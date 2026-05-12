"""Unit tests for SchemaSnapshotGenerator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.schema_snapshot import SchemaSnapshotGenerator


class TestSchemaSnapshotGenerator:
    """Tests for SchemaSnapshotGenerator."""

    def test_write_snapshot_creates_correct_filename(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "CREATE TABLE tb_users (id bigint);"
            mock_builder_cls.return_value = mock_builder

            path = gen.write_snapshot("local", "007", "add_payments", Path("/project"))

        assert path == snapshots_dir / "007_add_payments.sql"

    def test_write_snapshot_creates_directory(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "new" / "snapshots"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "-- schema"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("local", "001", "init", None)

        assert snapshots_dir.exists()

    def test_write_snapshot_writes_schema_content(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)
        expected_sql = "CREATE TABLE tb_orders (id bigint NOT NULL);"

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = expected_sql
            mock_builder_cls.return_value = mock_builder

            path = gen.write_snapshot("local", "003", "add_orders", Path("/project"))

        assert path.read_text() == expected_sql

    def test_write_snapshot_delegates_to_schema_builder(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)
        project_dir = Path("/my/project")

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "SELECT 1;"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("production", "010", "upgrade_pks", project_dir)

        mock_builder_cls.assert_called_once_with(env="production", project_dir=project_dir)
        mock_builder.build.assert_called_once_with(schema_only=True)

    def test_write_snapshot_overwrites_existing_file(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        snapshots_dir.mkdir()
        existing = snapshots_dir / "005_migration.sql"
        existing.write_text("old content")
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "new content"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("local", "005", "migration", None)

        assert existing.read_text() == "new content"


class TestSchemaSnapshotGeneratorLiveMode:
    """Tests for live-snapshot mode (database_url parameter)."""

    def test_live_snapshot_calls_temp_database_and_pg_dump(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        schema_sql = "CREATE TABLE t (id int);"
        pg_dump_output = "SET statement_timeout = 0;\nCREATE TABLE public.t (\n    id integer\n);\n"

        with (
            patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls,
            patch("confiture.core.temp_database.psycopg.connect") as mock_connect,
            patch("confiture.core.temp_database.subprocess.run") as mock_run,
        ):
            mock_builder = MagicMock()
            mock_builder.build.return_value = schema_sql
            mock_builder_cls.return_value = mock_builder

            # TempDatabase mock
            mock_maint_conn = MagicMock()
            mock_maint_conn.closed = False
            mock_maint_conn.info.server_version = 150000

            mock_schema_conn = MagicMock()
            mock_schema_conn.__enter__ = MagicMock(return_value=mock_schema_conn)
            mock_schema_conn.__exit__ = MagicMock(return_value=False)

            mock_connect.side_effect = [mock_maint_conn, mock_schema_conn, mock_maint_conn]

            mock_run.return_value = MagicMock(stdout=pg_dump_output)

            path = gen.write_snapshot(
                "local",
                "007",
                "add_partitions",
                Path("/project"),
                database_url="postgresql://localhost/myapp",
            )

        content = path.read_text()
        # Should have live header
        assert "Live snapshot generated by confiture" in content
        # Should have cleaned pg_dump output (no SET lines)
        assert "SET statement_timeout" not in content
        # Should contain actual DDL
        assert "CREATE TABLE public.t" in content

    def test_live_snapshot_header_includes_timestamp(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with (
            patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls,
            patch("confiture.core.temp_database.psycopg.connect") as mock_connect,
            patch("confiture.core.temp_database.subprocess.run") as mock_run,
        ):
            mock_builder = MagicMock()
            mock_builder.build.return_value = "SELECT 1;"
            mock_builder_cls.return_value = mock_builder

            mock_conn = MagicMock()
            mock_conn.closed = False
            mock_conn.info.server_version = 150000
            mock_schema_conn = MagicMock()
            mock_schema_conn.__enter__ = MagicMock(return_value=mock_schema_conn)
            mock_schema_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.side_effect = [mock_conn, mock_schema_conn, mock_conn]

            mock_run.return_value = MagicMock(stdout="CREATE TABLE t (id int);\n")

            path = gen.write_snapshot(
                "local",
                "001",
                "init",
                None,
                database_url="postgresql://localhost/myapp",
            )

        content = path.read_text()
        assert "Generated at:" in content
        assert "temporary database from schema DDL" in content

    def test_static_snapshot_when_no_database_url(self, tmp_path: Path) -> None:
        """Without database_url, write_snapshot uses static concatenation."""
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)
        expected = "CREATE TABLE t (id int);"

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = expected
            mock_builder_cls.return_value = mock_builder

            path = gen.write_snapshot("local", "001", "init", None)

        # Static path: raw schema SQL, no header
        assert path.read_text() == expected

    def test_live_snapshot_strips_pg_dump_noise(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        noisy_output = (
            "SET statement_timeout = 0;\n"
            "SET lock_timeout = 0;\n"
            "SELECT pg_catalog.set_config('search_path', '', false);\n"
            "-- Dumped from database version 16.1\n"
            "-- Dumped by pg_dump version 16.1\n"
            "CREATE EXTENSION IF NOT EXISTS plpgsql;\n"
            "COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL';\n"
            "CREATE TABLE public.users (\n"
            "    id bigint NOT NULL\n"
            ");\n"
        )

        with (
            patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls,
            patch("confiture.core.temp_database.psycopg.connect") as mock_connect,
            patch("confiture.core.temp_database.subprocess.run") as mock_run,
        ):
            mock_builder = MagicMock()
            mock_builder.build.return_value = "SELECT 1;"
            mock_builder_cls.return_value = mock_builder

            mock_conn = MagicMock()
            mock_conn.closed = False
            mock_conn.info.server_version = 150000
            mock_schema_conn = MagicMock()
            mock_schema_conn.__enter__ = MagicMock(return_value=mock_schema_conn)
            mock_schema_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.side_effect = [mock_conn, mock_schema_conn, mock_conn]

            mock_run.return_value = MagicMock(stdout=noisy_output)

            path = gen.write_snapshot(
                "local",
                "001",
                "init",
                None,
                database_url="postgresql://localhost/myapp",
            )

        content = path.read_text()
        assert "SET statement_timeout" not in content
        assert "SET lock_timeout" not in content
        assert "pg_catalog.set_config" not in content
        assert "Dumped from" not in content
        assert "Dumped by" not in content
        assert "CREATE EXTENSION" not in content
        assert "COMMENT ON EXTENSION" not in content
        assert "CREATE TABLE public.users" in content
