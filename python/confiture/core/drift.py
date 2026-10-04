"""Schema drift detection for Confiture.

Compares live database schema against expected state from migrations
to detect unauthorized changes or migration mishaps.
"""

import fnmatch
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Literal, get_args

import psycopg
from pydantic import ValidationError

from confiture.config.environment import AclExpectation, AclGrant, DriftConfig, OwnershipExpectation
from confiture.core import live_catalog
from confiture.core.ddl_clauses import constraint_body
from confiture.core.desired_state import load_desired_state
from confiture.core.differ import (
    CATALOGUED,
    MATERIALISED,
    ComparisonPolicy,
    Fidelity,
    SchemaDiffer,
    refuse_quoted_names,
    stated_side,
)
from confiture.core.ledger import bookkeeping_tables
from confiture.core.schema_analyzer import SchemaAnalyzer
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnOrderChanged,
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
    PrimaryKeyAdded,
    PrimaryKeyDropped,
    SchemaChange,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableDropped,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import (
    OTHER_OBJECT_KINDS,
    SCHEMALESS_KINDS,
    TVIEW_OPTIONS,
    Column,
    Constraint,
    Index,
    ObjectRef,
    OtherObject,
    RoutineKind,
    SchemaModel,
    Signature,
    Table,
    ref_for,
    routine_ref,
    trigger_ref,
)
from confiture.core.schema_read import SchemaRead, read_segments, read_text
from confiture.core.schema_sources import materialised_side
from confiture.core.server_constants import server_constants
from confiture.core.type_lattice import signatures_match
from confiture.exceptions import ConfigurationError, SchemaError
from confiture.exceptions import ValidationError as InvalidOption

logger = logging.getLogger(__name__)


class DriftType(Enum):
    """Types of schema drift."""

    MISSING_TABLE = "missing_table"
    EXTRA_TABLE = "extra_table"
    MISSING_COLUMN = "missing_column"
    EXTRA_COLUMN = "extra_column"
    TYPE_MISMATCH = "type_mismatch"
    NULLABLE_MISMATCH = "nullable_mismatch"
    DEFAULT_MISMATCH = "default_mismatch"
    COLUMN_ORDER_MISMATCH = "column_order_mismatch"
    MISSING_INDEX = "missing_index"
    EXTRA_INDEX = "extra_index"
    MISSING_CONSTRAINT = "missing_constraint"
    EXTRA_CONSTRAINT = "extra_constraint"
    CONSTRAINT_MISMATCH = "constraint_mismatch"
    MISSING_VIEW = "missing_view"
    EXTRA_VIEW = "extra_view"
    MISSING_MATVIEW = "missing_matview"
    EXTRA_MATVIEW = "extra_matview"
    MISSING_TRIGGER = "missing_trigger"
    EXTRA_TRIGGER = "extra_trigger"
    MISSING_ROUTINE = "missing_routine"
    EXTRA_ROUTINE = "extra_routine"
    MISSING_TVIEW = "missing_tview"
    EXTRA_TVIEW = "extra_tview"
    TVIEW_OPTION_MISMATCH = "tview_option_mismatch"
    MISSING_OBJECT = "missing_object"
    EXTRA_OBJECT = "extra_object"
    MISSING_GRANT = "missing_grant"
    EXTRA_GRANT = "extra_grant"
    WRONG_OWNER = "wrong_owner"


class DriftSeverity(Enum):
    """Severity of drift."""

    CRITICAL = "critical"  # Missing table/column
    WARNING = "warning"  # Extra objects, type changes
    INFO = "info"  # Minor differences


@dataclass(frozen=True)
class DriftSubject:
    """What a drift item is about, in parts: never joined, so a dot in a name stays in it (#505).

    ``object`` joins these with dots, and ``app.tb.a.b`` has several readings;
    the parts have one. ``relation`` is the table, view or trigger's table a
    finding is on, ``name`` the column, index, constraint, trigger or routine in
    it — ``None`` for a finding on the relation itself, or for a constraint or
    index the DDL left unnamed (its definition is in ``expected``). A routine's
    ``arguments`` are its argument types and a grant's ``role`` its grantee. An
    object no typed section holds names its ``kind`` (``extension``, ``policy``, …,
    :data:`~confiture.core.schema_model.OTHER_OBJECT_KINDS`), and has no ``schema``
    when it lives in none.
    """

    schema: str | None
    relation: str | None = None
    name: str | None = None
    arguments: tuple[str, ...] | None = None
    role: str | None = None
    kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The parts as the payload's ``subject`` carries them; ``kind`` only where there is one."""
        parts: dict[str, Any] = {
            "schema": self.schema,
            "relation": self.relation,
            "name": self.name,
            "arguments": list(self.arguments) if self.arguments is not None else None,
            "role": self.role,
        }
        if self.kind is not None:
            parts["kind"] = self.kind
        return parts


@dataclass
class DriftItem:
    """A single drift item."""

    drift_type: DriftType
    severity: DriftSeverity
    object_name: str
    expected: Any = None
    actual: Any = None
    message: str = ""
    details: dict[str, Any] | None = None
    subject: DriftSubject | None = None

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.drift_type.value}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        payload: dict[str, Any] = {
            "type": self.drift_type.value,
            "severity": self.severity.value,
            "object": self.object_name,
            "expected": str(self.expected) if self.expected is not None else None,
            "actual": str(self.actual) if self.actual is not None else None,
            "message": self.message,
            "subject": self.subject.to_dict() if self.subject is not None else None,
        }
        if self.details is not None:
            payload["details"] = self.details
        return payload


@dataclass
class DriftReport:
    """Report of schema drift detection."""

    database_name: str
    expected_schema_source: str  # "migrations" or file path
    drift_items: list[DriftItem] = field(default_factory=list)
    tables_checked: int = 0
    columns_checked: int = 0
    indexes_checked: int = 0
    #: Every constraint the tree declares, plus every one the database has and the
    #: tree does not (#507).
    constraints_checked: int = 0
    #: Declared constraints paired with a live one whose definition was compared.
    #: A CHECK is paired by name only (PostgreSQL stores its text analysed), so it
    #: is checked and not counted here: the two counts differ where #501 hid.
    constraint_definitions_compared: int = 0
    #: Views, matviews, triggers and routines compared — the objects a tree
    #: declares whose *existence* is checked (#303).
    objects_checked: int = 0
    detection_time_ms: int = 0
    #: How closely expressions were compared (``differ.Fidelity``): ``structural``
    #: unless a scratch server read the tree back (``materialised``).
    fidelity: Fidelity = "structural"

    @property
    def has_drift(self) -> bool:
        """Check if any drift was detected."""
        return len(self.drift_items) > 0

    @property
    def has_critical_drift(self) -> bool:
        """Check if any critical drift was detected."""
        return any(d.severity == DriftSeverity.CRITICAL for d in self.drift_items)

    @property
    def critical_count(self) -> int:
        """Count of critical drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        """Count of warning drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of info drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.INFO)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        payload: dict[str, Any] = {
            "database_name": self.database_name,
            "expected_schema_source": self.expected_schema_source,
            "has_drift": self.has_drift,
            "has_critical_drift": self.has_critical_drift,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "tables_checked": self.tables_checked,
            "columns_checked": self.columns_checked,
            "indexes_checked": self.indexes_checked,
            "constraints_checked": self.constraints_checked,
            "constraint_definitions_compared": self.constraint_definitions_compared,
            "objects_checked": self.objects_checked,
            "detection_time_ms": self.detection_time_ms,
            "drift_items": [d.to_dict() for d in self.drift_items],
        }
        # Said only when it is not the tier drift has always compared at.
        if self.fidelity != "structural":
            payload["fidelity"] = self.fidelity
        return payload


