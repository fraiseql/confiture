"""Unit tests for TempDatabase and pg_dump_schema."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.temp_database import (
    TempDatabase,
    _maintenance_url,
    _replace_dbname,
    clean_pg_dump_output,
    pg_dump_schema,
)
from confiture.exceptions import SchemaError

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


class TestMaintenanceUrl:
    def test_replaces_dbname_with_postgres(self) -> None:
        assert _maintenance_url("postgresql://user:pass@host:5432/myapp") == (
            "postgresql://user:pass@host:5432/postgres"
        )

    def test_preserves_query_params(self) -> None:
        url = "postgresql://user@host/mydb?sslmode=require"
        result = _maintenance_url(url)
        assert "/postgres?" in result
        assert "sslmode=require" in result

    def test_handles_no_dbname(self) -> None:
        result = _maintenance_url("postgresql://host:5432")
        assert result == "postgresql://host:5432/postgres"


class TestReplaceDbname:
    def test_replaces_database_component(self) -> None:
        result = _replace_dbname("postgresql://user:pass@host:5432/myapp", "new_db")
        assert result == "postgresql://user:pass@host:5432/new_db"


# ---------------------------------------------------------------------------
# TempDatabase context manager
# ---------------------------------------------------------------------------


class TestTempDatabase:
    @patch("confiture.core.temp_database.psycopg.connect")
    def test_creates_and_drops_database(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.info.server_version = 150000
        mock_connect.return_value = mock_conn

        td = TempDatabase("postgresql://localhost/myapp")

        temp_url = td.__enter__()

        # Should have connected to maintenance DB
        mock_connect.assert_called_once_with("postgresql://localhost/postgres", autocommit=True)

        # Should have created a temp database (via sql.SQL composition)
        create_call = mock_conn.execute.call_args_list[0]
        create_arg = str(create_call[0][0])
        assert "CREATE DATABASE" in create_arg

        # Returned URL should reference temp DB
        assert td._db_name in temp_url

        # Exit should drop the database
        td.__exit__(None, None, None)
        drop_calls = [c for c in mock_conn.execute.call_args_list if "DROP DATABASE" in str(c)]
        assert len(drop_calls) == 1
        assert "WITH (FORCE)" in str(drop_calls[0][0][0])

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_uses_terminate_backend_on_old_pg(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.info.server_version = 120000
        mock_connect.return_value = mock_conn

        td = TempDatabase("postgresql://localhost/myapp")
        td.__enter__()
        td.__exit__(None, None, None)

        execute_args = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
        assert any("pg_terminate_backend" in a for a in execute_args)
        assert any("DROP DATABASE" in a for a in execute_args)
        assert not any("WITH (FORCE)" in a for a in execute_args)

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_drops_database_even_on_schema_error(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.info.server_version = 150000
        mock_connect.return_value = mock_conn

        td = TempDatabase("postgresql://localhost/myapp")
        td.__enter__()
        td.__exit__(ValueError, ValueError("boom"), None)

        drop_calls = [c for c in mock_conn.execute.call_args_list if "DROP DATABASE" in str(c)]
        assert len(drop_calls) == 1

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_raises_schema_error_on_connection_failure(self, mock_connect: MagicMock) -> None:
        import psycopg

        mock_connect.side_effect = psycopg.OperationalError("connection refused")

        td = TempDatabase("postgresql://localhost/myapp")
        with pytest.raises(SchemaError, match="Cannot connect"):
            td.__enter__()

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_server_url_dbname_not_used_for_connection(self, mock_connect: MagicMock) -> None:
        """The maintenance connection must target 'postgres', not the user's DB."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.info.server_version = 150000
        mock_connect.return_value = mock_conn

        td = TempDatabase("postgresql://localhost/nonexistent_db")
        td.__enter__()

        # connect must have been called with /postgres, NOT /nonexistent_db
        connect_url = mock_connect.call_args[0][0]
        assert "/postgres" in connect_url
        assert "nonexistent_db" not in connect_url

        td.__exit__(None, None, None)

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_unique_db_name_per_instance(self, mock_connect: MagicMock) -> None:
        td1 = TempDatabase("postgresql://localhost/myapp")
        td2 = TempDatabase("postgresql://localhost/myapp")
        assert td1._db_name != td2._db_name

    @patch("confiture.core.temp_database.psycopg.connect")
    def test_reconnects_for_drop_if_conn_closed(self, mock_connect: MagicMock) -> None:
        mock_conn_enter = MagicMock()
        mock_conn_enter.closed = False
        mock_conn_enter.info.server_version = 150000

        mock_conn_drop = MagicMock()
        mock_conn_drop.closed = False

        mock_connect.side_effect = [mock_conn_enter, mock_conn_drop]

        td = TempDatabase("postgresql://localhost/myapp")
        td.__enter__()

        # Simulate closed connection
        mock_conn_enter.closed = True

        td.__exit__(None, None, None)

        # Should have reconnected
        assert mock_connect.call_count == 2


# ---------------------------------------------------------------------------
# apply_schema
# ---------------------------------------------------------------------------


