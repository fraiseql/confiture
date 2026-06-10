"""Unit tests for the shared COPY-aware ``psql`` applier.

Covers the argv contract, stdin vs ``-f <path>`` routing, the missing-binary and
non-zero-exit ``SchemaError`` paths (with credential redaction), and the inline
``COPY … FROM stdin`` detection predicate used as a safety-net hint.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core.psql_applier import apply_sql_via_psql, contains_inline_copy
from confiture.exceptions import SchemaError

_URL = "postgresql://localhost/confiture_db"


class TestApplySqlViaPsql:
    def test_inline_sql_argv_and_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["input"] = kwargs.get("input")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        apply_sql_via_psql(_URL, "CREATE TABLE t (id int);")

        assert captured["argv"] == [
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            _URL,
            "-f",
            "-",
        ]
        assert captured["input"] == "CREATE TABLE t (id int);"

    def test_sql_file_uses_dash_f_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["input"] = kwargs.get("input")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        apply_sql_via_psql(_URL, sql_file=Path("/tmp/seed_001.sql"))

        assert captured["argv"][-2:] == ["-f", "/tmp/seed_001.sql"]
        assert captured["input"] is None

    def test_requires_exactly_one_source(self) -> None:
        with pytest.raises(ValueError):
            apply_sql_via_psql(_URL)
        with pytest.raises(ValueError):
            apply_sql_via_psql(_URL, "SELECT 1;", sql_file=Path("/tmp/x.sql"))

    def test_missing_psql_raises_schema_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):
            raise FileNotFoundError("psql")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SchemaError, match="psql not found"):
            apply_sql_via_psql(_URL, "SELECT 1;")

    def test_missing_psql_with_copy_hints_at_artifact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):
            raise FileNotFoundError("psql")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SchemaError) as exc_info:
            apply_sql_via_psql(_URL, "COPY t FROM stdin;\n1\tx\n\\.\n")

        assert "from-artifact" in (exc_info.value.resolution_hint or "")

    def test_nonzero_exit_redacts_url_and_keeps_stderr_tail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):
            raise subprocess.CalledProcessError(
                1,
                "psql",
                stderr="psql:-:1: ERROR:  syntax error at or near \"BAD\"",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SchemaError) as exc_info:
            apply_sql_via_psql("postgresql://user:secret@host/db", "BAD;")

        message = str(exc_info.value)
        assert "syntax error" in message
        assert "secret" not in message
        assert "***" in message

    def test_success_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda argv, **kwargs: MagicMock(returncode=0, stdout="", stderr=""),
        )
        assert apply_sql_via_psql(_URL, "SELECT 1;") is None


class TestContainsInlineCopy:
    def test_detects_from_stdin(self) -> None:
        assert contains_inline_copy("COPY t FROM stdin;")

    def test_detects_with_columns_and_options(self) -> None:
        assert contains_inline_copy("COPY t (a, b) FROM STDIN WITH (FORMAT csv);")

    def test_server_side_file_not_detected(self) -> None:
        assert not contains_inline_copy("COPY t FROM '/path/data.csv';")

    def test_line_comment_copy_not_detected(self) -> None:
        assert not contains_inline_copy("-- COPY t FROM stdin\nSELECT 1;")

    def test_block_comment_copy_not_detected(self) -> None:
        assert not contains_inline_copy("/* COPY t FROM stdin */\nSELECT 1;")

    def test_plain_ddl_not_detected(self) -> None:
        assert not contains_inline_copy("CREATE TABLE t (id int);")