#: Which pair of drift types reports a kind's existence: every kind the schema
#: model holds beside a table. A function, a procedure and an aggregate share one
#: pair: the object's own name says which it is, and three more members of a
#: published enum would say nothing new.
_OBJECT_DRIFT_TYPES: dict[str, tuple[DriftType, DriftType]] = {
    "view": (DriftType.MISSING_VIEW, DriftType.EXTRA_VIEW),
    "matview": (DriftType.MISSING_MATVIEW, DriftType.EXTRA_MATVIEW),
    "trigger": (DriftType.MISSING_TRIGGER, DriftType.EXTRA_TRIGGER),
    "tview": (DriftType.MISSING_TVIEW, DriftType.EXTRA_TVIEW),
    **dict.fromkeys(get_args(RoutineKind), (DriftType.MISSING_ROUTINE, DriftType.EXTRA_ROUTINE)),
    # One generic pair for every kind no typed section holds: ``subject.kind`` says
    # which, and a severity that does not vary by kind needs no wire name per kind.
    **dict.fromkeys(OTHER_OBJECT_KINDS, (DriftType.MISSING_OBJECT, DriftType.EXTRA_OBJECT)),
}


@dataclass(frozen=True)
class _Object:
    """A view, routine or trigger as the existence comparison reads it.

    ``ref`` is its bucket and ``signature`` a routine's key, compared inside it
    (#275, #302). ``written`` is how a *missing* one is named — as the tree wrote
    it — and ``catalogued`` how an *extra* one is: as the database spells it.
    """

    ref: ObjectRef
    signature: Signature | None
    written: str
    catalogued: str
    subject: DriftSubject


def _objects(model: SchemaModel, sections: frozenset[str]) -> list[_Object]:
    """The objects *model* holds in *sections*: views, routines, triggers and TVIEWs."""
    found = [
        _Object(
            ref,
            None,
            view.qualified,
            f"{view.schema}.{view.name}",
            DriftSubject(ref.schema, view.name),
        )
        for ref, view in model.views.items()
        if "views" in sections
    ]
    found += [
        _Object(
            ref,
            routine.signature_key,
            routine.identity,
            f"{routine.schema}.{routine.name}"
            f"({', '.join(name for _schema, name in routine.signature_key)})",
            DriftSubject(
                ref.schema,
                None,
                routine.name,
                arguments=tuple(
                    name if schema is None else f"{schema}.{name}"
                    for schema, name in routine.signature_key
                ),
            ),
        )
        for ref, overloads in model.routines.items()
        if "routines" in sections
        for routine in overloads
    ]
    found += [
        _Object(
            ref,
            None,
            trigger.qualified,
            f"{trigger.schema}.{trigger.table}.{trigger.name}",
            DriftSubject(ref.schema, trigger.table, trigger.name),
        )
        for ref, trigger in model.triggers.items()
        if "triggers" in sections
    ]
    found += [
        _Object(
            ref,
            None,
            tview.qualified,
            f"{tview.schema}.{tview.name}",
            DriftSubject(ref.schema, tview.name),
        )
        for ref, tview in model.tviews.items()
        if "tviews" in sections
    ]
    found += [
        _other(ref, obj) for ref, obj in model.other_objects.items() if "other_objects" in sections
    ]
    return found


def _other(ref: ObjectRef, obj: OtherObject) -> _Object:
    """An object no typed section holds, named by its kind and, where it has one, its schema."""
    schema = None if obj.kind in SCHEMALESS_KINDS else obj.schema
    named = obj.name if schema is None else f"{schema}.{obj.name}"
    return _Object(ref, None, named, named, DriftSubject(schema, None, obj.name, kind=obj.kind))


def _kind_label(kind: str) -> str:
    """How a message names a kind: ``foreign_data_wrapper`` is "Foreign data wrapper"."""
    return kind.replace("_", " ").capitalize()


def _order(obj: _Object) -> str:
    return str((obj.ref.kind, obj.ref.schema, obj.ref.name.lower(), obj.ref.signature))


DEFAULT_SCHEMA = "public"


@dataclass
class ExpectedSchema:
    """What a schema file declares: the schema model and the schemas it names."""

    model: SchemaModel
    schemas: frozenset[str]


def _in_schema(model: SchemaModel, default_schema: str) -> SchemaModel:
    """*model* with every unqualified object placed in *default_schema* (#227).

    A view, routine, trigger or TVIEW is *keyed* in *default_schema* and keeps the
    spelling the tree wrote, which is how a finding names one that is missing.
    """

    def placed(obj: Any) -> Any:
        return replace(obj, schema=obj.schema or default_schema)

    return SchemaModel(
        coverage=model.coverage,
        source=model.source,
        routines={
            routine_ref(placed(overloads[0])): overloads for overloads in model.routines.values()
        },
        views={
            ref_for(v.kind, v.schema or default_schema, v.name): v for v in model.views.values()
        },
        triggers={trigger_ref(placed(t)): t for t in model.triggers.values()},
        tables={
            ref_for("table", t.schema or default_schema, t.name): placed(t)
            for t in model.tables.values()
        },
        enum_types={
            ref_for("type", e.schema or default_schema, e.name): placed(e)
            for e in model.enum_types.values()
        },
        sequences={
            ref_for("sequence", q.schema or default_schema, q.name): placed(q)
            for q in model.sequences.values()
        },
        tviews={
            ref_for("tview", t.schema or default_schema, t.name): t for t in model.tviews.values()
        },
        other_objects=model.other_objects,
    )


def parse_expected_schema(sql: str, default_schema: str = DEFAULT_SCHEMA) -> ExpectedSchema:
    """Read the expected schema out of DDL text into the schema model (#227).

    :func:`expected_schema` over :func:`~confiture.core.schema_read.read_text`.

    Raises:
        SchemaError: as :func:`expected_schema`.
    """
    return expected_schema(_read_expected(lambda: read_text(sql)), default_schema)


def expected_schema(read: SchemaRead, default_schema: str = DEFAULT_SCHEMA) -> ExpectedSchema:
    """The expected schema a tree declares, as PostgreSQL would hold it.

    The tree's catalogued model (``SchemaRead.catalogued``): a ``PARTITION OF`` or
    ``INHERITS`` child holds its parents' columns, as the live catalog lists them,
    and an unqualified object belongs to ``default_schema``. ``CREATE SCHEMA``
    declares a schema and no table.

    Raises:
        DifferError: ``DIFFER_403`` when the tree names an object that needs quotes.
    """
    refuse_quoted_names("expected", read.quoted)
    model = _in_schema(read.catalogued, default_schema)
    schemas = {default_schema} | {t.schema for t in model.tables.values() if t.schema}
    schemas |= {declared.name for declared in read.inventory.schemas}
    return ExpectedSchema(model=model, schemas=frozenset(schemas))


