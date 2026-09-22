"""Schema drift detection for Confiture.

Compares live database schema against expected state from migrations
to detect unauthorized changes or migration mishaps.
"""

import fnmatch
import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, get_args

import pglast
import psycopg

from confiture.core import live_catalog
from confiture.core.ddl_objects import declared_triggers, objects_in
from confiture.core.ddl_walk import canonical_default
from confiture.core.desired_state import load_desired_state
from confiture.core.linting.inventory import Inventory, schema_model
from confiture.core.locking import LOCK_HOLDER_TABLE
from confiture.core.schema_analyzer import SchemaAnalyzer
from confiture.core.schema_model import (
    SERIAL_TYPES,
    Column,
    Constraint,
    Index,
    ObjectRef,
    RoutineKind,
    SchemaModel,
    Signature,
    Table,
    identity_of,
    ref_for,
    routine_ref,
    trigger_ref,
)
from confiture.core.type_lattice import same_type, signatures_match
from confiture.exceptions import ConfigurationError, SchemaError

if TYPE_CHECKING:
    from confiture.config.environment import AclExpectation, AclGrant, OwnershipExpectation


from pathlib import Path

from pydantic import ValidationError

from confiture.config.environment import DriftConfig
from confiture.core.linting.inventory import build_inventory
from confiture.core.parser_info import parse_error_line

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
    MISSING_VIEW = "missing_view"
    EXTRA_VIEW = "extra_view"
    MISSING_MATVIEW = "missing_matview"
    EXTRA_MATVIEW = "extra_matview"
    MISSING_TRIGGER = "missing_trigger"
    EXTRA_TRIGGER = "extra_trigger"
    MISSING_ROUTINE = "missing_routine"
    EXTRA_ROUTINE = "extra_routine"
    MISSING_GRANT = "missing_grant"
    EXTRA_GRANT = "extra_grant"
    WRONG_OWNER = "wrong_owner"


class DriftSeverity(Enum):
    """Severity of drift."""

    CRITICAL = "critical"  # Missing table/column
    WARNING = "warning"  # Extra objects, type changes
    INFO = "info"  # Minor differences


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
    #: Views, matviews, triggers and routines compared — the objects a tree
    #: declares whose *existence* is now checked (#303).
    objects_checked: int = 0
    detection_time_ms: int = 0

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
        return {
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
            "objects_checked": self.objects_checked,
            "detection_time_ms": self.detection_time_ms,
            "drift_items": [d.to_dict() for d in self.drift_items],
        }


