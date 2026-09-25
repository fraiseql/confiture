"""DifferSQLGenerator: enum and sequence change types."""

from __future__ import annotations

import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    SequenceAdded,
    SequenceDropped,
)
from confiture.core.schema_model import EnumType, Sequence


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

    def test_the_type_is_created_with_its_labels(self) -> None:
        """An added enum type carries its labels, and the ``CREATE`` writes them.

        The labels never reached the renderer: it read them from a key the differ
        did not write, so every added enum type was generated as ``AS ENUM ()`` —
        a statement that applies cleanly and creates a type that holds nothing.
        """
        change = EnumTypeAdded(EnumType("mood", values=("happy", "it's ok")))
        sql = DifferSQLGenerator().generate_up(change)
        assert sql == "CREATE TYPE mood AS ENUM ('happy', 'it''s ok');\n"

    def test_the_differ_carries_the_labels_to_the_statement(self) -> None:
        diff = SchemaDiffer().compare("", "CREATE TYPE mood AS ENUM ('sad', 'ok');")
        (change,) = diff.changes
        assert DifferSQLGenerator().generate_up(change) == (
            "CREATE TYPE mood AS ENUM ('sad', 'ok');\n"
        )


class TestDropEnumType:
    def test_the_drop_is_written(self):
        """The destructive gate decides whether it ships, as for a table (#335)."""
        change = EnumTypeDropped(EnumType("mood"))
        assert DifferSQLGenerator().generate_up(change) == "DROP TYPE IF EXISTS mood;\n"

    def test_the_down_recreates_it_with_its_labels_in_order(self):
        """#335: the change carries the labels; the down wrote a warning instead."""
        change = EnumTypeDropped(EnumType("mood", schema="app", values=("sad", "it's ok")))
        assert DifferSQLGenerator().generate_down(change) == (
            "CREATE TYPE app.mood AS ENUM ('sad', 'it''s ok');\n"
        )


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

    def test_an_added_label_derives_no_rollback(self):
        """PostgreSQL cannot remove an enum label: the generator's directive says so."""
        change = EnumValuesChanged("mood", added=("ecstatic",), removed=())
        assert DifferSQLGenerator().generate_down(change) is None

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
    def test_the_drop_is_written(self):
        change = SequenceDropped(Sequence("order_seq"))
        assert DifferSQLGenerator().generate_up(change) == "DROP SEQUENCE IF EXISTS order_seq;\n"

    def test_the_down_recreates_it_with_its_options(self):
        change = SequenceDropped(Sequence("order_seq", start=100, increment=5))
        assert DifferSQLGenerator().generate_down(change) == (
            "CREATE SEQUENCE IF NOT EXISTS order_seq INCREMENT BY 5 START WITH 100;\n"
        )


class TestSequenceOptions:
    """#335: an added sequence lost its options; each one that is not the default is written."""

    @pytest.mark.parametrize(
        ("sequence", "options"),
        [
            (Sequence("s"), ""),
            # What the DDL reader and the live reader hold for a bare CREATE SEQUENCE.
            (Sequence("s", start=1, increment=1), ""),
            (Sequence("s", start=1, increment=1, min_value=1, max_value=2**63 - 1), ""),
            (Sequence("s", start=1000), " START WITH 1000"),
            (Sequence("s", start=10, min_value=10), " MINVALUE 10"),
            (Sequence("s", max_value=2**31 - 1), " MAXVALUE 2147483647"),
            (Sequence("s", increment=-1), " INCREMENT BY -1"),
            (
                Sequence("s", start=-1, increment=-1, min_value=-(2**63), max_value=-1),
                " INCREMENT BY -1",
            ),
            (Sequence("s", increment=-2, max_value=0, start=0), " INCREMENT BY -2 MAXVALUE 0"),
        ],
    )
    def test_only_what_differs_from_the_default_is_written(self, sequence, options):
        assert DifferSQLGenerator().generate_up(SequenceAdded(sequence)) == (
            f"CREATE SEQUENCE IF NOT EXISTS s{options};\n"
        )

    def test_the_differ_carries_them_from_the_ddl(self):
        (change,) = (
            SchemaDiffer()
            .compare("", "CREATE SEQUENCE s START 500 INCREMENT 10 MAXVALUE 100000;")
            .changes
        )
        assert DifferSQLGenerator().generate_up(change) == (
            "CREATE SEQUENCE IF NOT EXISTS s INCREMENT BY 10 MAXVALUE 100000 START WITH 500;\n"
        )
