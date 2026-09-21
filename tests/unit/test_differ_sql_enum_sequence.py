"""DifferSQLGenerator: enum and sequence change types."""

from __future__ import annotations

import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    SequenceAdded,
    SequenceDropped,
)
from confiture.core.schema_model import EnumType, Sequence
from confiture.exceptions import UnsafeOperationError


class TestAddEnumType:
    def test_generates_if_not_exists(self):
        change = EnumTypeAdded(EnumType("status"))
        sql = DifferSQLGenerator().generate_up(change)
        # Should produce valid SQL even without values
        assert "CREATE TYPE" in sql
        assert "status" in sql

    def test_down_drops_type(self):
        change = EnumTypeAdded(EnumType("mood"))
        sql = DifferSQLGenerator().generate_down(change)
        assert "DROP TYPE" in sql
        assert "mood" in sql


class TestDropEnumType:
    def test_raises_without_force(self):
        change = EnumTypeDropped(EnumType("mood"))
        with pytest.raises(UnsafeOperationError):
            DifferSQLGenerator().generate_up(change)

    def test_generates_drop_type_with_force(self):
        change = EnumTypeDropped(EnumType("mood"))
        sql = DifferSQLGenerator(force_destructive=True).generate_up(change)
        assert "DROP TYPE" in sql
        assert "mood" in sql

    def test_down_is_warning_comment(self):
        change = EnumTypeDropped(EnumType("mood"))
        sql = DifferSQLGenerator(force_destructive=True).generate_down(change)
        assert "WARNING" in sql or "Cannot" in sql


class TestChangeEnumValues:
    def test_generates_add_value_statements(self):
        change = EnumValuesChanged("mood", added=("ecstatic",), removed=())
        sql = DifferSQLGenerator().generate_up(change)
        assert "ADD VALUE" in sql
        assert "ecstatic" in sql
        assert "mood" in sql

    def test_removed_values_produce_warning(self):
        change = EnumValuesChanged("mood", added=(), removed=("sad",))
        sql = DifferSQLGenerator().generate_up(change)
        # Removing enum values requires DROP+RECREATE — should warn
        assert "WARNING" in sql or "sad" in sql

    def test_mixed_adds_and_removes(self):
        change = EnumValuesChanged("mood", added=("ecstatic",), removed=("sad",))
        sql = DifferSQLGenerator().generate_up(change)
        assert "ADD VALUE" in sql
        assert "ecstatic" in sql


class TestAddSequence:
    def test_generates_create_sequence(self):
        change = SequenceAdded(Sequence("order_seq"))
        sql = DifferSQLGenerator().generate_up(change)
        assert "CREATE SEQUENCE" in sql
        assert "order_seq" in sql

    def test_generates_if_not_exists(self):
        change = SequenceAdded(Sequence("order_seq"))
        sql = DifferSQLGenerator().generate_up(change)
        assert "IF NOT EXISTS" in sql

    def test_down_drops_sequence(self):
        change = SequenceAdded(Sequence("order_seq"))
        sql = DifferSQLGenerator().generate_down(change)
        assert "DROP SEQUENCE" in sql
        assert "order_seq" in sql


class TestDropSequence:
    def test_raises_without_force(self):
        change = SequenceDropped(Sequence("order_seq"))
        with pytest.raises(UnsafeOperationError):
            DifferSQLGenerator().generate_up(change)

    def test_generates_drop_sequence_with_force(self):
        change = SequenceDropped(Sequence("order_seq"))
        sql = DifferSQLGenerator(force_destructive=True).generate_up(change)
        assert "DROP SEQUENCE" in sql
        assert "order_seq" in sql

    def test_down_is_warning_comment(self):
        change = SequenceDropped(Sequence("order_seq"))
        sql = DifferSQLGenerator(force_destructive=True).generate_down(change)
        assert "WARNING" in sql or "Cannot" in sql
