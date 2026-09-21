"""Unit tests for DifferSQLGenerator."""

from __future__ import annotations

import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    ColumnAdded,
    ColumnDropped,
    ColumnTypeChanged,
    ForeignKeyAdded,
    IndexAdded,
    TableAdded,
    TableDropped,
)
from confiture.core.schema_model import Constraint
from confiture.exceptions import UnsafeOperationError
from tests.unit._schema_changes import replaced, spelled
from tests.unit._schema_models import index, table

#: A kind whose one right statement PostgreSQL does not have, so it has no generator.
RETYPED = replaced("type", "foo", "CREATE TYPE foo AS (x INT)", "CREATE TYPE foo AS (x INT, y INT)")


def test_add_table_generates_create_if_not_exists():
    change = TableAdded(
        table(
            "bookings",
            spelled("id", "uuid", nullable=False, default="gen_random_uuid()"),
            spelled("created_at", "timestamptz", nullable=False, default="now()"),
        )
    )
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "bookings" in sql
    assert "id uuid NOT NULL DEFAULT gen_random_uuid()" in sql


def test_schema_change_details_accepts_nested_column_list():
    change = TableAdded(table("orders", spelled("id", "uuid", nullable=False)))
    assert isinstance((change.to_wire().details or {})["columns"], list)


def test_drop_table_requires_force():
    change = TableDropped(table("bookings"))
    gen = DifferSQLGenerator()
    with pytest.raises(UnsafeOperationError, match="--force"):
        gen.generate_up(change)


def test_drop_table_with_force():
    change = TableDropped(table("bookings"))
    gen = DifferSQLGenerator(force_destructive=True)
    sql = gen.generate_up(change)
    assert "DROP TABLE IF EXISTS bookings CASCADE" in sql


def test_add_column_if_not_exists():
    change = ColumnAdded("users", spelled("bio", "text"))
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio text" in sql


def test_drop_column_requires_force():
    change = ColumnDropped("users", spelled("bio", "text"))
    gen = DifferSQLGenerator()
    with pytest.raises(UnsafeOperationError):
        gen.generate_up(change)


def test_drop_column_with_force():
    change = ColumnDropped("users", spelled("bio", "text"))
    gen = DifferSQLGenerator(force_destructive=True)
    sql = gen.generate_up(change)
    assert "DROP COLUMN IF EXISTS bio" in sql


def test_alter_column_type_warns_on_lossy_cast():
    change = ColumnTypeChanged("users", spelled("age", "text"), spelled("age", "integer"))
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "ALTER COLUMN age TYPE integer" in sql
    assert "USING" in sql
    # The generated SQL carries a manual-review marker for the cast.
    assert "review:" in sql


def test_add_index_concurrently():
    change = IndexAdded("bookings", index("idx_bookings_user_id", "bookings", "user_id"))
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_user_id" in sql
    assert "ON bookings (user_id)" in sql
    assert "BEGIN" not in sql


def test_add_fk_constraint_uses_not_valid():
    change = ForeignKeyAdded(
        "bookings",
        Constraint(
            kind="foreign_key",
            name="fk_user",
            columns=("user_id",),
            ref_table="users",
            ref_columns=("id",),
        ),
    )
    sql = DifferSQLGenerator().generate_up(change)
    assert "NOT VALID" in sql
    assert "VALIDATE CONSTRAINT" in sql


def test_generate_down_returns_warning_for_a_change_with_no_rollback():
    """A kind whose rollback is the author's work is a warning, never an exception."""
    sql = DifferSQLGenerator().generate_down(RETYPED)
    assert "WARNING" in sql or "No automatic rollback" in sql


def test_generate_up_raises_not_implemented_for_a_change_with_no_generator():
    gen = DifferSQLGenerator()
    with pytest.raises(NotImplementedError):
        gen.generate_up(RETYPED)