def _read_expected(read: Callable[[], SchemaRead]) -> SchemaRead:
    """*read*'s answer; a parse failure is ``SCHEMA_202``, naming the file and line.

    Loudly, rather than as an empty expectation that would report every live
    table as spurious drift.
    """
    try:
        return read()
    except SchemaError as exc:
        if exc.error_code != "DIFFER_400":
            raise
        raise SchemaError(
            f"The expected schema could not be parsed: {exc.message}. "
            "Comparing against it would report every live table as spurious drift.",
            error_code="SCHEMA_202",
            context=exc.context,
            resolution_hint="Fix the SQL syntax at the file and line named.",
        ) from exc


#: How a finding names a constraint the DDL left unnamed.
_CONSTRAINT_KEYWORDS = {
    "primary_key": "PRIMARY KEY",
    "unique": "UNIQUE",
    "check": "CHECK",
    "foreign_key": "FOREIGN KEY",
    "exclusion": "EXCLUDE",
}


def _named(table: Table) -> str:
    """``schema.table``: how a finding names a table."""
    return f"{table.schema or DEFAULT_SCHEMA}.{table.name}"


def _subject(table: Table, name: str | None = None) -> DriftSubject:
    """A finding on *table*, or on the column, index or constraint *name* in it."""
    return DriftSubject(table.schema or DEFAULT_SCHEMA, table.name, name)


def _column_facts(column: Column) -> dict[str, Any]:
    """A column as a finding reports it: the shape of ``expected`` / ``actual``."""
    return {"type": column.type_text, "nullable": not column.not_null, "default": column.default}


def _constraint_label(constraint: Constraint) -> str:
    if constraint.name:
        return constraint.name
    keyword = _CONSTRAINT_KEYWORDS[constraint.kind]
    return f"{keyword} ({', '.join(constraint.columns)})" if constraint.columns else keyword


# ---------------------------------------------------------------------------
# Drift is the one comparison, said as findings
# ---------------------------------------------------------------------------

#: Which stray objects of the kinds no other drift type names are reported
#: (``drift.extra_objects``): those of a kind the DDL declares, or all of them.
ExtraObjects = Literal["declared", "all"]

#: How drift compares: the tree is an author's and the database PostgreSQL's,
#: whatever each model says (a test may build both from DDL).
_POLICY = replace(CATALOGUED, author="new")
#: How drift compares once a scratch server has read the tree back: still the
#: tree's side whose unnamed objects PostgreSQL named.
_MATERIALISED = replace(MATERIALISED, author="new")

#: Every change the comparison makes, as the finding drift reports for it — or,
#: for a change drift has no finding for, why. A constraint dropped and added under
#: one name is one ``constraint_mismatch``; an object's kind picks its pair of
#: ``_OBJECT_DRIFT_TYPES``; a TVIEW redefined is one ``tview_option_mismatch`` per
#: option the tree pins; the column order's severity is ``column_order_severity``.
DRIFT_OF: dict[type[SchemaChange], tuple[DriftType | None, DriftSeverity] | str] = {
    TableAdded: (DriftType.MISSING_TABLE, DriftSeverity.CRITICAL),
    TableDropped: (DriftType.EXTRA_TABLE, DriftSeverity.WARNING),
    TableRenamed: "a database renames nothing by similarity: drift's policy pairs no rename",
    ColumnAdded: (DriftType.MISSING_COLUMN, DriftSeverity.CRITICAL),
    ColumnDropped: (DriftType.EXTRA_COLUMN, DriftSeverity.WARNING),
    ColumnRenamed: "a database renames nothing by similarity: drift's policy pairs no rename",
    ColumnTypeChanged: (DriftType.TYPE_MISMATCH, DriftSeverity.WARNING),
    ColumnNullabilityChanged: (DriftType.NULLABLE_MISMATCH, DriftSeverity.WARNING),
    ColumnDefaultChanged: (DriftType.DEFAULT_MISMATCH, DriftSeverity.WARNING),
    ColumnOrderChanged: (DriftType.COLUMN_ORDER_MISMATCH, DriftSeverity.WARNING),
    IndexAdded: (DriftType.MISSING_INDEX, DriftSeverity.WARNING),
    IndexDropped: (DriftType.EXTRA_INDEX, DriftSeverity.INFO),
    **dict.fromkeys(
        (
            ForeignKeyAdded,
            CheckConstraintAdded,
            UniqueConstraintAdded,
            PrimaryKeyAdded,
            ExclusionConstraintAdded,
        ),
        (DriftType.MISSING_CONSTRAINT, DriftSeverity.CRITICAL),
    ),
    **dict.fromkeys(
        (
            ForeignKeyDropped,
            CheckConstraintDropped,
            UniqueConstraintDropped,
            PrimaryKeyDropped,
            ExclusionConstraintDropped,
        ),
        (DriftType.EXTRA_CONSTRAINT, DriftSeverity.INFO),
    ),
    EnumTypeAdded: "drift reports no enum type",
    EnumTypeDropped: "drift reports no enum type",
    EnumValuesChanged: "drift reports no enum type",
    SequenceAdded: "drift reports no sequence",
    SequenceDropped: "drift reports no sequence",
    ObjectAdded: (None, DriftSeverity.CRITICAL),
    ObjectDropped: (None, DriftSeverity.INFO),
    ObjectReplaced: (DriftType.TVIEW_OPTION_MISMATCH, DriftSeverity.WARNING),
}

_CONSTRAINT_ADDED = (
    ForeignKeyAdded,
    CheckConstraintAdded,
    UniqueConstraintAdded,
    PrimaryKeyAdded,
    ExclusionConstraintAdded,
)
_CONSTRAINT_DROPPED = (
    ForeignKeyDropped,
    CheckConstraintDropped,
    UniqueConstraintDropped,
    PrimaryKeyDropped,
    ExclusionConstraintDropped,
)


_ON_TABLE = (
    ColumnAdded,
    ColumnDropped,
    ColumnTypeChanged,
    ColumnNullabilityChanged,
    ColumnDefaultChanged,
    ColumnOrderChanged,
    IndexAdded,
    IndexDropped,
    *_CONSTRAINT_ADDED,
    *_CONSTRAINT_DROPPED,
)


def _index_label(index: Index) -> str:
    return f"({', '.join(index.columns)})"


def _nth(found: Sequence[Any], wanted: Iterable[Any]) -> list[int]:
    """Where each of *wanted* is in *found*, each position used once: equal ones are distinct."""
    taken: set[int] = set()
    positions = []
    for item in wanted:
        at = next(i for i, other in enumerate(found) if i not in taken and other == item)
        taken.add(at)
        positions.append(at)
    return positions