class TestApplySchema:
    @patch("confiture.core.temp_database.apply_sql_via_psql")
    def test_delegates_to_psql_applier(self, mock_apply: MagicMock) -> None:
        td = TempDatabase("postgresql://localhost/myapp")
        td.apply_schema("postgresql://localhost/tmp_db", "CREATE TABLE t (id int);")

        mock_apply.assert_called_once_with(
            "postgresql://localhost/tmp_db", "CREATE TABLE t (id int);"
        )

    @patch("confiture.core.temp_database.apply_sql_via_psql")
    def test_reraises_schema_error_on_failure(self, mock_apply: MagicMock) -> None:
        mock_apply.side_effect = SchemaError("psql failed applying SQL: syntax error")

        td = TempDatabase("postgresql://localhost/myapp")
        with pytest.raises(SchemaError, match="syntax error"):
            td.apply_schema("postgresql://localhost/tmp_db", "BAD SQL;")

    @patch("confiture.core.temp_database.apply_sql_via_psql")
    def test_extension_error_has_specific_hint(self, mock_apply: MagicMock) -> None:
        mock_apply.side_effect = SchemaError('extension "postgis" does not exist')

        td = TempDatabase("postgresql://localhost/myapp")
        with pytest.raises(SchemaError) as exc_info:
            td.apply_schema("postgresql://localhost/tmp_db", "CREATE EXTENSION postgis;")

        assert "CREATE EXTENSION" in (exc_info.value.resolution_hint or "")


# ---------------------------------------------------------------------------
# pg_dump_schema
# ---------------------------------------------------------------------------


class TestPgDumpSchema:
    @patch("confiture.core.temp_database.subprocess.run")
    def test_returns_stdout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="CREATE TABLE t (id int);")
        result = pg_dump_schema("postgresql://localhost/mydb")
        assert result == "CREATE TABLE t (id int);"
        args, kwargs = mock_run.call_args
        assert args[0] == [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "postgresql://localhost/mydb",
        ]
        assert kwargs["check"] is True
        assert "env" in kwargs  # a libpq env (with optional PGPASSWORD) is passed

    @patch("confiture.core.temp_database.subprocess.run")
    def test_password_kept_off_argv(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        pg_dump_schema("postgresql://user:secret@host/mydb")
        args, kwargs = mock_run.call_args
        assert "secret" not in args[0][-1]  # the URL on argv carries no password
        assert kwargs["env"]["PGPASSWORD"] == "secret"

    @patch("confiture.core.temp_database.subprocess.run")
    def test_raises_on_missing_pg_dump(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(SchemaError, match="pg_dump not found"):
            pg_dump_schema("postgresql://localhost/mydb")

    @patch("confiture.core.temp_database.subprocess.run")
    def test_raises_on_version_mismatch(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1,
            "pg_dump",
            stderr="server version 16.0, pg_dump version 14.0",
        )
        with pytest.raises(SchemaError, match="older than the PostgreSQL server"):
            pg_dump_schema("postgresql://localhost/mydb")

    @patch("confiture.core.temp_database.subprocess.run")
    def test_raises_on_generic_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "pg_dump", stderr="connection refused"
        )
        with pytest.raises(SchemaError, match="pg_dump failed.*connection refused"):
            pg_dump_schema("postgresql://localhost/mydb")


# ---------------------------------------------------------------------------
# clean_pg_dump_output
# ---------------------------------------------------------------------------


class TestCleanPgDumpOutput:
    def test_strips_set_statements(self) -> None:
        raw = "SET statement_timeout = 0;\nCREATE TABLE t (id int);\n"
        assert "SET" not in clean_pg_dump_output(raw)
        assert "CREATE TABLE" in clean_pg_dump_output(raw)

    def test_strips_pg_catalog_set_config(self) -> None:
        raw = "SELECT pg_catalog.set_config('search_path', '', false);\nCREATE TABLE t (id int);\n"
        result = clean_pg_dump_output(raw)
        assert "pg_catalog" not in result
        assert "CREATE TABLE" in result

    def test_strips_dumped_comments(self) -> None:
        raw = "-- Dumped from database version 16.1\n-- Dumped by pg_dump version 16.1\nCREATE TABLE t (id int);\n"
        result = clean_pg_dump_output(raw)
        assert "Dumped" not in result
        assert "CREATE TABLE" in result

    def test_strips_create_extension(self) -> None:
        raw = "CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;\nCREATE TABLE t (id int);\n"
        result = clean_pg_dump_output(raw)
        assert "EXTENSION" not in result
        assert "CREATE TABLE" in result

    def test_strips_comment_on_extension(self) -> None:
        raw = "COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';\nCREATE TABLE t (id int);\n"
        result = clean_pg_dump_output(raw)
        assert "COMMENT ON EXTENSION" not in result

    def test_preserves_regular_comments(self) -> None:
        raw = "-- This is a regular comment\nCREATE TABLE t (id int);\n"
        result = clean_pg_dump_output(raw)
        assert "regular comment" in result

    def test_preserves_create_table(self) -> None:
        raw = (
            "SET statement_timeout = 0;\n"
            "SET lock_timeout = 0;\n"
            "SELECT pg_catalog.set_config('search_path', '', false);\n"
            "-- Dumped from database version 16.1\n"
            "CREATE TABLE public.users (\n"
            "    id bigint NOT NULL\n"
            ");\n"
        )
        result = clean_pg_dump_output(raw)
        assert result.strip() == ("CREATE TABLE public.users (\n    id bigint NOT NULL\n);")

    def test_empty_input(self) -> None:
        assert clean_pg_dump_output("") == ""
