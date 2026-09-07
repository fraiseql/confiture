"""psql meta-commands are refused before ``psql`` ever sees the file.

``apply_sql_via_psql`` hands schema and seed files to ``psql``, and ``psql``
executes backslash commands: ``\\!`` runs a shell command, ``\\copy … TO PROGRAM``
pipes data into one, ``\\i`` reads any file the operator can read.  A seed file is
repository content; the operator host is not.  D7: hard reject, no warning mode.

The scanner has to see the file the way ``psql`` does, or an attacker hides the
command where the scanner is not looking:

* a backslash is a command anywhere outside quotes, comments, dollar-quoted
  bodies and COPY data — ``SELECT 1 \\! id`` executes — so line-start is not
  enough;
* COPY data rows may legitimately begin with ``\\N``, so the block between
  ``COPY … FROM stdin;`` and ``\\.`` is data, not commands;
* quote characters inside COPY data are data too — a stray ``'`` in a data row
  must not swallow the ``\\.`` terminator and everything after it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core import psql_applier
from confiture.exceptions import SchemaError

_URL = "postgresql://localhost/confiture_db"


def _lines(sql: str) -> list[int]:
    return [m.line for m in psql_applier.find_meta_commands(sql)]


# ---------------------------------------------------------------------------
# Rejected
# ---------------------------------------------------------------------------


class TestRejected:
    @pytest.mark.parametrize(
        "command",
        [
            "\\! id",
            "\\copy t TO PROGRAM 'id'",
            "\\i /etc/passwd",
            "\\ir ../secrets.sql",
            "\\o /tmp/out",
            "\\set x `id`",
            "\\g",
            "\\gexec",
        ],
    )
    def test_meta_command_on_its_own_line_is_reported_with_its_line(self, command: str) -> None:
        sql = f"CREATE TABLE t (id int);\n{command}\nINSERT INTO t VALUES (1);\n"
        assert _lines(sql) == [2]

    def test_meta_command_after_sql_on_the_same_line(self) -> None:
        assert _lines("SELECT 1 \\! id\n") == [1]

    def test_meta_command_after_a_semicolon_on_the_same_line(self) -> None:
        assert _lines("SELECT 1; \\! id\n") == [1]

    def test_indented_meta_command(self) -> None:
        assert _lines("    \\! id\n") == [1]

    def test_every_offending_line_is_reported(self) -> None:
        sql = "\\! id\nSELECT 1;\n\\i x\n"
        assert _lines(sql) == [1, 3]

    def test_quote_inside_copy_data_does_not_hide_a_later_command(self) -> None:
        sql = "COPY t (a) FROM stdin;\nit's\n\\.\n\\! id\nSELECT 'closing quote';\n"
        assert _lines(sql) == [4]

    def test_dollar_inside_copy_data_does_not_hide_a_later_command(self) -> None:
        sql = "COPY t (a) FROM stdin;\n$$\n\\.\n\\! id\n"
        assert _lines(sql) == [4]

    def test_plain_string_does_not_escape_its_closing_quote(self) -> None:
        # standard_conforming_strings=on: '\' is a complete literal.
        assert _lines("SELECT '\\'; \\! id\n") == [1]

    def test_unterminated_string_still_reports_what_precedes_it(self) -> None:
        assert _lines("\\! id\nSELECT 'open\n") == [1]

    def test_copy_terminator_outside_copy_data_is_the_one_tolerated_backslash(self) -> None:
        # `\.` on its own line is the COPY terminator shape; psql treats it as
        # end-of-input, never as a shell.  Anything else is a command.
        assert _lines("\\.\n") == []
        assert _lines("\\.x\n") == [1]


# ---------------------------------------------------------------------------
# Accepted
# ---------------------------------------------------------------------------


class TestAccepted:
    def test_copy_block_with_terminator_and_backslash_data_rows(self) -> None:
        sql = "COPY t (a, b) FROM stdin;\n\\N\t1\nx\t\\N\n\\.\nSELECT 1;\n"
        assert _lines(sql) == []

    def test_copy_with_options_and_a_comment_on_the_statement(self) -> None:
        sql = "copy public.t (a) from STDIN with (format text); -- data follows\n\\N\n\\.\n"
        assert _lines(sql) == []

    def test_line_comment(self) -> None:
        assert _lines("-- \\! id\nSELECT 1; -- \\i x\n") == []

    def test_block_comment_including_nested(self) -> None:
        assert _lines("/* \\! id */ SELECT 1;\n/* a /* \\! id */ b */\n") == []

    def test_dollar_quoted_body_spanning_lines(self) -> None:
        sql = (
            "CREATE FUNCTION f() RETURNS text LANGUAGE sql AS $$\n"
            "  SELECT '\\! inside body'\n"
            "$$;\n"
            "CREATE FUNCTION g() RETURNS text LANGUAGE plpgsql AS $body$\n"
            "BEGIN\n"
            "  RETURN E'\\\\! nested $$ \\\\i';\n"
            "END\n"
            "$body$;\n"
        )
        assert _lines(sql) == []

    def test_single_quoted_literal(self) -> None:
        assert _lines("INSERT INTO t VALUES ('\\! id');\nSELECT 'a\n\\! b';\n") == []

    def test_escape_string_with_escaped_quote(self) -> None:
        # E'\'' — the backslash escapes the quote; the literal runs to the last '.
        assert _lines("SELECT E'it\\'s \\\\! fine';\n") == []

    def test_double_quoted_identifier(self) -> None:
        assert _lines('CREATE TABLE "\\! weird" (id int);\n') == []

    def test_positional_parameter_is_not_a_dollar_quote(self) -> None:
        assert _lines("PREPARE p AS SELECT $1;\nSELECT '\\! x';\n") == []

    def test_identifier_containing_a_dollar_is_not_a_dollar_quote(self) -> None:
        assert _lines("SELECT a$b$c FROM t;\nSELECT '\\! x';\n") == []

    def test_ordinary_schema_has_nothing_to_report(self) -> None:
        sql = Path("db/schema").rglob("*.sql")
        text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(sql))
        assert text, "repo schema fixture missing"
        assert _lines(text) == []


# ---------------------------------------------------------------------------
# The applier refuses before running psql
# ---------------------------------------------------------------------------


class TestApplierRefuses:
    @pytest.fixture
    def run_never_called(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    def test_inline_sql_with_meta_command_raises_and_names_the_line(
        self, run_never_called: list[list[str]]
    ) -> None:
        sql = "CREATE TABLE t (id int);\n\\! id\n"
        with pytest.raises(SchemaError) as excinfo:
            psql_applier.apply_sql_via_psql(_URL, sql)

        assert run_never_called == []
        message = str(excinfo.value)
        assert "line 2" in message
        assert "\\!" in message
        assert excinfo.value.error_code == "SCHEMA_205"

    def test_sql_file_with_meta_command_raises_and_names_the_file(
        self, tmp_path: Path, run_never_called: list[list[str]]
    ) -> None:
        seed = tmp_path / "010_seed.sql"
        seed.write_text("INSERT INTO t VALUES (1);\nSELECT 1;\n\\copy t TO PROGRAM 'id'\n")

        with pytest.raises(SchemaError) as excinfo:
            psql_applier.apply_sql_via_psql(_URL, sql_file=seed)

        assert run_never_called == []
        message = str(excinfo.value)
        assert "010_seed.sql" in message
        assert "line 3" in message

    def test_clean_copy_seed_still_runs(self, run_never_called: list[list[str]]) -> None:
        sql = "COPY t (a) FROM stdin;\n\\N\n\\.\n"
        psql_applier.apply_sql_via_psql(_URL, sql)
        assert len(run_never_called) == 1

    def test_reject_meta_commands_is_the_public_entry(self) -> None:
        with pytest.raises(SchemaError, match=r"seed.sql"):
            psql_applier.reject_meta_commands("\\! id\n", source=Path("seed.sql"))
        psql_applier.reject_meta_commands("SELECT 1;\n", source=None)