@dataclass
class _Findings:
    """The changes of one comparison, said as drift: in drift's order, with drift's words."""

    expected: SchemaModel
    actual: SchemaModel
    column_order_severity: DriftSeverity
    #: Which stray objects of the kinds no other type names are reported:
    #: ``declared`` kinds only (info), or ``all`` of them (warning).
    extra_objects: ExtraObjects = "declared"

    def render(
        self, changes: list[SchemaChange], report: DriftReport, *, column_order: bool
    ) -> None:
        """Every finding *changes* is, appended to *report* with what it counted."""
        on_table: dict[tuple[str, str], list[SchemaChange]] = defaultdict(list)
        objects: list[SchemaChange] = []
        for change in changes:
            if isinstance(change, ObjectAdded | ObjectDropped | ObjectReplaced):
                objects.append(change)
            elif isinstance(change, TableAdded | TableDropped):
                on_table[("", "")].append(change)
            elif isinstance(change, _ON_TABLE) and (
                column_order or not isinstance(change, ColumnOrderChanged)
            ):
                on_table[change.table.identity].append(change)
        self._tables(on_table.pop(("", ""), []), report)
        expected = {t.relation.identity: t for t in self.expected.tables.values()}
        actual = {t.relation.identity: t for t in self.actual.tables.values()}
        for key in sorted(expected.keys() & actual.keys(), key=lambda k: _named(expected[k])):
            report.tables_checked += 1
            self._table(expected[key], actual[key], on_table.get(key, []), report)
        self._objects(objects, report)

    def _tables(self, changes: list[SchemaChange], report: DriftReport) -> None:
        added = sorted((c.table for c in changes if isinstance(c, TableAdded)), key=_named)
        dropped = sorted((c.table for c in changes if isinstance(c, TableDropped)), key=_named)
        for table in added:
            name = _named(table)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    severity=DriftSeverity.CRITICAL,
                    object_name=name,
                    expected=name,
                    actual=None,
                    subject=_subject(table),
                    message=f"Table '{name}' is missing from database",
                )
            )
        for table in dropped:
            name = _named(table)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_TABLE,
                    severity=DriftSeverity.WARNING,
                    object_name=name,
                    expected=None,
                    actual=name,
                    subject=_subject(table),
                    message=f"Table '{name}' exists but is not in expected schema",
                )
            )

    def _table(
        self, expected: Table, actual: Table, changes: list[SchemaChange], report: DriftReport
    ) -> None:
        self._columns(expected, actual, changes, report)
        self._indexes(expected, actual, changes, report)
        self._constraints(expected, actual, changes, report)

    def _columns(
        self, expected: Table, actual: Table, changes: list[SchemaChange], report: DriftReport
    ) -> None:
        table = _named(expected)
        for change in sorted(
            (c for c in changes if isinstance(c, ColumnAdded)), key=lambda c: c.column.folded
        ):
            col = change.column.folded
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_COLUMN,
                    severity=DriftSeverity.CRITICAL,
                    object_name=f"{table}.{col}",
                    expected=_column_facts(change.column),
                    subject=_subject(expected, col),
                    actual=None,
                    message=f"Column '{table}.{col}' is missing",
                )
            )
        for change in sorted(
            (c for c in changes if isinstance(c, ColumnDropped)), key=lambda c: c.column.folded
        ):
            col = change.column.folded
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_COLUMN,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table}.{col}",
                    expected=None,
                    actual=_column_facts(change.column),
                    subject=_subject(actual, col),
                    message=f"Column '{table}.{col}' exists but is not expected",
                )
            )
        shared = {c.folded for c in expected.columns} & {c.folded for c in actual.columns}
        report.columns_checked += len(shared)
        for col in sorted(shared):
            for change in changes:
                item = _column_finding(change, col, f"{table}.{col}", _subject(expected, col))
                if item is not None:
                    report.drift_items.append(item)
        for change in changes:
            if isinstance(change, ColumnOrderChanged):
                expected_order, actual_order = list(change.new), list(change.old)
                report.drift_items.append(
                    DriftItem(
                        drift_type=DriftType.COLUMN_ORDER_MISMATCH,
                        severity=self.column_order_severity,
                        object_name=table,
                        subject=_subject(expected),
                        expected=", ".join(expected_order),
                        actual=", ".join(actual_order),
                        message=(
                            f"Columns of '{table}' are in a different order: expected "
                            f"({', '.join(expected_order)}), got ({', '.join(actual_order)})"
                        ),
                        details={"expected_order": expected_order, "actual_order": actual_order},
                    )
                )

    def _indexes(
        self, expected: Table, actual: Table, changes: list[SchemaChange], report: DriftReport
    ) -> None:
        """A declared index the database lacks, and an index it has that nothing declares.

        An index PostgreSQL created to back a constraint is the constraint's, never
        extra; one the DDL left unnamed is the live one that says the same thing.
        """
        table = _named(expected)
        added = [c.index for c in changes if isinstance(c, IndexAdded)]
        extra = sorted(c.index.name or "" for c in changes if isinstance(c, IndexDropped))
        report.indexes_checked += len(expected.indexes) + len(extra)
        missing: list[tuple[str, str | None]] = [
            (name, name) for name in sorted(ix.name for ix in added if ix.name)
        ]
        unnamed = [ix for ix in added if not ix.name]
        missing += [
            (_index_label(expected.indexes[at]), None)
            for at in sorted(_nth(expected.indexes, unnamed))
        ]
        for label, name in missing:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_INDEX,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table}.{label}",
                    subject=_subject(expected, name),
                    expected=label,
                    actual=None,
                    message=f"Index '{label}' on '{table}' is missing",
                )
            )
        for name in extra:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_INDEX,
                    severity=DriftSeverity.INFO,
                    object_name=f"{table}.{name}",
                    subject=_subject(actual, name),
                    expected=None,
                    actual=name,
                    message=f"Index '{name}' on '{table}' exists but is not expected",
                )
            )

    def _constraints(
        self, expected: Table, actual: Table, changes: list[SchemaChange], report: DriftReport
    ) -> None:
        """A constraint the tree declares and the database lost, holds otherwise, or lacks.

        A lost constraint and one that says something else under its name are
        CRITICAL (#506): a dropped or re-pointed foreign key lets rows exist that
        could not before. An extra one is INFO: it loses no data.
        """
        table = _named(expected)
        added = [c.constraint for c in changes if isinstance(c, _CONSTRAINT_ADDED)]
        dropped = [c.constraint for c in changes if isinstance(c, _CONSTRAINT_DROPPED)]
        changed = [
            (declared, live)
            for declared in added
            for live in dropped
            if declared.name and (declared.kind, declared.name) == (live.kind, live.name)
        ]
        missing = [c for c in added if all(c is not declared for declared, _ in changed)]
        extra = [c for c in dropped if all(c is not live for _, live in changed)]
        declared_order = sorted(expected.constraints, key=lambda c: not c.name)
        report.constraints_checked += len(expected.constraints) + len(extra)
        report.constraint_definitions_compared += sum(
            c.kind != "check" for c in expected.constraints
        ) - sum(c.kind != "check" for c in missing)

        for at in sorted(_nth(declared_order, missing)):
            constraint = declared_order[at]
            label = _constraint_label(constraint)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_CONSTRAINT,
                    severity=DriftSeverity.CRITICAL,
                    object_name=f"{table}.{label}",
                    subject=_subject(expected, constraint.name),
                    expected=label,
                    actual=None,
                    message=f"Constraint '{label}' on '{table}' is missing",
                )
            )
        for declared, live in sorted(changed, key=lambda pair: _nth(declared_order, [pair[0]])[0]):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.CONSTRAINT_MISMATCH,
                    severity=DriftSeverity.CRITICAL,
                    object_name=f"{table}.{declared.name}",
                    subject=_subject(expected, declared.name),
                    expected=constraint_body(declared),
                    actual=constraint_body(live),
                    message=f"Constraint '{declared.name}' on '{table}' is not what the DDL declares",
                )
            )
        for at in sorted(_nth(actual.constraints, extra)):
            constraint = actual.constraints[at]
            label = _constraint_label(constraint)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_CONSTRAINT,
                    severity=DriftSeverity.INFO,
                    object_name=f"{table}.{label}",
                    subject=_subject(actual, constraint.name),
                    expected=None,
                    actual=label,
                    message=f"Constraint '{label}' on '{table}' exists but is not expected",
                )
            )

    def _objects(self, changes: list[SchemaChange], report: DriftReport) -> None:
        """Views, matviews, triggers, routines and TVIEWs: what the tree declares against what exists.

        A **missing** object is CRITICAL, by analogy with ``missing_column``. An
        **extra** one is INFO, and only of a kind the tree declares at least one
        of, in a schema it declares one in: "this project does not manage views
        here" and "this project has lost all its views" are indistinguishable from
        an empty expected set. Only the kinds both sides read are compared:
        silence from a section nobody asked the catalogue about is not absence.
        """
        sections = frozenset(
            section
            for section in ("views", "routines", "triggers", "tviews", "other_objects")
            if self.expected.coverage.shared(self.actual.coverage, section)
        )
        report.objects_checked += sum(
            len(getattr(self.expected, section))
            for section in ("views", "routines", "triggers")
            if section in sections
        )
        declared = _objects(self.expected, sections)
        live = _objects(self.actual, sections)
        missing = [
            _object_for(declared, c.ref, c.obj.signature)
            for c in changes
            if isinstance(c, ObjectAdded) and c.ref.kind in _OBJECT_DRIFT_TYPES
        ]
        kinds = {obj.ref.kind for obj in declared}
        schemas = {obj.ref.schema for obj in declared}
        every = self.extra_objects == "all"
        extra = [
            _object_for(live, c.ref, c.obj.signature)
            for c in changes
            if isinstance(c, ObjectDropped)
            and (
                (c.ref.kind in kinds and c.ref.schema in schemas)
                or (every and c.ref.kind in OTHER_OBJECT_KINDS)
            )
        ]
        for obj in sorted(missing, key=_order):
            report.drift_items.append(
                DriftItem(
                    drift_type=_OBJECT_DRIFT_TYPES[obj.ref.kind][0],
                    severity=DriftSeverity.CRITICAL,
                    object_name=obj.written,
                    subject=obj.subject,
                    expected=obj.written,
                    actual=None,
                    message=f"{_kind_label(obj.ref.kind)} '{obj.written}' is missing from database",
                )
            )
        for obj in sorted(extra, key=_order):
            report.drift_items.append(
                DriftItem(
                    drift_type=_OBJECT_DRIFT_TYPES[obj.ref.kind][1],
                    # Asked for every stray object, for a gate to escalate: a warning.
                    severity=(
                        DriftSeverity.WARNING
                        if every and obj.ref.kind in OTHER_OBJECT_KINDS
                        else DriftSeverity.INFO
                    ),
                    object_name=obj.catalogued,
                    subject=obj.subject,
                    expected=None,
                    actual=obj.catalogued,
                    message=(
                        f"{_kind_label(obj.ref.kind)} '{obj.catalogued}' exists but is not "
                        "in expected schema"
                    ),
                )
            )
        redefined = sorted(
            (c.ref for c in changes if isinstance(c, ObjectReplaced) and c.ref.kind == "tview"),
            key=lambda ref: (ref.schema, ref.name),
        )
        for ref in redefined:
            report.drift_items.extend(_tview_options(ref, self.expected, self.actual))


