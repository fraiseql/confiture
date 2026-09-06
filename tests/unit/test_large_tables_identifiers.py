"""``large_tables.py`` composes identifiers; only expressions and predicates are raw.

Table, column and index names used to be f-string interpolated into every
statement. ``expression``, ``where_clause``, ``default`` and ``column_type``
stay raw SQL by documented contract — they are code the migration author
writes — but a name is a name and goes through ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from psycopg import sql as pgsql

from confiture.core.large_tables import (
    BatchConfig,
    BatchedMigration,
    OnlineIndexBuilder,
    TableSizeEstimator,
)

TABLE = 'ord"ers'  # a name that must be quoted to survive


class _RecordingCursor:
    def __init__(self) -> None:
        self.queries: list[Any] = []
        self.rowcount = 0
        self._last = ""

    def execute(self, sql: Any, params: Any = None) -> _RecordingCursor:
        self.queries.append(sql)
        self._last = _text(sql).lower()
        self.rowcount = 0
        return self

    def fetchone(self) -> tuple[Any, ...]:
        if "pg_relation_size" in self._last:
            return (1,)
        if "count(" in self._last:
            return (0,)
        return (None,)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [("a",)]

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _text(sql: Any) -> str:
    return sql.as_string() if isinstance(sql, pgsql.Composable) else str(sql)


def _conn() -> tuple[MagicMock, _RecordingCursor]:
    cursor = _RecordingCursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _assert_name_is_quoted(queries: list[Any]) -> None:
    """Every statement naming the table names it as a quoted identifier."""
    assert queries
    for q in queries:
        text = _text(q)
        if "ord" not in text:
            continue
        assert isinstance(q, pgsql.Composable), f"raw SQL string names the table: {text!r}"
        assert '"ord""ers"' in text, text
        assert f" {TABLE} " not in text and f" {TABLE}\n" not in text


def test_backfill_column_quotes_names() -> None:
    conn, cur = _conn()
    BatchedMigration(conn, BatchConfig(sleep_between_batches=0)).backfill_column(
        TABLE, 'tot"al', "subtotal + tax"
    )
    _assert_name_is_quoted(cur.queries)


def test_add_column_with_default_quotes_names() -> None:
    conn, cur = _conn()
    BatchedMigration(conn, BatchConfig(sleep_between_batches=0)).add_column_with_default(
        TABLE, "total", "NUMERIC(10, 2)", "0"
    )
    _assert_name_is_quoted(cur.queries)
    ddl = _text(cur.queries[0])
    assert 'ADD COLUMN IF NOT EXISTS "total" NUMERIC(10, 2)' in ddl


def test_delete_in_batches_quotes_names() -> None:
    conn, cur = _conn()
    BatchedMigration(conn, BatchConfig(sleep_between_batches=0)).delete_in_batches(
        TABLE, "created_at < now() - interval '1 year'"
    )
    _assert_name_is_quoted(cur.queries)
    assert "created_at < now() - interval '1 year'" in _text(cur.queries[0])


def test_copy_to_new_table_quotes_names() -> None:
    conn, cur = _conn()
    cur.fetchone = lambda: (0,)  # type: ignore[method-assign]
    BatchedMigration(conn, BatchConfig(sleep_between_batches=0)).copy_to_new_table(
        TABLE, "orders_v2", columns=["a", "b"]
    )
    _assert_name_is_quoted(cur.queries)


def test_exact_row_count_quotes_names() -> None:
    conn, cur = _conn()
    TableSizeEstimator(conn).get_exact_row_count(TABLE, "TRUE")
    _assert_name_is_quoted(cur.queries)


@pytest.mark.parametrize(
    "call",
    [
        lambda b: b.create_index_concurrently(TABLE, ["a"], index_name="idx_a", method="gin"),
        lambda b: b.drop_index_concurrently('ord"ers'),
        lambda b: b.reindex_concurrently('ord"ers'),
    ],
    ids=["create", "drop", "reindex"],
)
def test_index_builder_quotes_names(call: Any) -> None:
    conn, cur = _conn()
    call(OnlineIndexBuilder(conn))
    assert len(cur.queries) == 1
    q = cur.queries[0]
    assert isinstance(q, pgsql.Composable), f"raw SQL string: {q!r}"
    text = _text(q)
    assert '"ord""ers"' in text  # the table, or the index named after it


def test_index_options_stay_readable() -> None:
    conn, cur = _conn()
    OnlineIndexBuilder(conn).create_index_concurrently(
        "orders", ["a", "b"], unique=True, where="active = true", method="gin", include=["c"]
    )
    text = _text(cur.queries[0])
    assert (
        'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "idx_orders_a_b" ON "orders" USING "gin" ("a", "b") INCLUDE ("c") WHERE active = true'
        in " ".join(text.split())
    )
