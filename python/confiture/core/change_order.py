"""The order a generated migration applies its changes in: one PostgreSQL accepts.

The differ reports a diff grouped by what it compares — tables, then enum types
and sequences, then the objects compared by definition, each group by name. That
order is stable and readable; applied as written, it creates a table before the
schema it lives in, the extension its default calls, the enum type a column has
and the tables its foreign keys reference, and drops a table before the view that
reads it.

:func:`apply_order` ranks each change by what it needs to exist first — a stable
sort, so changes of one rank keep the differ's order — and orders the tables it
adds by their foreign keys. The down file undoes the up in reverse, so one order
serves both.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from confiture.core.introspection.dependency_graph import DependencyCycleError, dependency_order
from confiture.core.model_facts import resolve
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
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
    TableDropped,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import SchemaModel, Table, ref_for

#: Where a definition kind is created, by what it needs to exist first: a routine
#: may name a table's row type, a view a routine, a trigger its function. A kind
#: not named here is created last.
_CREATED: dict[str, int] = {
    "schema": 0,
    "extension": 1,
    "domain": 2,
    "type": 2,
    "function": 5,
    "procedure": 5,
    "aggregate": 5,
    "view": 6,
    "matview": 7,
}
_CREATED_LAST = 8

#: Where a definition kind is dropped: what depends on the others goes first, and a
#: schema, which everything lives in, last. A kind not named here is dropped first.
_DROPPED: dict[str, int] = {
    "view": -7,
    "matview": -8,
    "function": -6,
    "procedure": -6,
    "aggregate": -6,
    "domain": -4,
    "type": -4,
    "extension": -3,
    "schema": -2,
}
_DROPPED_FIRST = -9

#: The ranks the tables a migration adds and drops sit at.
_TABLES_DROPPED = -5
_TABLES_ADDED = 3
_ALTERED = 4


def _rank(change: SchemaChange) -> int:
    """Where *change* runs: drops (negative, dependents first), then creations and edits."""
    match change:
        case ObjectDropped(ref):
            return _DROPPED.get(ref.kind, _DROPPED_FIRST)
        case ObjectAdded(ref) | ObjectReplaced(ref):
            return _CREATED.get(ref.kind, _CREATED_LAST)
        case TableDropped():
            return _TABLES_DROPPED
        case EnumTypeDropped() | SequenceDropped():
            return _DROPPED["type"]
        case EnumTypeAdded() | EnumValuesChanged() | SequenceAdded():
            return _CREATED["type"]
        case TableAdded() | TableRenamed():
            return _TABLES_ADDED
        case (
            ColumnAdded()
            | ColumnDropped()
            | ColumnRenamed()
            | ColumnTypeChanged()
            | ColumnNullabilityChanged()
            | ColumnDefaultChanged()
            | IndexAdded()
            | IndexDropped()
            | ForeignKeyAdded()
            | ForeignKeyDropped()
            | CheckConstraintAdded()
            | CheckConstraintDropped()
            | UniqueConstraintAdded()
            | UniqueConstraintDropped()
        ):
            return _ALTERED
        case _:
            assert_never(change)


def _in_foreign_key_order(
    tables: Sequence[Table],
) -> tuple[list[Table], list[ForeignKeyAdded]]:
    """*tables*, each after the tables it references, and the foreign keys held back.

    A cycle has no such order. Each table in it is created without its foreign
    keys to the others, and those are returned to be added once every table
    exists — the builder's two-pass split, on the model.
    """
    by_ref = {ref_for("table", t.schema, t.name): t for t in tables}
    held: list[ForeignKeyAdded] = []
    while True:
        model = SchemaModel(tables=by_ref)
        try:
            order = dependency_order(model)
        except DependencyCycleError as cycle:
            members = set(cycle.tables)
            for ref in cycle.tables:
                table = by_ref[ref]
                closing = [
                    fk
                    for fk in table.constraints_of("foreign_key")
                    if resolve(model.tables, fk.ref_table or "") in members - {ref}
                ]
                held.extend(ForeignKeyAdded(table.qualified, fk) for fk in closing)
                kept = tuple(c for c in table.constraints if c not in closing)
                by_ref[ref] = replace(table, constraints=kept)
            continue
        return [by_ref[ref] for ref in order], held


def apply_order(changes: Sequence[SchemaChange]) -> list[SchemaChange]:
    """*changes* in an order PostgreSQL accepts, the differ's wherever it already does."""
    ranked = sorted(changes, key=_rank)
    added = [c.table for c in ranked if isinstance(c, TableAdded)]
    dropped = [c.table for c in ranked if isinstance(c, TableDropped)]
    tables, held = _in_foreign_key_order(added)
    # A dropped table goes before the tables it references: the reverse of creation.
    # Its down recreates it whole, so the order is taken, never the split.
    whole = {ref_for("table", t.schema, t.name): t for t in dropped}
    dropping = [
        whole[ref_for("table", t.schema, t.name)] for t in _in_foreign_key_order(dropped)[0]
    ][::-1]
    ordered: list[SchemaChange] = []
    for change in ranked:
        if isinstance(change, TableAdded):
            ordered.append(TableAdded(tables.pop(0)))
            if not tables:
                ordered.extend(held)
        elif isinstance(change, TableDropped):
            ordered.append(TableDropped(dropping.pop(0)))
        else:
            ordered.append(change)
    return ordered