def _column_finding(
    change: SchemaChange, col: str, name: str, subject: DriftSubject
) -> DriftItem | None:
    """The finding *change* is on column *col*, or ``None`` when it is on another or not one."""
    if isinstance(change, ColumnTypeChanged) and change.new.folded == col:
        exp_type, act_type = change.new.type_text or "", change.old.type_text or ""
        return DriftItem(
            drift_type=DriftType.TYPE_MISMATCH,
            severity=DriftSeverity.WARNING,
            object_name=name,
            subject=subject,
            expected=exp_type,
            actual=act_type,
            message=f"Column '{name}' type mismatch: expected {exp_type}, got {act_type}",
        )
    if isinstance(change, ColumnNullabilityChanged) and change.column == col:
        nullable = change.nullable
        return DriftItem(
            drift_type=DriftType.NULLABLE_MISMATCH,
            severity=DriftSeverity.WARNING,
            object_name=name,
            subject=subject,
            expected=f"nullable={nullable}",
            actual=f"nullable={not nullable}",
            message=f"Column '{name}' nullable mismatch: expected {nullable}, got {not nullable}",
        )
    if isinstance(change, ColumnDefaultChanged) and change.column == col:
        return DriftItem(
            drift_type=DriftType.DEFAULT_MISMATCH,
            severity=DriftSeverity.WARNING,
            object_name=name,
            subject=subject,
            expected=change.new,
            actual=change.old,
            message=f"Column '{name}' default mismatch: expected {change.new}, got {change.old}",
        )
    return None


def _object_for(found: list[_Object], ref: ObjectRef, signature: Signature | None) -> _Object:
    """The object of *found* a change on *ref* is about: a routine by its signature."""
    return next(
        obj for obj in found if obj.ref == ref and signatures_match(signature, obj.signature)
    )


def _tview_options(ref: ObjectRef, expected: SchemaModel, actual: SchemaModel) -> list[DriftItem]:
    """Each option a TVIEW's tree pins that the database's TVIEW does not hold.

    A key the tree does not pin is pg_tviews' default or a choice made by hand,
    which the tree left open: never drift.
    """
    declared, found = expected.tviews[ref], actual.tviews[ref]
    items = []
    for key in TVIEW_OPTIONS:
        pinned, held = getattr(declared, key), getattr(found, key)
        if pinned is None or pinned == held:
            continue
        items.append(
            DriftItem(
                drift_type=DriftType.TVIEW_OPTION_MISMATCH,
                severity=DriftSeverity.WARNING,
                object_name=declared.qualified,
                subject=DriftSubject(ref.schema, declared.name, key),
                expected=f"{key} = {json.dumps(pinned)}",
                actual=f"{key} = {json.dumps(held)}",
                message=(
                    f"TVIEW '{declared.qualified}' pins {key} = {json.dumps(pinned)}; "
                    f"the database holds {json.dumps(held)}"
                ),
            )
        )
    return items


def extra_objects_of(flag: str | None, configured: ExtraObjects) -> ExtraObjects:
    """``--extra-objects`` when given, else the config's ``drift.extra_objects``.

    Raises:
        ValidationError: ``VALID_001`` for a flag that is neither ``declared`` nor ``all``.
    """
    if flag is None:
        return configured
    if flag == "all":
        return "all"
    if flag == "declared":
        return "declared"
    raise InvalidOption(
        f"Invalid --extra-objects {flag!r}: use 'declared' or 'all'.",
        resolution_hint="--extra-objects all reports every stray object, as a warning.",
    )


