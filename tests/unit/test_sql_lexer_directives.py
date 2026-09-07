"""``sql_lexer.comments`` / ``directives`` / ``strip_copy_blocks``.

A ``-- confiture:<name>`` comment directive used to be found by one regex per
rule, each walking lines on its own: a directive inside a dollar-quoted body or
a COPY data row was a directive, and each rule attached it to "the next line"
by its own rule. The lexer reads comment tokens, so only a real comment is a
directive, and it attaches to the first statement after it.
"""

from __future__ import annotations

from confiture.core.sql_lexer import Directive, comments, directives, strip_copy_blocks


class TestDirectives:
    def test_attaches_to_the_statement_below(self) -> None:
        sql = "-- confiture:owner-only\nCREATE TABLE t (id int);\n"
        assert directives(sql) == [
            Directive(name="owner-only", argument=None, line=1, statement_line=2)
        ]

    def test_blank_lines_and_other_comments_do_not_detach_it(self) -> None:
        sql = "-- confiture:owner-skip\n\n-- audit table\n/* block */\nCREATE TABLE t (id int);\n"
        assert [d.statement_line for d in directives(sql)] == [5]

    def test_a_statement_in_between_detaches_it(self) -> None:
        sql = "-- confiture:owner-skip\nSET ROLE x;\nCREATE TABLE t (id int);\n"
        assert [d.statement_line for d in directives(sql)] == [2]

    def test_nothing_below_means_no_statement(self) -> None:
        assert directives("SELECT 1;\n-- confiture:owner-only\n")[0].statement_line is None

    def test_argument_is_the_rest_of_the_comment(self) -> None:
        sql = "-- confiture:run-as app_owner\nCREATE TABLE t (id int);\n"
        assert directives(sql)[0] == Directive("run-as", "app_owner", 1, 2)

    def test_name_is_case_folded_and_trailing_text_tolerated(self) -> None:
        sql = "--   Confiture:OWNER-ONLY — audit table\nCREATE TABLE t (id int);\n"
        (directive,) = directives(sql)
        assert directive.name == "owner-only"
        assert directive.argument == "— audit table"

    def test_inside_a_dollar_quoted_body_is_not_a_directive(self) -> None:
        sql = "DO $$\n-- confiture:owner-skip $$;\nCREATE TABLE t (id int);\n"
        assert directives(sql) == []

    def test_inside_copy_data_is_not_a_directive(self) -> None:
        sql = "COPY t (a) FROM stdin;\n-- confiture:owner-skip\n\\.\nCREATE TABLE u (id int);\n"
        assert directives(sql) == []

    def test_a_block_comment_is_not_a_directive(self) -> None:
        assert directives("/* confiture:owner-only */\nCREATE TABLE t (id int);\n") == []

    def test_other_comments_are_not_directives(self) -> None:
        assert directives("-- confiture is great\n-- owner-only\nSELECT 1;\n") == []

    def test_after_a_scanner_error_nothing_is_read(self) -> None:
        sql = "-- confiture:owner-only\nSELECT 'open\n-- confiture:owner-skip\n"
        assert [d.name for d in directives(sql)] == ["owner-only"]


class TestComments:
    def test_line_and_block_comments_with_their_lines(self) -> None:
        sql = "-- Strategy: rebuild\nSELECT 1; /* a\n b */\n"
        assert [(c.kind, c.text, c.line) for c in comments(sql)] == [
            ("line", "Strategy: rebuild", 1),
            ("block", "a\n b", 2),
        ]

    def test_a_comment_inside_a_literal_is_not_a_comment(self) -> None:
        assert comments("SELECT '-- x', $$ /* y */ $$;") == []


class TestStripCopyBlocks:
    def test_removes_the_statement_and_its_data(self) -> None:
        sql = (
            "CREATE TABLE t (a int);\nCOPY t (a) FROM stdin;\n1\n'\n\\.\nCREATE TABLE u (b int);\n"
        )
        assert strip_copy_blocks(sql) == "CREATE TABLE t (a int);\nCREATE TABLE u (b int);\n"

    def test_text_without_a_block_is_unchanged(self) -> None:
        sql = "COPY t FROM '/path';\n-- COPY x FROM stdin\nSELECT 1;\n"
        assert strip_copy_blocks(sql) == sql
