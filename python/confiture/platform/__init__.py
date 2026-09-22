"""The seam a tool builds on: one schema model, what changed, and what a writer may supply.

Read a schema into the model — from DDL (:func:`parse_schema`) or from a database
(:func:`introspect`) — and compare two (:func:`diff`), each change typed and tiered
(:func:`tier_of`); order a model's tables by their foreign keys
(:func:`dependency_order`); and ask which columns a writer supplies
(:func:`writable_columns`) and what each must respect (:func:`column_facts`,
:func:`naming_hints`). Nothing here is defined here: every name is confiture's
own, re-exported so that a consumer depends on this list and nothing behind it.
``tests/contract/test_platform_surface.py`` pins the list, every signature and
every field, and ``docs/guides/building-on-confiture.md`` is its guide.

No signature names a parser or a driver type. A connection is a URL, which the
call opens and closes, or anything meeting :class:`Connection` — a psycopg 3
connection does — whose transaction stays the caller's.
"""

from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.connection import Connection
from confiture.core.introspection.dependency_graph import DependencyCycle, dependency_order
from confiture.core.model_facts import column_facts, naming_hints, writable_columns
from confiture.core.risk_tier import RiskTier
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
    SchemaDiff,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableDropped,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import (
    Column,
    ColumnFacts,
    ColumnReference,
    Constraint,
    EnumType,
    Index,
    ObjectRef,
    Routine,
    SchemaModel,
    Sequence,
    Table,
    Trigger,
    View,
)
from confiture.core.schema_sources import SchemaSource, diff, introspect, parse_schema
from confiture.exceptions import SchemaError
from confiture.models.introspection import TableHints

__all__ = [
    "CheckConstraintAdded",
    "CheckConstraintDropped",
    "Column",
    "ColumnAdded",
    "ColumnDefaultChanged",
    "ColumnDropped",
    "ColumnFacts",
    "ColumnNullabilityChanged",
    "ColumnReference",
    "ColumnRenamed",
    "ColumnTypeChanged",
    "Connection",
    "Constraint",
    "DependencyCycle",
    "EnumType",
    "EnumTypeAdded",
    "EnumTypeDropped",
    "EnumValuesChanged",
    "ForeignKeyAdded",
    "ForeignKeyDropped",
    "Index",
    "IndexAdded",
    "IndexDropped",
    "ObjectAdded",
    "ObjectDropped",
    "ObjectRef",
    "ObjectReplaced",
    "RiskTier",
    "Routine",
    "SchemaChange",
    "SchemaDiff",
    "SchemaError",
    "SchemaModel",
    "SchemaSource",
    "Sequence",
    "SequenceAdded",
    "SequenceDropped",
    "Table",
    "TableAdded",
    "TableDropped",
    "TableHints",
    "TableRenamed",
    "Trigger",
    "UniqueConstraintAdded",
    "UniqueConstraintDropped",
    "View",
    "column_facts",
    "dependency_order",
    "diff",
    "introspect",
    "naming_hints",
    "parse_schema",
    "tier_of",
    "writable_columns",
]