def drift_config_from(config_data: Any) -> DriftConfig:
    """The ``drift:`` block of a loaded config as a :class:`DriftConfig` (#226).

    A missing block is the defaults; a block that is not a mapping or fails
    validation is ``CONFIG_001`` — a configuration error, not a connection one.
    """

    raw = config_data.get("drift") if isinstance(config_data, dict) else None
    if raw is None:
        return DriftConfig()
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"'drift' must be a mapping, got {type(raw).__name__}",
            error_code="CONFIG_001",
            resolution_hint="Use `drift:\n  ignore_column_order: false\n  column_order_severity: warning`.",
        )
    try:
        return DriftConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid 'drift' configuration: {exc.errors()[0].get('msg', exc)}",
            error_code="CONFIG_001",
            resolution_hint=(
                "Allowed keys: ignore_column_order (bool), column_order_severity "
                "(warning|critical), extra_objects (declared|all)."
            ),
        ) from exc


class SchemaDriftDetector:
    """Detects schema drift between live database and expected state.

    Compares live database schema against expected state to find:
    - Missing/extra tables
    - Missing/extra columns
    - Type mismatches
    - Nullable mismatches
    - Missing/extra indexes

    Example:
        >>> detector = SchemaDriftDetector(conn)
        >>> report = detector.compare_with_expected(expected_schema)
        >>> if report.has_critical_drift:
        ...     print("CRITICAL: Schema has drifted!")
        ...     for item in report.drift_items:
        ...         print(f"  {item}")
    """

    # Confiture's own bookkeeping: never drift, whatever the schema declares
    SYSTEM_TABLES: ClassVar[frozenset[str]] = bookkeeping_tables()

    def __init__(
        self,
        connection: psycopg.Connection,
        ignore_tables: list[str] | None = None,
        *,
        ignore_column_order: bool = False,
        column_order_severity: str = "warning",
        scratch_url: str | None = None,
        extra_objects: ExtraObjects = "declared",
    ):
        """Initialize drift detector.

        Args:
            connection: Database connection
            ignore_tables: Additional tables to ignore in drift detection
            ignore_column_order: Skip the column-order comparison (#226)
            column_order_severity: ``"warning"`` (default) or ``"critical"`` for a
                ``column_order_mismatch`` item
            scratch_url: A writable server to build a schema file into and read it
                back from, so its expressions compare as PostgreSQL stores them
                (``materialised``); ``None`` compares them structurally.
            extra_objects: ``declared`` reports a stray schema, extension, policy, …
                (``extra_object``, info) only of a kind the DDL declares; ``all``
                reports one of any kind, as a warning.
        """
        self.connection = connection
        self.scratch_url = scratch_url
        self.extra_objects: ExtraObjects = extra_objects
        self.ignore_column_order = ignore_column_order
        self.column_order_severity = (
            DriftSeverity.CRITICAL if column_order_severity == "critical" else DriftSeverity.WARNING
        )
        self.analyzer = SchemaAnalyzer(connection)
        self.ignore_tables = set(ignore_tables or [])
        # Always ignore Confiture's own tables
        self.ignore_tables.update(self.SYSTEM_TABLES)

    def _ignored(self, table_key: str) -> bool:
        """``ignore_tables`` takes ``schema.table`` or a bare name matched against the table part."""
        return table_key in self.ignore_tables or table_key.rsplit(".", 1)[-1] in self.ignore_tables

    def compare_schemas(
        self,
        expected: SchemaModel,
        actual: SchemaModel,
    ) -> DriftReport:
        """What is wrong with the database *actual* holds, against the tree *expected* declares.

        Both are ``core/schema_model`` values — the expected side the tree's, the
        live side ``live_catalog``'s. They are compared once, by the one
        comparison (``SchemaDiffer.compare_sides``) under the policy a tree and a
        database call for, and drift is that diff said as findings
        (:data:`DRIFT_OF`): what would make the database the tree is what is
        wrong with it. A default is compared as a value: the database's server
        spells the tree's constants (``server_constants``).

        Args:
            expected: Expected schema state
            actual: Actual (live) schema state

        Returns:
            DriftReport with differences
        """
        # The database's server spells the tree's constants (#564).
        constants = server_constants(self.connection, self._kept(expected))
        return self._compare(expected, actual, replace(_POLICY, constants=constants))

    def _compare(
        self, expected: SchemaModel, actual: SchemaModel, policy: ComparisonPolicy
    ) -> DriftReport:
        """*expected* against *actual* under *policy*, said as drift."""
        start_time = time.perf_counter()
        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="provided",
            fidelity=policy.fidelity,
        )
        expected, actual = self._kept(expected), self._kept(actual)
        diff = SchemaDiffer().compare_sides(stated_side(actual), stated_side(expected), policy)
        _Findings(expected, actual, self.column_order_severity, self.extra_objects).render(
            diff.changes, report, column_order=not self.ignore_column_order
        )
        report.detection_time_ms = int((time.perf_counter() - start_time) * 1000)
        return report

    def _kept(self, model: SchemaModel) -> SchemaModel:
        """*model* without the tables drift ignores, and without the default schema itself.

        A tree puts objects in the default schema without creating it, and a
        database recreates it (a test database's `public` is a user object), so
        the schema object is never the tree's to report missing or extra; one the
        tree writes ``CREATE SCHEMA`` for is compared on both sides, or neither.
        """
        tables = {ref: t for ref, t in model.tables.items() if not self._ignored(_named(t))}
        default = ref_for("schema", None, DEFAULT_SCHEMA)
        others = {ref: o for ref, o in model.other_objects.items() if ref != default}
        return replace(model, tables=tables, other_objects=others)

    def get_live_schema(
        self, schemas: Iterable[str] | None = None, *, objects: bool = False
    ) -> SchemaModel:
        """The live schema in *schemas* (``public`` when none are named), as the model.

        *objects* reads the views, matviews, triggers and routines too, through the
        detector's own connection — the one that honours ``--ssh``. An extension's
        own are the extension's, not the tree's: ``citext`` alone installs a dozen
        functions, so without leaving them out a pristine database reports dozens
        of extra routines.
        """
        wanted = sorted(set(schemas)) if schemas is not None else [DEFAULT_SCHEMA]
        return live_catalog.read(
            self.connection,
            schemas=wanted,
            routines=objects,
            views=objects,
            triggers=objects,
            other_objects=objects,
        )

    def compare_with_expected(self, expected: SchemaModel) -> DriftReport:
        """Compare the live database with an expected schema model.

        The live side reads the schemas *expected* places its tables in.
        """
        schemas = {t.schema or DEFAULT_SCHEMA for t in expected.tables.values()}
        actual = self.get_live_schema(schemas or None)
        report = self.compare_schemas(expected, actual)
        report.expected_schema_source = "provided"
        return report

    def compare_with_schema_file(
        self, schema_file_path: str, default_schema: str = DEFAULT_SCHEMA
    ) -> DriftReport:
        """Compare the live database with a schema SQL file.

        The file is read into the schema model (#227); an unqualified name resolves to
        ``default_schema``, and the live side reads exactly the schemas the file
        declares or qualifies with.

        Args:
            schema_file_path: Schema SQL file, or a directory of ``.sql`` files read in name order
            default_schema: Schema an unqualified ``CREATE TABLE`` belongs to

        Returns:
            DriftReport with differences
        """
        path = Path(schema_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file_path}")

        source = load_desired_state(schema_file_path)
        expected = expected_schema(
            _read_expected(lambda: read_segments(source.segments())), default_schema
        )
        actual = self.get_live_schema(expected.schemas, objects=True)
        if self.scratch_url is None:
            report = self.compare_schemas(expected.model, actual)
        else:
            built = materialised_side(
                source.read(),
                self.scratch_url,
                declared=expected.model,
                schemas=sorted(expected.schemas),
                default_schema=default_schema,
            )
            report = self._compare(built.model, actual, _MATERIALISED)
        report.expected_schema_source = f"file:{schema_file_path}"
        return report

    def _get_database_name(self) -> str:
        """Get current database name."""
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            result = cur.fetchone()
            return result[0] if result else "unknown"


