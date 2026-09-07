"""``sql_lexer.tokens`` / ``sql_lexer.code_text``: what is SQL code, from the scanner.

``psql`` executes a backslash command wherever it sits outside quotes, comments,
dollar-quoted bodies and ``COPY … FROM stdin`` data, so the applier has to see a
file the way ``psql``'s lexer does. That decision used to live in a hand-written
line lexer in ``psql_applier``; it comes from libpg_query's scanner now, with
the two things the scanner does not know layered on top: a COPY data block is
skipped line by line up to its ``\\.`` terminator, and a scanner error (an
unterminated string) ends the code — everything after it is opaque, which is
what ``psql`` would do too.
"""

from __future__ import annotations

import pytest

from confiture.core.sql_lexer import code_text, tokens


def _names(sql: str) -> list[str]:
    return [t.name for t in tokens(sql)]


class TestCodeTextShape:
    def test_same_lines_same_lengths(self) -> None:
        sql = "SELECT 'a\nb' AS x; -- c\n/* d\ne */ SELECT 1;\n"
        blanked = code_text(sql).text
        assert blanked.count("\n") == sql.count("\n")
        assert [len(line) for line in blanked.split("\n")] == [
            len(line) for line in sql.split("\n")
        ]

    def test_code_is_kept_in_place(self) -> None:
        sql = "SELECT 1 \\! id"
        assert code_text(sql).text == "SELECT 1 \\! id"

    def test_empty_text(self) -> None:
        assert code_text("").text == ""
        assert code_text("").copy_blocks == 0


def _blanked(sql: str, *non_code: str) -> str:
    """``sql`` with each ``non_code`` substring replaced by spaces of the same length."""
    for piece in non_code:
        assert piece in sql, piece
        sql = sql.replace(piece, " " * len(piece))
    return sql


class TestBlanked:
    @pytest.mark.parametrize(
        ("sql", "non_code"),
        [
            ("SELECT 1; -- \\! id", ["-- \\! id"]),
            ("/* \\! */ SELECT 1", ["/* \\! */"]),
            ("/* a /* \\! */ b */ SELECT 1", ["/* a /* \\! */ b */"]),
            ("SELECT '\\! x'", ["'\\! x'"]),
            ("SELECT E'it\\'s \\\\! fine'", ["E'it\\'s \\\\! fine'"]),
            ("SELECT '\\'; \\! id", ["'\\'"]),
            ('CREATE TABLE "\\! weird" (id int)', ['"\\! weird"']),
            ("SELECT $$ \\! $$", ["$$ \\! $$"]),
            ("SELECT $b$ $$ \\! $$ $b$", ["$b$ $$ \\! $$ $b$"]),
            ("PREPARE p AS SELECT $1", []),
            ("SELECT a$b$c FROM t", []),
        ],
    )
    def test_non_code_becomes_spaces(self, sql: str, non_code: list[str]) -> None:
        assert code_text(sql).text == _blanked(sql, *non_code)

    def test_dollar_body_spanning_lines_keeps_its_newlines(self) -> None:
        sql = "CREATE FUNCTION f() RETURNS text AS $$\n  SELECT '\\! x'\n$$ LANGUAGE sql;\n"
        blanked = code_text(sql).text
        assert blanked.split("\n")[1] == " " * len("  SELECT '\\! x'")
        assert blanked.split("\n")[2] == "   LANGUAGE sql;"


class TestCopyData:
    def test_data_rows_and_terminator_are_not_code(self) -> None:
        sql = "COPY t (a) FROM stdin;\nit's\n$$\n\\N\t1\n\\.\nSELECT 'x'; \\! id\n"
        result = code_text(sql)
        lines = result.text.split("\n")
        assert lines[0] == "COPY t (a) FROM stdin;"
        assert lines[1:5] == [" " * 4, " " * 2, " " * 4, " " * 2]
        assert lines[5] == _blanked("SELECT 'x'; \\! id", "'x'")
        assert result.copy_blocks == 1

    def test_rest_of_the_copy_line_is_still_code(self) -> None:
        sql = "COPY t (a) FROM stdin; \\! id -- c\n1\n\\.\n"
        assert code_text(sql).text.split("\n")[0] == "COPY t (a) FROM stdin; \\! id     "

    def test_two_blocks(self) -> None:
        sql = "COPY a FROM stdin;\n1\n\\.\nCOPY b FROM stdin;\n'\n\\.\nSELECT 1;\n"
        result = code_text(sql)
        assert result.copy_blocks == 2
        assert result.text.split("\n")[6] == "SELECT 1;"

    def test_block_without_terminator_runs_to_the_end(self) -> None:
        sql = "COPY t FROM stdin;\n\\! id\n\\i x\n"
        result = code_text(sql)
        assert result.text == "COPY t FROM stdin;\n     \n    \n"
        assert result.copy_blocks == 1

    @pytest.mark.parametrize(
        "sql",
        [
            "COPY t FROM '/path/data.csv';",
            "-- COPY t FROM stdin\nSELECT 1;",
            "/* COPY t FROM stdin */\nSELECT 1;",
            "INSERT INTO doc (body) VALUES ('intro\nCOPY x FROM stdin\nmore');",
            "CREATE FUNCTION f() RETURNS text AS $body$\nCOPY t FROM stdin\n$body$ LANGUAGE sql;",
            "COPY (SELECT 1) TO stdout;",
        ],
    )
    def test_not_a_data_block(self, sql: str) -> None:
        assert code_text(sql).copy_blocks == 0

    def test_lowercase_and_options(self) -> None:
        sql = "copy public.t (a) from STDIN with (format text); -- data follows\n\\N\n\\.\n"
        assert code_text(sql).copy_blocks == 1
        assert "\\" not in code_text(sql).text.split("\n")[1]


class TestScannerErrors:
    def test_what_precedes_an_unterminated_string_is_code(self) -> None:
        sql = "\\! id\nSELECT 'open\n"
        assert code_text(sql).text == "\\! id\nSELECT      \n"

    def test_an_unterminated_string_inside_copy_data_does_not_end_the_code(self) -> None:
        sql = "COPY t (a) FROM stdin;\nit's\n\\.\n\\! id\n"
        assert code_text(sql).text.split("\n")[3] == "\\! id"

    def test_only_an_error_returns_no_tokens(self) -> None:
        assert tokens("'open") == []


class TestTokens:
    def test_offsets_are_absolute_across_a_data_block(self) -> None:
        sql = "COPY t FROM stdin;\n1\n\\.\nSELECT 1;\n"
        select = [t for t in tokens(sql) if t.name == "SELECT"]
        assert len(select) == 1
        assert sql[select[0].start : select[0].end + 1] == "SELECT"
        assert select[0].start == sql.index("SELECT")

    def test_data_that_opens_a_dollar_quote_does_not_swallow_the_code_after_it(self) -> None:
        sql = "COPY t FROM stdin;\na$x$b\n\\.\nSELECT 1;\n"
        assert "SELECT" in _names(sql)

    def test_data_tokens_are_not_reported(self) -> None:
        sql = "COPY t FROM stdin;\n1\t2\n\\.\n"
        assert _names(sql) == ["COPY", "IDENT", "FROM", "STDIN", "ASCII_59"]

    def test_comments_are_tokens(self) -> None:
        assert _names("-- a\nSELECT 1 /* b */") == ["SQL_COMMENT", "SELECT", "ICONST", "C_COMMENT"]
