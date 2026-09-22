"""The risk tier of a schema change: the change set's own table, read for a difference.

A :data:`~confiture.core.schema_change.SchemaChange` declares its tier from the one
:class:`~confiture.core.risk_tier.RiskTier` taxonomy the change set uses — the
change-set kind it is (``_TIER_BY_KIND``), and the same rules for the kinds whose
tier depends on the statement (``tier_for_add_column``, ``tier_for_add_constraint``,
``tier_for_create_index``, ``tier_for_type_change``). Nothing here touches
``ChangeEntry`` or its ``CONTRACT_VERSION``: fraisier-core reads the change set, and
the change set is what it was.

A difference knows more than a statement, and where that changes the answer the tier
says what the difference is. An added view is written ``CREATE OR REPLACE`` so the
migration re-applies, and a statement reads that as a replacement; a column type
change's source type is in the diff and never in the SQL. Everywhere else the tier is
the one the change set gives the SQL confiture writes for the change —
``tests/unit/test_schema_change_tiers.py`` holds both halves of that.

``None`` is *unclassified*, as it is in the change set: a kind the table does not
tier (``CREATE AGGREGATE``), or an enum losing labels, which no statement can do.
"""

from __future__ import annotations

from typing import assert_never

from confiture.core.change_set.models import (
    _TIER_BY_KIND,
    tier_for_add_column,
    tier_for_add_constraint,
    tier_for_create_index,
    tier_for_type_change,
)
from confiture.core.differ_sql import REPLACED_BY_DROP_AND_CREATE
from confiture.core.lock_profile import profile_for_kind
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.schema_change import (
    KINDS,
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnChange,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    DefinitionChange,
    EnumOrSequenceChange,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    SchemaChange,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableChange,
    TableDropped,
    TableObjectChange,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Column
from confiture.core.type_lattice import TypeChange, changes_rewrite_table, compare_types

__all__ = ["tier_of"]

#: Where an object kind's change-set noun is not its own name.
_NOUN: dict[str, str] = {"matview": "materialized_view"}


def _noun(kind: str) -> str:
    return _NOUN.get(kind, kind)


def _table_tier(change: TableChange) -> RiskTier | None:
    match change:
        case TableAdded():
            return _TIER_BY_KIND["create_table"]
        case TableDropped():
            return _TIER_BY_KIND["drop_table"]
        case TableRenamed():
            return _TIER_BY_KIND["rename_object"]
        case _:
            assert_never(change)


def _type_change_tier(old: Column, new: Column) -> RiskTier | None:
    """The change set's own rule, with the source type a statement never states."""
    direction = compare_types(old.type_key, new.type_key)
    if direction in (TypeChange.UNKNOWN, TypeChange.IDENTICAL):
        return None
    rewrites = changes_rewrite_table(old.type_key, new.type_key)
    lock = profile_for_kind("alter_column_type", rewrites=rewrites)
    return tier_for_type_change(direction, rewrites_table=lock.rewrites_table)


def _column_tier(change: ColumnChange) -> RiskTier | None:
    match change:
        case ColumnAdded(_, column):
            return tier_for_add_column(
                nullable=not column.not_null, has_default=column.default is not None
            )
        case ColumnDropped():
            return _TIER_BY_KIND["drop_column"]
        case ColumnRenamed():
            return _TIER_BY_KIND["rename_column"]
        case ColumnTypeChanged(_, old, new):
            return _type_change_tier(old, new)
        case ColumnNullabilityChanged(nullable=nullable):
            return _TIER_BY_KIND["drop_not_null" if nullable else "set_not_null"]
        case ColumnDefaultChanged(new=new):
            return _TIER_BY_KIND["set_column_default" if new else "drop_column_default"]
        case _:
            assert_never(change)


def _table_object_tier(change: TableObjectChange) -> RiskTier | None:
    match change:
        case IndexAdded():
            # The renderer builds it CONCURRENTLY.
            return tier_for_create_index(concurrently=True)
        case ForeignKeyAdded(_, constraint):
            # Added NOT VALID and validated separately — when it has a name to validate by.
            return tier_for_add_constraint(not_valid=bool(constraint.name))
        case CheckConstraintAdded() | UniqueConstraintAdded():
            return tier_for_add_constraint(not_valid=False)
        case IndexDropped():
            return _TIER_BY_KIND["drop_index"]
        case ForeignKeyDropped() | CheckConstraintDropped() | UniqueConstraintDropped():
            return _TIER_BY_KIND["drop_constraint"]
        case _:
            assert_never(change)


def _enum_or_sequence_tier(change: EnumOrSequenceChange) -> RiskTier | None:
    match change:
        case EnumTypeAdded():
            return _TIER_BY_KIND["create_type"]
        case EnumTypeDropped():
            return _TIER_BY_KIND["drop_type"]
        case EnumValuesChanged(removed=removed):
            # `ALTER TYPE … ADD VALUE` is additive; no statement removes a label.
            return None if removed else _TIER_BY_KIND["alter_type"]
        case SequenceAdded():
            return _TIER_BY_KIND["create_sequence"]
        case SequenceDropped():
            return _TIER_BY_KIND["drop_sequence"]
        case _:
            assert_never(change)


def _definition_tier(change: DefinitionChange) -> RiskTier | None:
    noun = _noun(change.ref.kind)
    match change:
        case ObjectAdded():
            return _TIER_BY_KIND.get(f"create_{noun}")
        case ObjectDropped():
            return _TIER_BY_KIND.get(f"drop_{noun}")
        case ObjectReplaced() if change.ref.kind in REPLACED_BY_DROP_AND_CREATE:
            return worst_tier(
                (_TIER_BY_KIND.get(f"drop_{noun}"), _TIER_BY_KIND.get(f"create_{noun}"))
            )
        case ObjectReplaced():
            return _TIER_BY_KIND.get(f"replace_{noun}")
        case _:
            assert_never(change)


def tier_of(change: SchemaChange) -> RiskTier | None:
    """The tier *change* carries, or ``None`` where the change set would classify nothing.

    Raises:
        TypeError: for anything that is not one of the ``SchemaChange`` variants.
    """
    if not isinstance(change, tuple(KINDS)):
        raise TypeError(f"tier_of takes a SchemaChange, not {type(change).__name__}")
    match change:
        case TableAdded() | TableDropped() | TableRenamed():
            return _table_tier(change)
        case (
            ColumnAdded()
            | ColumnDropped()
            | ColumnRenamed()
            | ColumnTypeChanged()
            | ColumnNullabilityChanged()
            | ColumnDefaultChanged()
        ):
            return _column_tier(change)
        case (
            IndexAdded()
            | IndexDropped()
            | ForeignKeyAdded()
            | ForeignKeyDropped()
            | CheckConstraintAdded()
            | CheckConstraintDropped()
            | UniqueConstraintAdded()
            | UniqueConstraintDropped()
        ):
            return _table_object_tier(change)
        case (
            EnumTypeAdded()
            | EnumTypeDropped()
            | EnumValuesChanged()
            | SequenceAdded()
            | SequenceDropped()
        ):
            return _enum_or_sequence_tier(change)
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return _definition_tier(change)
        case _:
            assert_never(change)
