"""One thin lexer over pglast (Phase 05, ANA-04 / ANA-05).

Ten hand-written scanners split statements, skipped comments and matched dollar
tags, and disagreed with each other on ``"a;b"`` identifiers, ``E'\\';'``
literals and nested tags. ``core/sql_lexer.py`` is the one place now: statement
splitting and comment stripping come from libpg_query's own scanner, parsing
from ``parse_sql``. The differ's index / enum / sequence / constraint passes walk
the AST, so a commented-out ``CREATE INDEX`` is nothing, not a change.
"""

from __future__ import annotations

import time

import pglast
import pytest

from confiture.core import sql_lexer
from confiture.core.differ import SchemaDiffer
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns

SPLIT_CASES = {
    "quoted_identifier_with_semicolon": (
        'select 1; create table "a;b" (x int);',
        ["select 1", 'create table "a;b" (x int)'],
    ),
    "escaped_quote_in_literal": ("select 'it''s;'; select 2", ["select 'it''s;'", "select 2"]),
    "e_string_with_backslash_quote": (r"select E'\';'; select 3", [r"select E'\';'", "select 3"]),
    "nested_dollar_tags": (
        "select $q$ ; $body$ ; $body$ $q$; select 4",
        ["select $q$ ; $body$ ; $body$ $q$", "select 4"],
    ),
    "nested_block_comments": (
        "select 1 /* a /* nested; */ b; */; select 5",
        ["select 1 /* a /* nested; */ b; */", "select 5"],
    ),
    "line_comment_with_semicolon": (
        "select 1 -- comment; here\n; select 6",
        ["select 1 -- comment; here", "select 6"],
    ),
    "invalid_sql_still_splits": ("THIS IS NOT SQL; select 7;", ["THIS IS NOT SQL", "select 7"]),
    "trailing_semicolon_and_blank": ("select 1;\n\n;", ["select 1"]),
}


@pytest.mark.parametrize("case", sorted(SPLIT_CASES), ids=sorted(SPLIT_CASES))
def test_split_statements_matches_pglast_split(case: str) -> None:
    sql, expected = SPLIT_CASES[case]
    assert sql_lexer.split_statements(sql) == expected
    if "NOT SQL" not in sql:
        assert sql_lexer.split_statements(sql) == list(pglast.split(sql, with_parser=True))


STRIP_CASES = {
    "line_comment": ("select 1 -- gone\nfrom t", "select 1 \nfrom t"),
    "block_comment": ("select /* gone */ 1", "select  1"),
    "nested_block_comment": ("select /* a /* b */ c */ 1", "select  1"),
    "dashes_inside_literal_kept": ("select 'a--b' -- c", "select 'a--b' "),
    "dashes_inside_dollar_body_kept": ("do $$ -- not a comment $$", "do $$ -- not a comment $$"),
    "quoted_identifier_kept": ('select "x--y" from t', 'select "x--y" from t'),
    "no_comments_untouched": ("select 1;", "select 1;"),
}


@pytest.mark.parametrize("case", sorted(STRIP_CASES), ids=sorted(STRIP_CASES))
def test_strip_comments(case: str) -> None:
    sql, expected = STRIP_CASES[case]
    assert sql_lexer.strip_comments(sql) == expected


def test_parse_yields_statements_with_locations() -> None:
    parsed = sql_lexer.parse("select 1;\n\ncreate table t (id int);")
    assert [type(p.stmt).__name__ for p in parsed] == ["SelectStmt", "CreateStmt"]
    assert [p.line for p in parsed] == [1, 3]


def test_statement_type_names_the_verb() -> None:
    assert sql_lexer.statement_type("CREATE TABLE t (id int)") == "CREATE"
    assert sql_lexer.statement_type("WITH x AS (SELECT 1) SELECT * FROM x") == "SELECT"
    assert sql_lexer.statement_type("INSERT INTO t VALUES (1)") == "INSERT"
    assert sql_lexer.statement_type("THIS IS NOT SQL") == "UNKNOWN"


def test_commented_out_ddl_is_nothing_to_the_differ() -> None:
    """ANA-04: the differ's index/enum/sequence/constraint passes walk the AST."""
    sql = """
CREATE TABLE t (id INT PRIMARY KEY, a INT);
-- CREATE INDEX idx_gone ON t (a);
/* CREATE TYPE mood AS ENUM ('sad'); */
-- CREATE SEQUENCE sq_gone START 5;
-- ALTER TABLE t ADD CONSTRAINT ck_gone CHECK (a > 0);
"""
    parsed = SchemaDiffer().parse_schema(sql)
    assert parsed.tables[0].indexes == []
    assert parsed.tables[0].check_constraints == []
    assert parsed.enum_types == []
    assert parsed.sequences == []


def test_real_index_enum_sequence_and_constraints_are_read_from_the_ast() -> None:
    sql = """
CREATE TABLE s.t (id INT PRIMARY KEY, a INT, b TEXT);
CREATE UNIQUE INDEX idx_t_a ON s.t (a, lower(b)) WHERE a > 1;
CREATE TYPE s.mood AS ENUM ('sad', 'ok');
CREATE SEQUENCE s.sq START WITH 10 INCREMENT BY 2 MINVALUE 1 MAXVALUE 100;
ALTER TABLE s.t ADD CONSTRAINT fk_t FOREIGN KEY (a) REFERENCES s.t (id) ON DELETE CASCADE;
ALTER TABLE s.t ADD CONSTRAINT ck_t CHECK (a > 0);
ALTER TABLE s.t ADD CONSTRAINT uq_t UNIQUE (a, b);
"""
    parsed = SchemaDiffer().parse_schema(sql)
    (table,) = parsed.tables
    (idx,) = table.indexes
    assert (idx.name, idx.columns, idx.unique, idx.where) == (
        "idx_t_a",
        ["a", "lower(b)"],
        True,
        "a > 1",
    )
    (fk,) = table.foreign_keys
    assert (fk.name, fk.columns, fk.ref_table, fk.ref_columns, fk.on_delete) == (
        "fk_t",
        ["a"],
        "t",
        ["id"],
        "CASCADE",
    )
    assert [(c.name, c.expression) for c in table.check_constraints] == [("ck_t", "a > 0")]
    assert [(u.name, u.columns) for u in table.unique_constraints] == [("uq_t", ["a", "b"])]
    assert [(e.schema, e.name, e.values) for e in parsed.enum_types] == [
        ("s", "mood", ["sad", "ok"])
    ]
    (seq,) = parsed.sequences
    assert (seq.schema, seq.name, seq.start, seq.increment, seq.min_value, seq.max_value) == (
        "s",
        "sq",
        10,
        2,
        1,
        100,
    )


def test_adversarial_dollar_input_is_fast() -> None:
    """The DO-block guards used to be regexes with catastrophic backtracking."""
    sql = (
        "DO $$ BEGIN " + "$a$ $ $b$ ; " * 2000 + " END $$;\n"
    ) * 3  # ~50 KB of tags and stray dollars
    assert len(sql) > 50_000
    started = time.perf_counter()
    sql_lexer.split_statements(sql)
    try:
        detect_non_idempotent_patterns(sql)
    except pglast.parser.ParseError:
        pass
    assert time.perf_counter() - started < 0.1
