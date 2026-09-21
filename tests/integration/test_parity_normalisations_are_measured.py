"""Where a live catalog and the DDL it was built from disagree — measured, not assumed.

``tests/integration/test_parse_live_parity.py`` asserts that a database read through
``core/live_catalog`` equals the tree it was applied from, read through the lint
inventory, *after* ``schema_model.normalise_for_parity``. Every normalisation that
function applies is one of the disagreements below. Each test asserts that the
disagreement still **exists** on the server the suite runs against, so a
normalisation cannot outlive its cause: the day PostgreSQL stops generating a name
or adding a cast, the test fails and the normalisation goes.

Measured on PostgreSQL 15 (CI) and 18.4 (local), 2026-09-21:

1. an unnamed constraint gets a generated name (``child_pid_fkey``);
2. a stored default is PostgreSQL's analysed expression (``'x'::text``), not the
   text the author wrote;
3. a stored CHECK is analysed too: ``IN (…)`` is written back as ``= ANY (ARRAY[…])``;
4. a stored generation expression, index expression or partial-index predicate carries
   the implicit casts the analyser added;
5. ``format_type`` spells a type PostgreSQL's way (``character varying(50)``), which
   is why a column is compared by ``type_key``;
6. a ``serial`` column is an ``integer`` with a ``nextval`` default and a sequence the
   column owns — none of which the tree wrote;
7. a sequence's unset bounds read back as the type's own bounds;
8. a relation's schema is always known to the catalog, and ``pg_get_indexdef`` /
   ``pg_get_constraintdef`` spell it only when ``search_path`` would not find it;
9. a routine's argument and result types are ``format_type``'s spelling, not the
   file's (``int8`` reads back ``bigint``);
10. a view's query is stored as a parse tree and read back deparsed.

And one the first draft of the plan listed that does **not** exist: an index whose
statement writes no ``USING`` is ``btree`` on both sides, because PostgreSQL's
grammar fills in the default before the parse tree is built.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest

from confiture.core.linting.inventory import build_model


@pytest.fixture
def conn(fresh_database_factory: Callable[[str], str]):
    with psycopg.connect(fresh_database_factory("confiture_parity"), autocommit=True) as c:
        yield c


def _one(conn: psycopg.Connection, sql: str, *args: object) -> object:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def test_an_unnamed_constraint_is_given_a_name(conn: psycopg.Connection) -> None:
    ddl = (
        "CREATE TABLE parent (id INT PRIMARY KEY); CREATE TABLE child (pid INT REFERENCES parent);"
    )
    conn.execute(ddl)
    live = _one(
        conn,
        "SELECT conname FROM pg_constraint WHERE conrelid = 'child'::regclass AND contype = 'f'",
    )
    parsed = build_model(ddl).tables
    (fk,) = next(t for t in parsed.values() if t.name == "child").constraints
    assert (fk.name, live) == ("", "child_pid_fkey")


def test_a_default_is_stored_analysed(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (c TEXT DEFAULT 'x', n INT DEFAULT (1 + 2))")
    stored = [
        row[0]
        for row in conn.execute(
            "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef"
            " WHERE adrelid = 't'::regclass ORDER BY adnum"
        ).fetchall()
    ]
    assert stored == ["'x'::text", "(1 + 2)"]


def test_a_check_is_stored_analysed(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (s TEXT CHECK (s IN ('a', 'b')))")
    stored = _one(
        conn,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conrelid = 't'::regclass AND contype = 'c'",
    )
    assert "= ANY (ARRAY[" in str(stored)


def test_a_generation_expression_is_stored_analysed(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (d JSONB, s TEXT GENERATED ALWAYS AS (d ->> 'k') STORED)")
    stored = _one(
        conn, "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef WHERE adrelid = 't'::regclass"
    )
    assert stored == "(d ->> 'k'::text)"


def test_format_type_spells_a_type_its_own_way(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (v VARCHAR(50), i INT)")
    spelled = [
        row[0]
        for row in conn.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
            " WHERE attrelid = 't'::regclass AND attnum > 0 ORDER BY attnum"
        ).fetchall()
    ]
    assert spelled == ["character varying(50)", "integer"]


def test_serial_is_not_a_type(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (id SERIAL)")
    spelled, default = conn.execute(
        "SELECT format_type(a.atttypid, a.atttypmod), pg_get_expr(d.adbin, d.adrelid)"
        " FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
        " WHERE a.attrelid = 't'::regclass AND a.attname = 'id'"
    ).fetchone()
    owned = _one(
        conn,
        "SELECT count(*) FROM pg_depend WHERE classid = 'pg_class'::regclass"
        " AND refobjid = 't'::regclass AND deptype = 'a'",
    )
    assert (spelled, default.startswith("nextval("), owned) == ("integer", True, 1)


def test_an_unbounded_sequence_reads_back_bounded(conn: psycopg.Connection) -> None:
    conn.execute("CREATE SEQUENCE s")
    bounds = conn.execute(
        "SELECT seqmin, seqmax FROM pg_sequence WHERE seqrelid = 's'::regclass"
    ).fetchone()
    assert bounds == (1, 9223372036854775807)


def test_a_catalog_spells_a_schema_only_when_the_search_path_would_miss_it(
    conn: psycopg.Connection,
) -> None:
    conn.execute(
        "CREATE SCHEMA b; CREATE TABLE b.p (id INT PRIMARY KEY);"
        " CREATE TABLE q (id INT PRIMARY KEY);"
        " CREATE TABLE c (pid INT REFERENCES b.p, qid INT REFERENCES q);"
        " CREATE INDEX ix ON c (pid);"
    )
    defs = sorted(
        str(row[0])
        for row in conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = 'c'::regclass AND contype = 'f'"
        ).fetchall()
    )
    index = _one(conn, "SELECT pg_get_indexdef('ix'::regclass)")
    assert defs == ["FOREIGN KEY (pid) REFERENCES b.p(id)", "FOREIGN KEY (qid) REFERENCES q(id)"]
    assert str(index).startswith("CREATE INDEX ix ON public.c USING btree")


def test_an_index_method_is_btree_on_both_sides(conn: psycopg.Connection) -> None:
    """The disagreement the plan expected, measured absent."""
    ddl = "CREATE TABLE t (n INT); CREATE INDEX ix ON t (n);"
    conn.execute(ddl)
    live = _one(
        conn,
        "SELECT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam WHERE c.relname = 'ix'",
    )
    (table,) = build_model(ddl).tables.values()
    assert (table.indexes[0].method, live) == ("btree", "btree")


def test_an_index_expression_and_predicate_are_stored_analysed(conn: psycopg.Connection) -> None:
    conn.execute(
        "CREATE TABLE t (d JSONB, s TEXT); CREATE INDEX ix ON t ((d ->> 'k')) WHERE s <> 'x';"
    )
    stored = str(_one(conn, "SELECT pg_get_indexdef('ix'::regclass)"))
    assert "'k'::text" in stored
    assert "'x'::text" in stored


def test_a_routines_types_read_back_in_format_types_spelling(conn: psycopg.Connection) -> None:
    conn.execute("CREATE FUNCTION f(a int8) RETURNS int4 LANGUAGE sql AS $$ SELECT 1 $$")
    arguments, result = conn.execute(
        "SELECT pg_get_function_identity_arguments(oid), pg_get_function_result(oid)"
        " FROM pg_proc WHERE proname = 'f'"
    ).fetchone()
    assert (arguments, result) == ("a bigint", "integer")


def test_a_views_query_reads_back_deparsed(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE t (id INT); CREATE VIEW v AS SELECT * FROM t")
    deparsed = str(_one(conn, "SELECT pg_get_viewdef('v'::regclass, true)"))
    # `*` is expanded; PostgreSQL 15 also qualifies the column (`t.id`), 16 on does not.
    assert "*" not in deparsed
    assert "id" in deparsed
