"""Tests for the ``Captures`` normalization layer (Phase 04, issue #123).

The regex backend produces ``re.Match`` objects with numbered groups
that vary by pattern; the AST backend produces typed pglast nodes.
Templates can't accept either directly — they take a single normalized
:class:`Captures` instance. This test module proves the two dispatchers
produce equivalent captures for equivalent SQL.
"""

from __future__ import annotations

import re

import pytest

from confiture.core.idempotency._captures import (
    Captures,
    captures_from_ast,
    captures_from_regex,
)
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import PATTERNS

pglast = pytest.importorskip("pglast")


def _regex_match(pattern: IdempotencyPattern, sql: str) -> re.Match[str]:
    for pdef in PATTERNS:
        if pdef.pattern is pattern:
            m = pdef.regex.search(sql)
            assert m is not None, f"regex for {pattern.name} did not match {sql!r}"
            return m
    raise AssertionError(f"no PATTERN entry for {pattern.name}")


def _first_ast_stmt(sql: str):
    tree = pglast.parse_sql(sql)
    return tree[0].stmt


class TestCapturesEquivalence:
    """For each fillable pattern, regex and AST yield equal Captures."""

    def test_create_table(self) -> None:
        sql = "CREATE TABLE tenant.orders (id INT);"
        r_cap = captures_from_regex(
            IdempotencyPattern.CREATE_TABLE, _regex_match(IdempotencyPattern.CREATE_TABLE, sql)
        )
        a_cap = captures_from_ast(IdempotencyPattern.CREATE_TABLE, _first_ast_stmt(sql))
        assert r_cap == a_cap
        assert r_cap.schema == "tenant"
        assert r_cap.table == "orders"

    def test_create_table_unqualified(self) -> None:
        sql = "CREATE TABLE orders (id INT);"
        r_cap = captures_from_regex(
            IdempotencyPattern.CREATE_TABLE, _regex_match(IdempotencyPattern.CREATE_TABLE, sql)
        )
        a_cap = captures_from_ast(IdempotencyPattern.CREATE_TABLE, _first_ast_stmt(sql))
        assert r_cap == a_cap
        assert r_cap.schema is None
        assert r_cap.table == "orders"

    def test_create_index(self) -> None:
        sql = "CREATE INDEX idx_orders_user_id ON tenant.orders (user_id);"
        r_cap = captures_from_regex(
            IdempotencyPattern.CREATE_INDEX, _regex_match(IdempotencyPattern.CREATE_INDEX, sql)
        )
        a_cap = captures_from_ast(IdempotencyPattern.CREATE_INDEX, _first_ast_stmt(sql))
        assert r_cap.index_name == "idx_orders_user_id"
        assert a_cap.index_name == "idx_orders_user_id"
        # Both backends agree on index name and table (AST gives table, regex may not).
        # Equality only on identifiers we promise both backends can extract.
        assert r_cap.index_name == a_cap.index_name

    def test_alter_table_add_column(self) -> None:
        sql = "ALTER TABLE tenant.orders ADD COLUMN amount NUMERIC;"
        r_cap = captures_from_regex(
            IdempotencyPattern.ALTER_TABLE_ADD_COLUMN,
            _regex_match(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN, sql),
        )
        a_cap = captures_from_ast(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN, _first_ast_stmt(sql))
        assert r_cap.schema == "tenant"
        assert r_cap.table == "orders"
        assert r_cap.column == "amount"
        assert a_cap.schema == "tenant"
        assert a_cap.table == "orders"
        assert a_cap.column == "amount"

    def test_alter_table_add_constraint_check(self) -> None:
        sql = (
            "ALTER TABLE tenant.orders "
            "ADD CONSTRAINT chk_orders_amount_positive CHECK (amount > 0);"
        )
        r_cap = captures_from_regex(
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
            _regex_match(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK, sql),
        )
        a_cap = captures_from_ast(
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK, _first_ast_stmt(sql)
        )
        assert r_cap.schema == "tenant"
        assert r_cap.table == "orders"
        assert r_cap.constraint == "chk_orders_amount_positive"
        assert a_cap.schema == "tenant"
        assert a_cap.table == "orders"
        assert a_cap.constraint == "chk_orders_amount_positive"

    def test_alter_table_rename_column(self) -> None:
        sql = "ALTER TABLE tenant.orders RENAME COLUMN amt TO amount;"
        r_cap = captures_from_regex(
            IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN,
            _regex_match(IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN, sql),
        )
        a_cap = captures_from_ast(
            IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN, _first_ast_stmt(sql)
        )
        assert r_cap.schema == "tenant"
        assert r_cap.table == "orders"
        assert r_cap.column == "amt"
        assert r_cap.new_column == "amount"
        assert a_cap.schema == "tenant"
        assert a_cap.table == "orders"
        assert a_cap.column == "amt"
        assert a_cap.new_column == "amount"

    def test_create_type_as_enum(self) -> None:
        sql = "CREATE TYPE tenant.order_status AS ENUM ('open', 'closed');"
        r_cap = captures_from_regex(
            IdempotencyPattern.CREATE_TYPE, _regex_match(IdempotencyPattern.CREATE_TYPE, sql)
        )
        a_cap = captures_from_ast(IdempotencyPattern.CREATE_TYPE, _first_ast_stmt(sql))
        assert r_cap.type_name == "order_status"
        assert a_cap.type_name == "order_status"
        # AST exposes the schema; regex pattern only captures the bare type name.
        assert a_cap.schema == "tenant"

    def test_drop_table(self) -> None:
        sql = "DROP TABLE tenant.orders;"
        r_cap = captures_from_regex(
            IdempotencyPattern.DROP_TABLE, _regex_match(IdempotencyPattern.DROP_TABLE, sql)
        )
        a_cap = captures_from_ast(IdempotencyPattern.DROP_TABLE, _first_ast_stmt(sql))
        assert r_cap.schema == "tenant"
        assert r_cap.table == "orders"
        assert a_cap.schema == "tenant"
        assert a_cap.table == "orders"


class TestCapturesDataclass:
    """Captures defaults to all-None and is hashable/frozen."""

    def test_default_all_none(self) -> None:
        cap = Captures()
        assert cap.schema is None
        assert cap.table is None
        assert cap.column is None
        assert cap.new_column is None
        assert cap.constraint is None
        assert cap.type_name is None
        assert cap.index_name is None
        assert cap.view is None
        assert cap.sequence is None
        assert cap.extension is None

    def test_frozen(self) -> None:
        cap = Captures(table="orders")
        with pytest.raises((AttributeError, TypeError)):
            cap.table = "users"  # type: ignore[misc]
