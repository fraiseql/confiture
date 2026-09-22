"""ViewManager names a view by what the catalogue holds, whatever characters that is.

The schema and view names come from ``pg_class``; every statement composes them as
identifiers, so a view whose name holds a quote, a hyphen or a whole statement is
dropped and recreated as itself, and nothing else runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

from confiture.core.view_manager import ViewManager

pytestmark = pytest.mark.integration

#: A view name that closes the identifier an unquoted rendering opens.
_INJECTED = 'v" CASCADE; DROP TABLE keepme; --'
#: An ordinary name that is not a bare identifier.
_HYPHENATED = "order-summary"
#: A materialized view, so the refresh, the index and the comment are composed too.
_MATERIALIZED = 'Totals "m"; --'


@pytest.fixture
def conn(fresh_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_database) as connection:
        connection.execute("CREATE TABLE t (a int)")
        connection.execute("CREATE TABLE keepme (x int)")
        connection.commit()
        yield connection


def _views(conn: psycopg.Connection, *names: str) -> None:
    for name in names:
        conn.execute(sql.SQL("CREATE VIEW {} AS SELECT a FROM t").format(sql.Identifier(name)))
    conn.commit()


def _relations(conn: psycopg.Connection, kinds: str) -> set[str]:
    rows = conn.execute(
        "SELECT relname FROM pg_class"
        " WHERE relnamespace = 'public'::regnamespace AND relkind::text = ANY(%s)",
        (list(kinds),),
    )
    return {row[0] for row in rows}


def _alter_and_recreate(conn: psycopg.Connection, vm: ViewManager) -> list[object]:
    conn.execute("ALTER TABLE t ALTER COLUMN a TYPE bigint")
    conn.commit()
    return [view.name for view, _error in vm.recreate_saved_views().failed]


def test_dropping_a_view_named_like_a_statement_drops_only_that_view(
    conn: psycopg.Connection,
) -> None:
    _views(conn, _INJECTED)

    ViewManager(conn).save_and_drop_dependent_views(["public"])

    assert _relations(conn, "rv") == {"t", "keepme"}


def test_a_view_whose_name_is_not_a_bare_identifier_is_recreated(
    conn: psycopg.Connection,
) -> None:
    _views(conn, _HYPHENATED, "plain")
    vm = ViewManager(conn)
    vm.save_and_drop_dependent_views(["public"])

    failed = _alter_and_recreate(conn, vm)

    assert (failed, _relations(conn, "v")) == ([], {_HYPHENATED, "plain"})


def test_a_materialized_view_is_recreated_with_its_index_and_comment(
    conn: psycopg.Connection,
) -> None:
    materialized = sql.Identifier(_MATERIALIZED)
    conn.execute(sql.SQL("CREATE MATERIALIZED VIEW {} AS SELECT a FROM t").format(materialized))
    conn.execute(sql.SQL("CREATE INDEX totals_a ON {} (a)").format(materialized))
    comment = "it's a \\ total"
    conn.execute(
        sql.SQL("COMMENT ON MATERIALIZED VIEW {} IS {}").format(materialized, sql.Literal(comment))
    )
    conn.commit()
    vm = ViewManager(conn)
    vm.save_and_drop_dependent_views(["public"])

    failed = _alter_and_recreate(conn, vm)

    described = conn.execute(
        "SELECT obj_description(%s::regclass)", (materialized.as_string(conn),)
    ).fetchone()
    assert (failed, _relations(conn, "mi"), described) == (
        [],
        {_MATERIALIZED, "totals_a"},
        (comment,),
    )
