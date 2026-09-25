"""The seam a tool builds on: one schema model, what changed, and what a writer may supply.

Read a schema into the model — from DDL (:func:`parse_schema`) or from a database
(:func:`introspect`) — and compare two (:func:`diff`), each change typed and tiered
(:func:`tier_of`); order a model's tables by their foreign keys
(:func:`dependency_order`); and ask which columns a writer supplies
(:func:`writable_columns`) and what each must respect (:func:`column_facts`,
:func:`naming_hints`); write seeds (:func:`write_copy_seed`,
:func:`write_insert_seed`), apply them (:func:`apply_seeds`) and validate them
(:func:`validate_seeds`). Nothing here is defined here: every name is confiture's
own, re-exported so that a consumer depends on this list and nothing behind it.
``tests/contract/test_platform_surface.py`` pins the list, every signature and
every field, and ``docs/guides/building-on-confiture.md`` is its guide.

No signature names a parser or a driver type. A connection is a URL, which the
call opens and closes, or anything meeting :class:`Connection` — a psycopg 3
connection does — whose transaction stays the caller's.

What a call refuses it raises as a :class:`ConfiturError` naming what it
refused — :class:`SchemaError`, :class:`SeedError`, or a
:class:`ConfigurationError` for a URL that does not connect — with the driver's
or the codec's exception as its cause where there was one.
:class:`NotInModelError` is a ``SchemaError`` and a ``KeyError`` both. Two
errors are Python's own, for a mistake in the call itself: a ``TypeError`` for an
argument of the wrong type, and the ``ValueError`` that :func:`parse_schema`,
:func:`diff` and :func:`validate_seeds` raise for arguments that cannot be run
together.
"""

from confiture.config.environment import SeedProfile
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.connection import Connection
from confiture.core.ddl_objects import DDLObject
from confiture.core.introspection.dependency_graph import DependencyCycleError, dependency_order
from confiture.core.model_facts import (
    NotInModelError,
    column_facts,
    naming_hints,
    writable_columns,
)
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
    ExclusionConstraintAdded,
    ExclusionConstraintDropped,
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
from confiture.core.seed.applier import ApplyResult, apply_seeds
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.orchestrator import validate_seeds
from confiture.core.seed.writer import SeedFile, write_copy_seed, write_insert_seed
from confiture.exceptions import ConfigurationError, ConfiturError, SchemaError, SeedError
from confiture.models.introspection import TableHints
from confiture.models.warnings import BuildWarning

__all__ = [
    "ApplyResult",
    "BuildWarning",
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
    "ConfigurationError",
    "ConfiturError",
    "Connection",
    "Constraint",
    "DDLObject",
    "DependencyCycleError",
    "EnumType",
    "EnumTypeAdded",
    "EnumTypeDropped",
    "EnumValuesChanged",
    "ExclusionConstraintAdded",
    "ExclusionConstraintDropped",
    "ForeignKeyAdded",
    "ForeignKeyDropped",
    "Index",
    "IndexAdded",
    "IndexDropped",
    "NotInModelError",
    "ObjectAdded",
    "ObjectDropped",
    "ObjectRef",
    "ObjectReplaced",
    "PrepSeedPattern",
    "PrepSeedReport",
    "PrepSeedViolation",
    "RiskTier",
    "Routine",
    "SchemaChange",
    "SchemaDiff",
    "SchemaError",
    "SchemaModel",
    "SchemaSource",
    "SeedError",
    "SeedFile",
    "SeedProfile",
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
    "ViolationSeverity",
    "apply_seeds",
    "column_facts",
    "dependency_order",
    "diff",
    "introspect",
    "naming_hints",
    "parse_schema",
    "tier_of",
    "validate_seeds",
    "writable_columns",
    "write_copy_seed",
    "write_insert_seed",
]
