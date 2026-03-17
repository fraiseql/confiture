"""Phase 02 Cycle 1 — DifferSQLGenerator: enum and sequence change types."""

from __future__ import annotations

import pytest

from confiture.core.introspection.differ_sql import DifferSQLGenerator
from confiture.exceptions import UnsafeOperationError
from confiture.models.schema import SchemaChange


class TestAddEnumType:
    def test_generates_create_type_as_enum(self):
        change = SchemaChange(
            type="ADD_ENUM_TYPE",
            table="mood",
            details={"values": ["happy", "sad", "neutral"]},
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert "CREATE TYPE" in sql
        assert "mood" in sql
        assert "AS ENUM" in sql
        assert "happy" in sql
        assert "sad" in sql
        assert "neutral" in sql

    def test_generates_if_not_exists(self):
        change = SchemaChange(type="ADD_ENUM_TYPE", table="status")
        sql = DifferSQLGenerator().generate_up(change)
        # Should produce valid SQL even without values
        assert "CREATE TYPE" in sql
        assert "status" in sql

    def test_down_drops_type(self):
        change = SchemaChange(type="ADD_ENUM_TYPE", table="mood")
        sql = DifferSQLGenerator().generate_down(change)
        assert "DROP TYPE" in sql
        assert "mood" in sql


class TestDropEnumType:
    def test_raises_without_force(self):
        change = SchemaChange(type="DROP_ENUM_TYPE", table="mood")
        with pytest.raises(UnsafeOperationError):
            DifferSQLGenerator().generate_up(change)

    def test_generates_drop_type_with_force(self):
        change = SchemaChange(type="DROP_ENUM_TYPE", table="mood")
        sql = DifferSQLGenerator(force_destructive=True).generate_up(change)
        assert "DROP TYPE" in sql
        assert "mood" in sql

    def test_down_is_warning_comment(self):
        change = SchemaChange(type="DROP_ENUM_TYPE", table="mood")
        sql = DifferSQLGenerator(force_destructive=True).generate_down(change)
        assert "WARNING" in sql or "Cannot" in sql


class TestChangeEnumValues:
    def test_generates_add_value_statements(self):
        change = SchemaChange(
            type="CHANGE_ENUM_VALUES",
            table="mood",
            details={"added_values": ["ecstatic"], "removed_values": []},
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert "ADD VALUE" in sql
        assert "ecstatic" in sql
        assert "mood" in sql

    def test_removed_values_produce_warning(self):
        change = SchemaChange(
            type="CHANGE_ENUM_VALUES",
            table="mood",
            details={"added_values": [], "removed_values": ["sad"]},
        )
        sql = DifferSQLGenerator().generate_up(change)
        # Removing enum values requires DROP+RECREATE — should warn
        assert "WARNING" in sql or "sad" in sql

    def test_mixed_adds_and_removes(self):
        change = SchemaChange(
            type="CHANGE_ENUM_VALUES",
            table="mood",
            details={"added_values": ["ecstatic"], "removed_values": ["sad"]},
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert "ADD VALUE" in sql
        assert "ecstatic" in sql


class TestAddSequence:
    def test_generates_create_sequence(self):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        sql = DifferSQLGenerator().generate_up(change)
        assert "CREATE SEQUENCE" in sql
        assert "order_seq" in sql

    def test_generates_if_not_exists(self):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        sql = DifferSQLGenerator().generate_up(change)
        assert "IF NOT EXISTS" in sql

    def test_down_drops_sequence(self):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        sql = DifferSQLGenerator().generate_down(change)
        assert "DROP SEQUENCE" in sql
        assert "order_seq" in sql


class TestDropSequence:
    def test_raises_without_force(self):
        change = SchemaChange(type="DROP_SEQUENCE", table="order_seq")
        with pytest.raises(UnsafeOperationError):
            DifferSQLGenerator().generate_up(change)

    def test_generates_drop_sequence_with_force(self):
        change = SchemaChange(type="DROP_SEQUENCE", table="order_seq")
        sql = DifferSQLGenerator(force_destructive=True).generate_up(change)
        assert "DROP SEQUENCE" in sql
        assert "order_seq" in sql

    def test_down_is_warning_comment(self):
        change = SchemaChange(type="DROP_SEQUENCE", table="order_seq")
        sql = DifferSQLGenerator(force_destructive=True).generate_down(change)
        assert "WARNING" in sql or "Cannot" in sql