#: Which pair of drift types reports a kind's existence: every kind the schema
#: model holds beside a table. A function, a procedure and an aggregate share one
#: pair: the object's own name says which it is, and three more members of a
#: published enum would say nothing new.
_OBJECT_DRIFT_TYPES: dict[str, tuple[DriftType, DriftType]] = {
    "view": (DriftType.MISSING_VIEW, DriftType.EXTRA_VIEW),
    "matview": (DriftType.MISSING_MATVIEW, DriftType.EXTRA_MATVIEW),
    "trigger": (DriftType.MISSING_TRIGGER, DriftType.EXTRA_TRIGGER),
    **dict.fromkeys(get_args(RoutineKind), (DriftType.MISSING_ROUTINE, DriftType.EXTRA_ROUTINE)),
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


def _objects(model: SchemaModel) -> list[_Object]:
    found = [
        _Object(ref, None, view.qualified, f"{view.schema}.{view.name}")
        for ref, view in model.views.items()
    ]
    found += [
        _Object(
            ref,
            routine.signature_key,
            routine.identity,
            f"{routine.schema}.{routine.name}"
            f"({', '.join(name for _schema, name in routine.signature_key)})",
        )
        for ref, overloads in model.routines.items()
        for routine in overloads
    ]
    found += [
        _Object(ref, None, trigger.qualified, f"{trigger.schema}.{trigger.table}.{trigger.name}")
        for ref, trigger in model.triggers.items()
    ]
    return found


def _order(obj: _Object) -> str:
    return str((obj.ref.kind, obj.ref.schema, obj.ref.name.lower(), obj.ref.signature))


def _compare_objects(expected: SchemaModel, actual: SchemaModel) -> list[DriftItem]:
    """Views, matviews, triggers and routines: what the tree declares against what exists.

    Paired by :class:`ObjectRef` and, inside a routine's bucket, by
    ``signatures_match`` — so ``fn(bigint)`` in a tree and ``fn(int8)`` in a
    database are one routine, and ``app.f(app.t)`` / ``app.f(other.t)`` two.

    A **missing** object is CRITICAL, by analogy with ``missing_column``: the DDL
    declares it and the database has not got it, which is what a deploy gate is
    for. An **extra** object is INFO, and only for a kind the tree declares at
    least one of, in a schema it declares one in — because "this project does not
    manage views here" and "this project has lost all its views" are
    indistinguishable from an empty expected set, and a live database
    legitimately carries objects no DDL tree declares.
    """
    declared = _objects(expected)
    unclaimed: dict[ObjectRef, list[_Object]] = defaultdict(list)
    for obj in _objects(actual):
        unclaimed[obj.ref].append(obj)

    missing: list[_Object] = []
    for obj in declared:
        candidates = unclaimed.get(obj.ref, [])
        twin = next((c for c in candidates if signatures_match(obj.signature, c.signature)), None)
        if twin is None:
            missing.append(obj)
        else:
            candidates.remove(twin)

    declared_kinds = {obj.ref.kind for obj in declared}
    declared_schemas = {obj.ref.schema for obj in declared}
    extra = [
        obj
        for found in unclaimed.values()
        for obj in found
        if obj.ref.kind in declared_kinds and obj.ref.schema in declared_schemas
    ]

    items = [
        DriftItem(
            drift_type=_OBJECT_DRIFT_TYPES[obj.ref.kind][0],
            severity=DriftSeverity.CRITICAL,
            object_name=obj.written,
            expected=obj.written,
            actual=None,
            message=f"{obj.ref.kind.capitalize()} '{obj.written}' is missing from database",
        )
        for obj in sorted(missing, key=_order)
    ]
    items += [
        DriftItem(
            drift_type=_OBJECT_DRIFT_TYPES[obj.ref.kind][1],
            severity=DriftSeverity.INFO,
            object_name=obj.catalogued,
            expected=None,
            actual=obj.catalogued,
            message=(
                f"{obj.ref.kind.capitalize()} '{obj.catalogued}' exists but is not in expected schema"
            ),
        )
        for obj in sorted(extra, key=_order)
    ]
    return items


DEFAULT_SCHEMA = "public"


@dataclass
class ExpectedSchema:
    """What a schema file declares: the schema model and the schemas it names."""

    model: SchemaModel
    schemas: frozenset[str]


def _inherit_partition_columns(inventory: Inventory) -> None:
    """A ``PARTITION OF`` child declares no columns: it has its parent's."""
    for table in inventory.tables:
        if table.parent and not table.columns:
            parent_schema, _, parent_name = table.parent.rpartition(".")
            parent = inventory.find(parent_schema or None, parent_name)
            if parent is not None:
                table.columns = list(parent.columns)


def _in_schema(model: SchemaModel, default_schema: str) -> SchemaModel:
    """*model* with every unqualified object placed in *default_schema* (#227).

    A view, routine or trigger is *keyed* in *default_schema* and keeps the
    spelling the tree wrote, which is how a finding names one that is missing.
    """

    def placed(obj: Any) -> Any:
        return replace(obj, schema=obj.schema or default_schema)

    return SchemaModel(
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
    )


def parse_expected_schema(sql: str, default_schema: str = DEFAULT_SCHEMA) -> ExpectedSchema:
    """Read the expected schema out of DDL into the schema model (#227).

    The lint inventory reads the tree — every column, constraint and index, wherever
    it was written — and an unqualified object belongs to ``default_schema``. A
    ``PARTITION OF`` child inherits its parent's columns when the parent is in the
    same DDL. ``CREATE SCHEMA`` declares a schema and no table.

    Raises:
        SchemaError: ``SCHEMA_202`` when pglast rejects the DDL — a parser
            failure surfaced loudly rather than as an empty expectation that
            would report every live table as spurious drift.
    """
    try:
        raws = list(pglast.parse_sql(sql) or [])
        inventory = build_inventory(sql, raws)
        objects = objects_in(sql, raws)
    except pglast.parser.ParseError as exc:
        raise SchemaError(
            f"The expected schema could not be parsed (line {parse_error_line(sql, exc)}): {exc}. "
            "Comparing against it would report every live table as spurious drift.",
            error_code="SCHEMA_202",
            resolution_hint="Fix the SQL syntax in the schema file, or regenerate it with `confiture build`.",
        ) from exc

    _inherit_partition_columns(inventory)
    triggers = {trigger_ref(t): t for t in declared_triggers(objects)}
    model = _in_schema(replace(schema_model(inventory), triggers=triggers), default_schema)
    schemas = {default_schema} | {t.schema for t in model.tables.values() if t.schema}
    schemas |= {declared.name for declared in inventory.schemas}
    return ExpectedSchema(model=model, schemas=frozenset(schemas))


#: How a finding names a constraint the DDL left unnamed.
_CONSTRAINT_KEYWORDS = {
    "primary_key": "PRIMARY KEY",
    "unique": "UNIQUE",
    "check": "CHECK",
    "foreign_key": "FOREIGN KEY",
}


def _named(table: Table) -> str:
    """``schema.table``: how a finding names a table."""
    return f"{table.schema or DEFAULT_SCHEMA}.{table.name}"


def _column_facts(column: Column) -> dict[str, Any]:
    """A column as a finding reports it — the shape ``expected`` / ``actual`` always had."""
    return {"type": column.type_text, "nullable": not column.not_null, "default": column.default}


def _comparable_defaults(exp: Column, act: Column) -> tuple[str | None, str | None]:
    """Both defaults as they are compared, or ``(None, None)`` where no default is.

    Compared as parse trees through ``ddl_walk.canonical_default``, never as text:
    PostgreSQL stores a default analysed (``'x'`` as ``'x'::text``). An identity or a
    generated column has no default, and a ``serial``'s ``nextval`` is its own.
    """
    if exp.identity or act.identity or exp.generated or act.generated:
        return None, None
    if (exp.raw_sql_type or "").upper() in SERIAL_TYPES:
        return None, None
    column_type = act.type_text or exp.type_text
    try:
        return (
            canonical_default(exp.default, column_type),
            canonical_default(act.default, column_type),
        )
    except pglast.parser.ParseError:
        return exp.default, act.default


def _index_keys(index: Index) -> tuple[str | None, ...]:
    return tuple(
        key if key.replace("_", "").isalnum() else canonical_default(key, None)
        for key in index.columns
    )


def _same_index(expected: Index, live: Index) -> bool:
    """Whether an index the DDL left unnamed is *live*, whatever PostgreSQL named it."""
    return (expected.unique, expected.method, _index_keys(expected)) == (
        live.unique,
        live.method,
        _index_keys(live),
    )


def _index_label(index: Index) -> str:
    return f"({', '.join(index.columns)})"


def _same_constraint(expected: Constraint, live: Constraint) -> bool:
    """Whether *live* is the constraint *expected* declares.

    By name when the DDL wrote one; otherwise by what it says — its columns and, for
    a foreign key, what it references (``REFERENCES p`` with no column list means the
    referenced key, which the catalog always spells out). An unnamed CHECK matches any
    live CHECK still unclaimed: its text is stored analysed and cannot be compared.
    """
    if expected.kind != live.kind:
        return False
    if expected.name:
        return expected.name == live.name
    if expected.kind == "check":
        return True
    return (
        expected.columns == live.columns
        and identity_of(expected.ref_table) == identity_of(live.ref_table)
        and (not expected.ref_columns or expected.ref_columns == live.ref_columns)
    )


def _constraint_label(constraint: Constraint) -> str:
    if constraint.name:
        return constraint.name
    keyword = _CONSTRAINT_KEYWORDS[constraint.kind]
    return f"{keyword} ({', '.join(constraint.columns)})" if constraint.columns else keyword


def drift_config_from(config_data: Any) -> "DriftConfig":
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
            resolution_hint="Allowed keys: ignore_column_order (bool), column_order_severity (warning|critical).",
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
    SYSTEM_TABLES: ClassVar[set[str]] = {
        "tb_confiture",
        "tb_confiture_steps",
        LOCK_HOLDER_TABLE,
        "confiture_version",
        "confiture_audit_log",
    }

    def __init__(
        self,
        connection: psycopg.Connection,
        ignore_tables: list[str] | None = None,
        *,
        ignore_column_order: bool = False,
        column_order_severity: str = "warning",
    ):
        """Initialize drift detector.

        Args:
            connection: Database connection
            ignore_tables: Additional tables to ignore in drift detection
            ignore_column_order: Skip the column-order comparison (#226)
            column_order_severity: ``"warning"`` (default) or ``"critical"`` for a
                ``column_order_mismatch`` item
        """
        self.connection = connection
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
        *,
        objects: bool = False,
    ) -> DriftReport:
        """Compare two schema models: the expected one from DDL, the actual one live.

        Both are ``core/schema_model`` values — the expected side built by the lint
        inventory, the live side by ``live_catalog`` — so what differs is the schema,
        not two representations of it.

        Args:
            expected: Expected schema state
            actual: Actual (live) schema state
            objects: Also compare the views, matviews, triggers and routines both
                models hold (#303). Off unless *actual* read them: silence from a
                kind nobody asked the catalogue about is not evidence of absence.

        Returns:
            DriftReport with differences
        """
        start_time = time.perf_counter()

        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="provided",
        )

        expected_tables = {
            key: table
            for table in expected.tables.values()
            if not self._ignored(key := _named(table))
        }
        actual_tables = {
            key: table
            for table in actual.tables.values()
            if not self._ignored(key := _named(table))
        }

        for table in sorted(expected_tables.keys() - actual_tables.keys()):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    severity=DriftSeverity.CRITICAL,
                    object_name=table,
                    expected=table,
                    actual=None,
                    message=f"Table '{table}' is missing from database",
                )
            )

        for table in sorted(actual_tables.keys() - expected_tables.keys()):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_TABLE,
                    severity=DriftSeverity.WARNING,
                    object_name=table,
                    expected=None,
                    actual=table,
                    message=f"Table '{table}' exists but is not in expected schema",
                )
            )

        for table in sorted(expected_tables.keys() & actual_tables.keys()):
            report.tables_checked += 1
            self._compare_table_columns(table, expected_tables[table], actual_tables[table], report)
            self._compare_indexes(table, expected_tables[table], actual_tables[table], report)
            self._compare_constraints(table, expected_tables[table], actual_tables[table], report)

        # Compare object existence: a view, matview, trigger or routine the tree
        # declares and the database has not got was exit 0 before this (#303).
        if objects:
            report.drift_items.extend(_compare_objects(expected, actual))
            report.objects_checked = (
                len(expected.views) + len(expected.routines) + len(expected.triggers)
            )

        report.detection_time_ms = int((time.perf_counter() - start_time) * 1000)
        return report

    def _compare_table_columns(
        self,
        table_name: str,
        expected_table: Table,
        actual_table: Table,
        report: DriftReport,
    ) -> None:
        """Compare the columns of one table present on both sides."""
        expected_cols = {c.folded: c for c in expected_table.columns}
        actual_cols = {c.folded: c for c in actual_table.columns}

        for col in sorted(expected_cols.keys() - actual_cols.keys()):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_COLUMN,
                    severity=DriftSeverity.CRITICAL,
                    object_name=f"{table_name}.{col}",
                    expected=_column_facts(expected_cols[col]),
                    actual=None,
                    message=f"Column '{table_name}.{col}' is missing",
                )
            )

        for col in sorted(actual_cols.keys() - expected_cols.keys()):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_COLUMN,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table_name}.{col}",
                    expected=None,
                    actual=_column_facts(actual_cols[col]),
                    message=f"Column '{table_name}.{col}' exists but is not expected",
                )
            )

        for col in sorted(expected_cols.keys() & actual_cols.keys()):
            report.columns_checked += 1
            self._compare_column(
                f"{table_name}.{col}", expected_cols[col], actual_cols[col], report
            )

        self._compare_column_order(table_name, list(expected_cols), list(actual_cols), report)

    def _compare_column(self, name: str, exp: Column, act: Column, report: DriftReport) -> None:
        """Type, nullability and default of one column present on both sides."""
        # One canonicaliser answers for both sides: the DDL's own spelling and
        # `format_type`'s are two vocabularies for one type (#302).
        exp_type, act_type = exp.type_text or "", act.type_text or ""
        if exp_type and act_type and not same_type(exp_type, act_type):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.TYPE_MISMATCH,
                    severity=DriftSeverity.WARNING,
                    object_name=name,
                    expected=exp_type,
                    actual=act_type,
                    message=f"Column '{name}' type mismatch: expected {exp_type}, got {act_type}",
                )
            )

        if exp.not_null != act.not_null:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.NULLABLE_MISMATCH,
                    severity=DriftSeverity.WARNING,
                    object_name=name,
                    expected=f"nullable={not exp.not_null}",
                    actual=f"nullable={not act.not_null}",
                    message=f"Column '{name}' nullable mismatch: "
                    f"expected {not exp.not_null}, got {not act.not_null}",
                )
            )

        expected_default, actual_default = _comparable_defaults(exp, act)
        if expected_default != actual_default:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.DEFAULT_MISMATCH,
                    severity=DriftSeverity.WARNING,
                    object_name=name,
                    expected=exp.default,
                    actual=act.default,
                    message=f"Column '{name}' default mismatch: "
                    f"expected {exp.default}, got {act.default}",
                )
            )

    def _compare_column_order(
        self,
        table_name: str,
        expected_order: list[str],
        actual_order: list[str],
        report: DriftReport,
    ) -> None:
        """One ``column_order_mismatch`` per table whose columns are the same set in another order (#226).

        Both sides keep declaration order: the expected DDL as written, the live
        side by ``attnum``. A differing set is already reported column by column,
        so only equal sets are compared.
        """
        if self.ignore_column_order:
            return
        if set(expected_order) != set(actual_order) or expected_order == actual_order:
            return
        report.drift_items.append(
            DriftItem(
                drift_type=DriftType.COLUMN_ORDER_MISMATCH,
                severity=self.column_order_severity,
                object_name=table_name,
                expected=", ".join(expected_order),
                actual=", ".join(actual_order),
                message=(
                    f"Columns of '{table_name}' are in a different order: expected "
                    f"({', '.join(expected_order)}), got ({', '.join(actual_order)})"
                ),
                details={"expected_order": expected_order, "actual_order": actual_order},
            )
        )

    def _compare_indexes(
        self, table: str, expected: Table, actual: Table, report: DriftReport
    ) -> None:
        """Compare one table's declared indexes with its live ones.

        A live index that backs a constraint is PostgreSQL's, not the DDL's: it is
        never *extra*. It still matches a declared index by name, so ``UNIQUE USING
        INDEX`` reports nothing. An index the DDL left unnamed matches a live index
        with the same keys, uniqueness and method, whatever PostgreSQL named it.
        """
        act_by_name = {ix.name: ix for ix in actual.indexes if ix.name}
        exp_named = {ix.name for ix in expected.indexes if ix.name}
        matched = set(exp_named & act_by_name.keys())
        unnamed_missing: list[Index] = []
        for ix in expected.indexes:
            if ix.name:
                continue
            twin = next(
                (
                    live
                    for live in actual.indexes
                    if live.name not in matched and _same_index(ix, live)
                ),
                None,
            )
            if twin is None:
                unnamed_missing.append(ix)
            else:
                matched.add(twin.name)
        backing = {ix.name for ix in actual.indexes if ix.backs_constraint}
        extra = sorted(act_by_name.keys() - backing - matched)
        missing = sorted(exp_named - act_by_name.keys())
        report.indexes_checked += len(expected.indexes) + len(extra)

        for idx in [*missing, *(_index_label(ix) for ix in unnamed_missing)]:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_INDEX,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table}.{idx}",
                    expected=idx,
                    actual=None,
                    message=f"Index '{idx}' on '{table}' is missing",
                )
            )
        for idx in extra:
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_INDEX,
                    severity=DriftSeverity.INFO,
                    object_name=f"{table}.{idx}",
                    expected=None,
                    actual=idx,
                    message=f"Index '{idx}' on '{table}' exists but is not expected",
                )
            )

    def _compare_constraints(
        self, table: str, expected: Table, actual: Table, report: DriftReport
    ) -> None:
        """Compare one table's constraints: a constraint the tree declares and the database lost.

        Keyed by name where the DDL wrote one, and by what the constraint says where
        it did not — PostgreSQL names an unnamed constraint at apply time
        (``child_pid_fkey``), and 1.14.0's rule is that two unnamed foreign keys on one
        table are two. A CHECK's text is not compared: PostgreSQL stores it analysed.
        """
        unmatched = list(actual.constraints)
        missing: list[Constraint] = []
        for constraint in sorted(expected.constraints, key=lambda c: not c.name):
            twin = next((live for live in unmatched if _same_constraint(constraint, live)), None)
            if twin is None:
                missing.append(constraint)
            else:
                unmatched.remove(twin)

        for constraint in missing:
            label = _constraint_label(constraint)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_CONSTRAINT,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table}.{label}",
                    expected=label,
                    actual=None,
                    message=f"Constraint '{label}' on '{table}' is missing",
                )
            )
        for constraint in unmatched:
            label = _constraint_label(constraint)
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_CONSTRAINT,
                    severity=DriftSeverity.INFO,
                    object_name=f"{table}.{label}",
                    expected=None,
                    actual=label,
                    message=f"Constraint '{label}' on '{table}' exists but is not expected",
                )
            )

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

        sql = load_desired_state(schema_file_path).read()
        expected = parse_expected_schema(sql, default_schema=default_schema)
        actual = self.get_live_schema(expected.schemas, objects=True)
        report = self.compare_schemas(expected.model, actual, objects=True)
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

    def check(self, expectations: "list[AclExpectation]") -> DriftReport:
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
        apply_to: "str | list[str]",
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
        grant: "AclGrant",
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
        grant: "AclGrant",
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

    def check(self, expectation: "OwnershipExpectation") -> DriftReport:
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
                if actual_owner != expectation.expected_owner:
                    qualified = f"{schema}.{relname}"
                    report.drift_items.append(
                        DriftItem(
                            drift_type=DriftType.WRONG_OWNER,
                            severity=DriftSeverity.CRITICAL,
                            object_name=qualified,
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
