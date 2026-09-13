"""``sql_lexer.blank_copy_blocks``: a COPY block costs its characters, not its lines.

A ``COPY … FROM stdin`` block is psql client protocol, not SQL, and pglast rejects
the whole text it appears in (#194). Deleting the block fixes the parse and moves
every line after it, which is fine for a differ that reports no positions and wrong
for a lint that reports ``file:line`` on every finding (#274).

Blanking keeps the block's newlines and replaces everything else with spaces, so a
position in the blanked text is the same position in the original — the technique
#270 established for a schema-qualified type name a compiler would not accept.
"""

from __future__ import annotations

import pglast.parser
import pytest

from confiture.core import sql_lexer
from confiture.core.sql_lexer import blank_copy_blocks

SQL = (
    "CREATE SCHEMA app;\n"
    "CREATE TABLE app.tb_widget (id uuid PRIMARY KEY, label text);\n"
    "COPY app.tb_widget (id, label) FROM stdin;\n"
    "0b6f1c2e-1111-4a4a-8888-000000000001\tfirst\n"
    "\\.\n"
    "CREATE TABLE app.tb_after (x int);\n"
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


class TestBlankingPreservesOffsets:
    def test_blanking_preserves_offsets(self) -> None:
        """Same length, same lines, and the block's own characters are spaces."""
        blanked = blank_copy_blocks(SQL)

        assert len(blanked) == len(SQL)
        assert blanked.count("\n") == SQL.count("\n")
        start = SQL.index("COPY")
        end = SQL.index("\\.") + len("\\.")
        assert set(blanked[start:end]) <= {" ", "\n"}

    def test_the_statements_around_the_block_still_parse(self) -> None:
        """pglast reads the text the block used to break, before it and after it."""
        statements = pglast.parser.parse_sql(blank_copy_blocks(SQL))

        assert [type(raw.stmt).__name__ for raw in statements] == [
            "CreateSchemaStmt",
            "CreateStmt",
            "CreateStmt",
        ]

    def test_a_location_still_indexes_the_original_text(self) -> None:
        """The last statement's offset finds it in ``SQL``, on the line it is written on."""
        statements = pglast.parser.parse_sql(blank_copy_blocks(SQL))

        offset = statements[-1].stmt_location
        assert SQL[offset:].startswith("CREATE TABLE app.tb_after")
        assert _line_of(SQL, offset) == _line_of(SQL, SQL.index("CREATE TABLE app.tb_after"))

    def test_the_raw_text_does_not_parse(self) -> None:
        """The premise: without blanking there is nothing to read at all."""
        with pytest.raises(pglast.parser.ParseError):
            pglast.parser.parse_sql(SQL)


class TestBlankingIsNotStripping:
    def test_text_without_a_block_is_unchanged(self) -> None:
        sql = "COPY t FROM '/path';\n-- COPY x FROM stdin\nSELECT 1;\n"
        assert blank_copy_blocks(sql) == sql

    def test_two_blocks_are_both_blanked(self) -> None:
        sql = (
            "COPY t (a) FROM stdin;\n1\n\\.\n"
            "CREATE TABLE u (b int);\n"
            "COPY u (b) FROM stdin;\n2\n\\.\n"
        )
        blanked = blank_copy_blocks(sql)

        assert len(blanked) == len(sql)
        assert blanked.count("\n") == sql.count("\n")
        assert [type(raw.stmt).__name__ for raw in pglast.parser.parse_sql(blanked)] == [
            "CreateStmt"
        ]

    def test_an_unterminated_block_runs_to_the_end(self) -> None:
        """No ``\\.``: the rest of the text is data, and blanking says so without hanging."""
        sql = "CREATE TABLE t (a int);\nCOPY t (a) FROM stdin;\n1\n2\n"
        blanked = blank_copy_blocks(sql)

        assert len(blanked) == len(sql)
        assert blanked.startswith("CREATE TABLE t (a int);\n")
        assert blanked[sql.index("COPY") :].strip() == ""

    def test_a_dollar_quoted_terminator_is_not_a_terminator(self) -> None:
        r"""A ``\.`` inside a routine body is body text, so the lexer never sees a block."""
        sql = "CREATE FUNCTION f() RETURNS text AS $$ SELECT '\\.' $$ LANGUAGE sql;\n"
        assert blank_copy_blocks(sql) == sql


class TestOneCopyBlockFunction:
    """The lexer answers "where are the COPY blocks" once, and blanking is the answer.

    ``strip_copy_blocks`` was the first answer (#194) and its only caller was
    ``core/differ.py``, which parses and then regex-scans. Blanking serves that
    caller unchanged *and* keeps a ``DIFFER_400`` position pointing at the real
    file, so keeping both would be two answers to one question — the standing
    rule ``test_one_sql_lexer.py`` exists to hold.
    """

    def test_the_lexer_exposes_no_stripping_variant(self) -> None:
        assert not hasattr(sql_lexer, "strip_copy_blocks")

    def test_the_stripped_fixture_is_blanked_in_place(self) -> None:
        """The case ``strip_copy_blocks`` used to shorten, kept at full length."""
        sql = (
            "CREATE TABLE t (a int);\nCOPY t (a) FROM stdin;\n1\n'\n\\.\nCREATE TABLE u (b int);\n"
        )

        blanked = blank_copy_blocks(sql)

        assert blanked == (
            "CREATE TABLE t (a int);\n                      \n \n \n  \nCREATE TABLE u (b int);\n"
        )
