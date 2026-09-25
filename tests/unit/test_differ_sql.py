"""Unit tests for DifferSQLGenerator."""

from __future__ import annotations

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


def test_a_dropped_table_is_written():
    """Whether a migration may drop a table is the destructive gate's decision.

    ``migration.destructive`` rules on the generated file, for every kind of drop.
    """
    sql = DifferSQLGenerator().generate_up(TableDropped(table("bookings")))
    assert sql == "DROP TABLE bookings;\n"


def test_add_column_writes_the_declared_column():
    change = ColumnAdded("users", spelled("bio", "text"))
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert sql == "ALTER TABLE users ADD COLUMN bio text;\n"


def test_a_dropped_column_is_written():
    """As for a table: the destructive gate decides."""
    change = ColumnDropped("users", spelled("bio", "text"))
    sql = DifferSQLGenerator().generate_up(change)
    assert sql == "ALTER TABLE users DROP COLUMN bio;\n"


def test_alter_column_type_writes_the_new_type():
    change = ColumnTypeChanged("users", spelled("age", "text"), spelled("age", "integer"))
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert sql == "ALTER TABLE users ALTER COLUMN age TYPE integer;\n"


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


def test_generate_down_returns_none_for_a_change_with_no_rollback():
    """A kind whose rollback is the author's work derives none, never an exception."""
    assert DifferSQLGenerator().generate_down(RETYPED) is None


def test_generate_up_returns_none_for_a_change_with_no_generator():
    gen = DifferSQLGenerator()
    assert gen.generate_up(RETYPED) is None
