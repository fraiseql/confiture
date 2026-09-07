"""``strip_transaction_wrappers`` strips only top-level ``BEGIN`` / ``COMMIT`` lines.

Top-level means the line's code — what :func:`confiture.core.sql_lexer.code_text`
leaves after blanking comments, string literals and dollar-quoted bodies — is
exactly the wrapper. The ``BEGIN`` of a ``DO $$ … $$`` block, a ``'BEGIN'``
literal and a ``-- BEGIN`` comment are never wrappers.
"""

from __future__ import annotations

from confiture.core.sql_utils import strip_transaction_wrappers


class TestTopLevelLines:
    def test_simple_sql(self) -> None:
        sql = "BEGIN;\nCREATE TABLE t (id INT);\nCOMMIT;\n"
        assert strip_transaction_wrappers(sql) == "CREATE TABLE t (id INT);\n"

    def test_inside_do_block(self) -> None:
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "    INSERT INTO t VALUES (1);\n"
            "EXCEPTION\n"
            "    WHEN OTHERS THEN NULL;\n"
            "END $$;\n"
        )
        assert strip_transaction_wrappers(sql) == sql

    def test_dollar_quote_with_tag(self) -> None:
        sql = (
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $body$\n"
            "BEGIN\n"
            "    NULL;\n"
            "END\n"
            "$body$;\n"
        )
        assert strip_transaction_wrappers(sql) == sql

    def test_string_with_begin_inside(self) -> None:
        sql = "INSERT INTO t VALUES ('BEGIN');\n"
        assert strip_transaction_wrappers(sql) == sql

    def test_line_comment_with_begin(self) -> None:
        sql = "-- BEGIN\nSELECT 1;\n"
        assert strip_transaction_wrappers(sql) == sql

    def test_block_comment_spanning_lines(self) -> None:
        sql = "/* BEGIN\n   inside */\nSELECT 1;\n"
        assert strip_transaction_wrappers(sql) == sql

    def test_nested_dollar_quote_with_inner_double_dollar(self) -> None:
        sql = "DO $body$\nBEGIN\n    RAISE NOTICE $$inner$$;\nEND $body$;\n"
        assert strip_transaction_wrappers(sql) == sql

    def test_doubled_quote_escape(self) -> None:
        sql = "INSERT INTO t VALUES ('it''s fine');\nBEGIN;\n"
        assert strip_transaction_wrappers(sql) == "INSERT INTO t VALUES ('it''s fine');\n"

    def test_wrapper_followed_by_a_comment_is_a_wrapper(self) -> None:
        sql = "BEGIN; -- start\nSELECT 1;\n"
        assert strip_transaction_wrappers(sql) == "SELECT 1;\n"

    def test_empty_sql(self) -> None:
        assert strip_transaction_wrappers("") == ""
