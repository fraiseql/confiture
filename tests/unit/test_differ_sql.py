"""Unit tests for DifferSQLGenerator."""

from __future__ import annotations

import pytest

from confiture.core.introspection.differ_sql import DifferSQLGenerator
from confiture.exceptions import UnsafeOperationError
from confiture.models.schema import SchemaChange


def test_add_table_generates_create_if_not_exists():
    change = SchemaChange(
        type="ADD_TABLE",
        table="bookings",
        details={
            "columns": [
                {"name": "id", "type": "uuid", "nullable": False, "default": "gen_random_uuid()"},
                {
                    "name": "created_at",
                    "type": "timestamptz",
                    "nullable": False,
                    "default": "now()",
                },
            ]
        },
    )
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "bookings" in sql
    assert "id uuid NOT NULL DEFAULT gen_random_uuid()" in sql


def test_schema_change_details_accepts_nested_column_list():
    change = SchemaChange(
        type="ADD_TABLE",
        table="orders",
        details={"columns": [{"name": "id", "type": "uuid", "nullable": False}]},
    )
    assert isinstance(change.details["columns"], list)


def test_drop_table_requires_force():
    change = SchemaChange(type="DROP_TABLE", table="bookings")
    gen = DifferSQLGenerator()
    with pytest.raises(UnsafeOperationError, match="--force"):
        gen.generate_up(change)


def test_drop_table_with_force():
    change = SchemaChange(type="DROP_TABLE", table="bookings")
    gen = DifferSQLGenerator(force_destructive=True)
    sql = gen.generate_up(change)
    assert "DROP TABLE IF EXISTS bookings CASCADE" in sql


def test_add_column_if_not_exists():
    change = SchemaChange(
        type="ADD_COLUMN",
        table="users",
        column="bio",
        details={"type": "text", "nullable": True},
    )
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio text" in sql


def test_drop_column_requires_force():
    change = SchemaChange(type="DROP_COLUMN", table="users", column="bio")
    gen = DifferSQLGenerator()
    with pytest.raises(UnsafeOperationError):
        gen.generate_up(change)


def test_drop_column_with_force():
    change = SchemaChange(type="DROP_COLUMN", table="users", column="bio")
    gen = DifferSQLGenerator(force_destructive=True)
    sql = gen.generate_up(change)
    assert "DROP COLUMN IF EXISTS bio" in sql


def test_alter_column_type_warns_on_lossy_cast():
    change = SchemaChange(
        type="ALTER_COLUMN_TYPE",
        table="users",
        column="age",
        old_value="text",
        new_value="integer",
    )
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "ALTER COLUMN age TYPE integer" in sql
    assert "USING" in sql
    assert "FIXME" in sql


def test_add_index_concurrently():
    change = SchemaChange(
        type="ADD_INDEX",
        table="bookings",
        details={"name": "idx_bookings_user_id", "columns": ["user_id"], "unique": False},
    )
    gen = DifferSQLGenerator()
    sql = gen.generate_up(change)
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_user_id" in sql
    assert "ON bookings (user_id)" in sql
    assert "BEGIN" not in sql


def test_add_fk_constraint_uses_not_valid():
    change = SchemaChange(
        type="ADD_CONSTRAINT",
        table="bookings",
        details={
            "name": "fk_user",
            "type": "FOREIGN KEY",
            "columns": ["user_id"],
            "references": "users(id)",
        },
    )
    sql = DifferSQLGenerator().generate_up(change)
    assert "NOT VALID" in sql
    assert "VALIDATE CONSTRAINT" in sql


def test_generate_down_returns_warning_for_unknown():
    change = SchemaChange(type="ADD_FUNCTION", table="myfunc")
    gen = DifferSQLGenerator()
    sql = gen.generate_down(change)
    assert "WARNING" in sql or "No automatic rollback" in sql


def test_generate_up_raises_not_implemented_for_unknown():
    change = SchemaChange(type="UNKNOWN_CHANGE", table="foo")
    gen = DifferSQLGenerator()
    with pytest.raises(NotImplementedError):
        gen.generate_up(change)
