"""Unit tests for the dollar-quote-aware top-level line scanner.

The scanner in ``confiture.core.sql_utils`` distinguishes top-level SQL
from text inside dollar-quoted blocks, single-quoted strings, ``--`` line
comments, and ``/* ... */`` block comments. It is the primitive that
makes ``strip_transaction_wrappers`` (#132) and the optional static
transaction-control lint (#133) dollar-quote-aware.
"""

from confiture.core.sql_utils import _iter_top_level_lines


def _strippable_indices(sql: str) -> set[int]:
    """Return the 0-indexed line numbers the scanner reports as top-level."""
    return {idx for idx, _, top in _iter_top_level_lines(sql) if top}


class TestScanner:
    def test_simple_sql(self):
        sql = "BEGIN;\nCREATE TABLE t (id INT);\nCOMMIT;\n"
        assert _strippable_indices(sql) == {0, 1, 2}

    def test_inside_do_block(self):
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "    INSERT INTO t VALUES (1);\n"
            "EXCEPTION\n"
            "    WHEN OTHERS THEN NULL;\n"
            "END $$;\n"
        )
        # Lines 0 and 5 are top-level (DO $$ opens, END $$ closes). Lines 1–4
        # are inside the dollar-quoted block.
        assert _strippable_indices(sql) == {0, 5}

    def test_dollar_quote_with_tag(self):
        sql = (
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $body$\n"
            "BEGIN\n"
            "    NULL;\n"
            "END\n"
            "$body$;\n"
        )
        assert _strippable_indices(sql) == {0, 4}

    def test_string_with_begin_inside(self):
        sql = "INSERT INTO t VALUES ('BEGIN');\n"
        # The 'BEGIN' substring is inside a string, so part of the line
        # crosses a string boundary. Conservative answer: not strippable.
        assert _strippable_indices(sql) == set()

    def test_line_comment_with_begin(self):
        sql = "-- BEGIN\nSELECT 1;\n"
        assert _strippable_indices(sql) == {1}

    def test_block_comment_spanning_lines(self):
        sql = "/* BEGIN\n   inside */\nSELECT 1;\n"
        assert _strippable_indices(sql) == {2}

    def test_nested_dollar_quote_with_inner_double_dollar(self):
        sql = "DO $body$\nBEGIN\n    RAISE NOTICE $$inner$$;\nEND $body$;\n"
        # $$ inside $body$ is a literal, not a close. Only $body$ closes.
        assert _strippable_indices(sql) == {0, 3}

    def test_doubled_quote_escape(self):
        sql = "INSERT INTO t VALUES ('it''s fine');\nBEGIN;\n"
        assert _strippable_indices(sql) == {1}

    def test_empty_sql(self):
        assert _strippable_indices("") == set()

    def test_returns_correct_line_text(self):
        """The yielded tuple includes the line text verbatim."""
        sql = "BEGIN;\nSELECT 1;\n"
        lines = list(_iter_top_level_lines(sql))
        assert lines[0][1] == "BEGIN;\n"
        assert lines[1][1] == "SELECT 1;\n"