class AclDriftDetector:
    """Detect ACL drift between live ``pg_class.relacl`` and the ``acls:`` config.

    Two query paths — kept visually separate by design:

    * :meth:`_check_missing` uses ``has_table_privilege(role, table, priv)``.
      That's a hypothesis-check: it answers "does this role hold this
      privilege?" and transparently handles role-membership inheritance,
      ``PUBLIC``, and ownership.  One question per ``(table, role, priv)``.

    * :meth:`_check_extra` uses ``information_schema.role_table_grants``.
      That's an enumeration of *directly granted* privileges per role on
      a table.  We need enumeration here because ``has_table_privilege``
      cannot say what *else* a role holds, only confirm or deny a guess.
      Privileges held only via ``PUBLIC`` (or via owner-implicit rules)
      are deliberately not in this view, so they don't show up as extras.

    System tables (``tb_confiture`` etc.) are excluded via the same
    :pyattr:`SchemaDriftDetector.SYSTEM_TABLES` set.

    Example::

        from confiture.config.environment import Environment
        from confiture.core.drift import AclDriftDetector

        env = Environment.load("production")
        with psycopg.connect(env.database_url) as conn:
            report = AclDriftDetector(conn).check(env.acls)
            if report.has_critical_drift:
                raise SystemExit(1)
    """

    # Reuse the same exclusion set as the structural detector so confiture's
    # own tracking tables never count as drift.
    SYSTEM_TABLES = SchemaDriftDetector.SYSTEM_TABLES

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def check(self, expectations: list[AclExpectation]) -> DriftReport:
        """Compare every expectation against the live ACL state.

        Returns a :class:`DriftReport` with the originating database name
        baked in and one :class:`DriftItem` per ``(schema, table, role,
        priv)`` gap.  ``report.has_drift is False`` means the live ACLs
        match the spec.

        The shape matches :meth:`SchemaDriftDetector.compare_with_schema_file`
        so library consumers can compose both detectors uniformly — see
        :meth:`DriftReport` for the available helpers.
        """
        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="acls",
        )
        for expectation in expectations:
            tables = self._discover_tables(
                expectation.schema_, expectation.apply_to, expectation.ignore
            )
            for table in tables:
                report.tables_checked += 1
                for grant in expectation.grants:
                    missing = self._check_missing(expectation.schema_, table, grant)
                    if missing is not None:
                        report.drift_items.append(missing)
                    extras = self._check_extra(expectation.schema_, table, grant)
                    if extras is not None:
                        report.drift_items.append(extras)
        return report

    def _get_database_name(self) -> str:
        """Return the current database name for inclusion in the report."""
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    # ------------------------------------------------------------------ #
    # Table discovery                                                    #
    # ------------------------------------------------------------------ #

    # relkind values that count as "a table whose grants we care about":
    #   ``r`` — regular base tables.
    #   ``p`` — partitioned parents (relkind='p').  Grants here propagate
    #          to children automatically, so we MUST include parents in
    #          discovery or we'd silently miss their coverage gaps.
    # Excluded: ``v`` (view), ``m`` (materialized view), ``f`` (foreign),
    # ``i``/``I`` (indexes), ``t`` (TOAST), ``S`` (sequence).
    _INCLUDED_RELKINDS = ("r", "p")

    def _discover_tables(
        self,
        schema: str,
        apply_to: str | list[str],
        ignore: list[str],
    ) -> list[str]:
        """Return base-table relnames in *schema* matching *apply_to*, less *ignore*.

        Includes regular tables (``relkind = 'r'``) and partitioned parents
        (``relkind = 'p'``).  Partition *children* (``relispartition = true``)
        are excluded — grants on the parent propagate, and listing the child
        as a separate target would spuriously surface ``EXTRA_GRANT`` items
        for the inherited privileges.  Glob filtering happens in Python
        via :mod:`fnmatch`; the SQL side only constrains the schema.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind = ANY(%s)
                  AND c.relispartition = false
                ORDER BY c.relname
                """,
                (schema, list(self._INCLUDED_RELKINDS)),
            )
            relnames = [row[0] for row in cur.fetchall()]

        # Drop confiture's own tracking tables.
        relnames = [r for r in relnames if r not in self.SYSTEM_TABLES]

        # Apply pattern filter unless "ALL_TABLES".
        if apply_to != "ALL_TABLES":
            patterns = list(apply_to)
            relnames = [r for r in relnames if any(fnmatch.fnmatchcase(r, p) for p in patterns)]

        # Drop tables matching any ignore glob.
        if ignore:
            relnames = [r for r in relnames if not any(fnmatch.fnmatchcase(r, p) for p in ignore)]

        return relnames

    # ------------------------------------------------------------------ #
    # MISSING_GRANT — hypothesis check via has_table_privilege            #
    # ------------------------------------------------------------------ #

    def _check_missing(
        self,
        schema: str,
        table: str,
        grant: AclGrant,
    ) -> DriftItem | None:
        """Return a single ``MISSING_GRANT`` item if *role* lacks any expected priv.

        Uses ``has_table_privilege`` because it transparently handles
        ``PUBLIC``, role-membership inheritance, and ownership — those
        confer privileges that ``information_schema.role_table_grants``
        does not enumerate, so checking the direct-grants view here
        would produce false positives for any role that inherits a
        privilege.

        Identifiers are quoted via :class:`psycopg.sql.Identifier` and
        passed as a *text literal* that ``::regclass`` resolves, so
        mixed-case tables created with ``CREATE TABLE "MyTable" …`` are
        looked up without case-folding.  Inlining the qualified name as
        bare SQL (``"schema"."table"::regclass``) would be parsed as a
        column reference (``column "table" of table "schema"``) and
        fail with ``missing FROM-clause entry`` — the text-cast form
        avoids that pitfall entirely.
        """
        # SQL-side qualifier needs the double-quoted form so mixed-case
        # relnames survive regclass lookup; the human-friendly object_name
        # used in DriftItem stays unquoted for display consistency with
        # OwnershipDriftDetector and the existing structural diff items.
        qualified_sql = f'"{schema}"."{table}"'
        display_name = f"{schema}.{table}"
        # ``has_table_privilege(role, table_oid, priv)`` takes a regclass.
        # Pass the qualified name as a TEXT parameter to ``::regclass``
        # so PostgreSQL resolves it through the regclass input function
        # rather than parsing it as a column reference.
        priv_query = "SELECT has_table_privilege(%s, %s::regclass, %s)"

        missing: list[str] = []
        for priv in grant.privileges:
            with self.connection.cursor() as cur:
                try:
                    cur.execute(priv_query, (grant.role, qualified_sql, priv))
                    row = cur.fetchone()
                except (
                    psycopg.errors.UndefinedObject,
                    psycopg.errors.UndefinedTable,
                ) as e:
                    # Role or table doesn't exist.  Treat as informational
                    # warning (role-not-present is itself a finding worth
                    # reporting, but it isn't a CRITICAL coverage gap).
                    self.connection.rollback()
                    cause = str(e)
                    # When the missing object looks like the table itself
                    # (i.e. an unquoted lookup of a quoted relname),
                    # surface that explicitly so the operator can fix it
                    # rather than chasing the role.
                    if "does not exist" in cause and table.lower() != table:
                        hint = (
                            " (mixed-case identifier — check that the live "
                            "table name in pg_class matches the spec exactly)"
                        )
                    else:
                        hint = ""
                    return DriftItem(
                        drift_type=DriftType.MISSING_GRANT,
                        severity=DriftSeverity.WARNING,
                        object_name=f"{display_name}({grant.role})",
                        subject=DriftSubject(schema, table, role=grant.role),
                        expected=", ".join(grant.privileges),
                        actual=None,
                        message=(
                            f"Cannot verify grants for role '{grant.role}' "
                            f"on '{display_name}': {cause}{hint}"
                        ),
                    )
                if row is not None and row[0] is False:
                    missing.append(priv)
        if not missing:
            return None
        return DriftItem(
            drift_type=DriftType.MISSING_GRANT,
            severity=DriftSeverity.CRITICAL,
            object_name=f"{display_name}({grant.role})",
            subject=DriftSubject(schema, table, role=grant.role),
            expected=", ".join(grant.privileges),
            actual=None,
            message=(
                f"Role '{grant.role}' is missing grant(s) {', '.join(missing)} on '{display_name}'"
            ),
        )

    # ------------------------------------------------------------------ #
    # EXTRA_GRANT — enumeration via information_schema.role_table_grants  #
    # ------------------------------------------------------------------ #

    def _check_extra(
        self,
        schema: str,
        table: str,
        grant: AclGrant,
    ) -> DriftItem | None:
        """Return an ``EXTRA_GRANT`` item if *role* directly holds privileges beyond expected.

        Enumeration via ``information_schema.role_table_grants`` lists
        only *directly granted* privileges; ``PUBLIC`` and ownership
        rules are not in that view by design, so privileges held
        indirectly do not surface as extras (matches operator intent —
        you can't revoke what you didn't grant).
        """
        qualified = f"{schema}.{table}"
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = %s
                  AND table_schema = %s
                  AND table_name = %s
                """,
                (grant.role, schema, table),
            )
            actual = {row[0].upper() for row in cur.fetchall()}

        expected = set(grant.privileges)
        extras = sorted(actual - expected)
        if not extras:
            return None
        return DriftItem(
            drift_type=DriftType.EXTRA_GRANT,
            severity=DriftSeverity.WARNING,
            object_name=f"{qualified}({grant.role})",
            subject=DriftSubject(schema, table, role=grant.role),
            expected=", ".join(sorted(expected)) or "(none)",
            actual=", ".join(extras),
            message=(
                f"Role '{grant.role}' has unexpected grant(s) {', '.join(extras)} on '{qualified}'"
            ),
        )


class OwnershipDriftDetector:
    """Detect ownership drift between ``pg_class.relowner`` and the ``ownership:`` config.

    Issue #124 — the ownership axis of the same drift class that
    :class:`AclDriftDetector` covers on the ACL axis.

    Discovery query is a single SELECT against ``pg_class`` filtered by
    schema and ``relkind``.  Partition children (``relispartition =
    true``) are NOT excluded — Postgres allows each partition to have a
    distinct owner, and a drifted child is exactly the kind of mistake
    this detector exists to catch.  The ``ignore:`` glob list is
    evaluated Python-side after the query so the SQL stays simple and
    the cross-schema globs (``*.legacy_audit_log``) work uniformly.

    System tables (``tb_confiture`` etc.) are excluded via the same
    :pyattr:`SchemaDriftDetector.SYSTEM_TABLES` set.

    Example::

        from confiture.config.environment import Environment
        from confiture.core.drift import OwnershipDriftDetector

        env = Environment.load("production")
        with psycopg.connect(env.database_url) as conn:
            report = OwnershipDriftDetector(conn).check(env.ownership)
            if report.has_critical_drift:
                raise SystemExit(1)
    """

    SYSTEM_TABLES = SchemaDriftDetector.SYSTEM_TABLES

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def check(self, expectation: OwnershipExpectation) -> DriftReport:
        """Compare every reachable relation against the expected owner.

        Returns a :class:`DriftReport` with one :class:`DriftItem` per
        relation whose actual owner differs from ``expected_owner``.
        ``report.has_drift is False`` means every in-scope relation has
        the canonical owner.
        """
        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="ownership",
        )
        for apply_entry in expectation.apply_to:
            relations = self._discover_relations(
                apply_entry.schema_, apply_entry.relkinds, expectation.ignore
            )
            for schema, relname, _relkind, actual_owner in relations:
                report.tables_checked += 1
                if actual_owner != expectation.owner_identity:
                    qualified = f"{schema}.{relname}"
                    report.drift_items.append(
                        DriftItem(
                            drift_type=DriftType.WRONG_OWNER,
                            severity=DriftSeverity.CRITICAL,
                            object_name=qualified,
                            subject=DriftSubject(schema, relname),
                            expected=expectation.expected_owner,
                            actual=actual_owner,
                            message=(
                                f"Relation '{qualified}' is owned by "
                                f"'{actual_owner}' but expected owner is "
                                f"'{expectation.expected_owner}'"
                            ),
                        )
                    )
        return report

    def _get_database_name(self) -> str:
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    def _discover_relations(
        self,
        schema: str,
        relkinds: list[str],
        ignore_patterns: list[str],
    ) -> list[tuple[str, str, str, str]]:
        """Return ``(schema, relname, relkind, owner)`` tuples in scope.

        Filters out system tables and any qualified name matching an
        ``ignore`` glob.  Ignore patterns may be either ``schema.name``
        or a glob form like ``*.audit_log`` evaluated against the
        ``schema.relname`` qualified form.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname,
                       c.relname,
                       c.relkind,
                       pg_get_userbyid(c.relowner) AS owner
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind = ANY(%s)
                ORDER BY n.nspname, c.relname
                """,
                (schema, list(relkinds)),
            )
            rows: list[tuple[str, str, str, str]] = [
                (row[0], row[1], row[2], row[3]) for row in cur.fetchall()
            ]

        rows = [r for r in rows if r[1] not in self.SYSTEM_TABLES]

        if ignore_patterns:
            rows = [r for r in rows if not _matches_any_glob(f"{r[0]}.{r[1]}", ignore_patterns)]

        return rows


def _matches_any_glob(qualified_name: str, patterns: list[str]) -> bool:
    """Return ``True`` iff *qualified_name* matches any *patterns* glob.

    Patterns may be either literal ``schema.name`` or a glob form like
    ``*.audit_log`` or ``tenant.*_legacy``.  Uses :mod:`fnmatch`'s
    case-sensitive ``fnmatchcase`` to mirror :class:`AclDriftDetector`.
    """
    return any(fnmatch.fnmatchcase(qualified_name, p) for p in patterns)
