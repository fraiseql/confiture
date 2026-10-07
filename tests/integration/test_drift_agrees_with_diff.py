"""Drift and ``migrate diff --from db`` say the same thing about a database.

``confiture drift`` asks *what is wrong with this database*, and ``diff(database,
tree)`` *what would make it the tree*: one question, asked of one comparison. So for
every perturbation of a database built from its own tree, each drift item is about
an object the diff changes, and each change the diff makes is about an object drift
reports — unless the change is of a kind drift has no item for, which
``drift.DRIFT_OF`` names with its reason.

The perturbations are the live-drift corpus' mutation table
(``test_live_drift_identity.MUTATIONS``) and the shapes beside it that one
comparison and not the other used to see: a primary key, a foreign key's action, a
default's value, an index's keys.
"""

from pathlib import Path

import psycopg
import pytest
from test_live_drift_identity import MUTATIONS, corpus_sql

from confiture import platform
from confiture.core.drift import DRIFT_OF, DriftItem, DriftType, SchemaDriftDetector
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnOrderChanged,
    ColumnTypeChanged,
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
    TableAdded,
    TableDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)

#: ``(family, schema, relation, name)``: the object a finding or a change is about.
Key = tuple[str, str, str | None, str | None]

#: What a drift type is a finding on.
_DRIFT_FAMILY: dict[DriftType, str] = {
    DriftType.MISSING_TABLE: "table",
    DriftType.EXTRA_TABLE: "table",
    DriftType.MISSING_COLUMN: "column",
    DriftType.EXTRA_COLUMN: "column",
    DriftType.TYPE_MISMATCH: "column",
    DriftType.NULLABLE_MISMATCH: "column",
    DriftType.DEFAULT_MISMATCH: "column",
    DriftType.COLUMN_ORDER_MISMATCH: "order",
    DriftType.MISSING_INDEX: "index",
    DriftType.EXTRA_INDEX: "index",
    DriftType.MISSING_CONSTRAINT: "constraint",
    DriftType.EXTRA_CONSTRAINT: "constraint",
    DriftType.CONSTRAINT_MISMATCH: "constraint",
    DriftType.MISSING_VIEW: "object",
    DriftType.EXTRA_VIEW: "object",
    DriftType.MISSING_MATVIEW: "object",
    DriftType.EXTRA_MATVIEW: "object",
    DriftType.MISSING_TRIGGER: "object",
    DriftType.EXTRA_TRIGGER: "object",
    DriftType.MISSING_ROUTINE: "object",
    DriftType.EXTRA_ROUTINE: "object",
    DriftType.MISSING_TVIEW: "object",
    DriftType.EXTRA_TVIEW: "object",
    DriftType.TVIEW_OPTION_MISMATCH: "object",
}

_CONSTRAINT_CHANGES = (
    ForeignKeyAdded,
    ForeignKeyDropped,
    CheckConstraintAdded,
    CheckConstraintDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
    ExclusionConstraintAdded,
    ExclusionConstraintDropped,
    PrimaryKeyAdded,
    PrimaryKeyDropped,
)
_COLUMN_CHANGES = (
    ColumnAdded,
    ColumnDropped,
    ColumnTypeChanged,
    ColumnNullabilityChanged,
    ColumnDefaultChanged,
)


def _drift_key(item: DriftItem) -> Key:
    subject = item.subject
    assert subject is not None, item
    family = _DRIFT_FAMILY[item.drift_type]
    if family == "object":
        if item.drift_type in {DriftType.MISSING_ROUTINE, DriftType.EXTRA_ROUTINE}:
            return (family, subject.schema, None, subject.name)
        if item.drift_type in {DriftType.MISSING_TRIGGER, DriftType.EXTRA_TRIGGER}:
            return (family, subject.schema, None, f"{subject.relation}.{subject.name}")
        return (family, subject.schema, None, subject.relation)
    if family in {"table", "order"}:
        return (family, subject.schema, subject.relation, None)
    return (family, subject.schema, subject.relation, subject.name or None)


def _change_key(change: SchemaChange) -> Key | None:
    """The object *change* is about, or ``None`` for a kind drift has no item for."""
    if isinstance(DRIFT_OF[type(change)], str):
        return None
    if isinstance(change, ColumnOrderChanged):
        return ("order", *change.table.identity, None)
    if isinstance(change, TableAdded | TableDropped):
        return ("table", *change.table.relation.identity, None)
    if isinstance(change, _COLUMN_CHANGES):
        column = change.column if isinstance(change, ColumnAdded | ColumnDropped) else None
        name = column.folded if column is not None else _column_name(change)
        return ("column", *change.table.identity, name)
    if isinstance(change, IndexAdded | IndexDropped):
        return ("index", *change.table.identity, change.index.name or None)
    if isinstance(change, _CONSTRAINT_CHANGES):
        return ("constraint", *change.table.identity, change.constraint.name or None)
    if isinstance(change, ObjectAdded | ObjectDropped | ObjectReplaced):
        return ("object", change.ref.schema, None, change.ref.name)
    raise AssertionError(f"no key for {change!r}")


def _column_name(change: SchemaChange) -> str:
    if isinstance(change, ColumnTypeChanged):
        return change.old.folded
    assert isinstance(change, ColumnNullabilityChanged | ColumnDefaultChanged)
    return change.column


@pytest.fixture
def built(fresh_database: str, tmp_path: Path) -> tuple[str, Path]:
    sql = corpus_sql()
    apply_sql_via_psql(fresh_database, sql=sql)
    schema_file = tmp_path / "schema_corpus.sql"
    schema_file.write_text(sql, encoding="utf-8")
    return fresh_database, schema_file


def _disagreement(url: str, schema_file: Path) -> tuple[set[Key], set[Key], set[str]]:
    """What drift reports that the diff does not change, the other way round, and drift's types."""
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))
    found = {_drift_key(item) for item in report.drift_items}
    changes = platform.diff(url, schema_file).changes
    changed = {key for change in changes if (key := _change_key(change)) is not None}
    return found - changed, changed - found, {item.drift_type.value for item in report.drift_items}


#: The shapes beside the mutation table: ``(mutation SQL, drift type)``.
MORE = [
    pytest.param("ALTER TABLE core.tb_other ADD COLUMN note TEXT", "extra_column", id="add-column"),
    pytest.param(
        "CREATE INDEX ix_other_label ON core.tb_other (label)", "extra_index", id="add-index"
    ),
    pytest.param(
        "ALTER TABLE core.tb_other DROP CONSTRAINT tb_other_pkey",
        "missing_constraint",
        id="drop-primary-key",
    ),
    pytest.param(
        "ALTER TABLE core.tb_other DROP CONSTRAINT uq_other_label, "
        "ADD CONSTRAINT uq_other_label UNIQUE (id, label)",
        "constraint_mismatch",
        id="unique-gains-a-column",
    ),
    pytest.param(
        "ALTER TABLE core.tb_other DROP CONSTRAINT uq_other_label, "
        "ADD CONSTRAINT uq_other_label UNIQUE NULLS NOT DISTINCT (label)",
        "constraint_mismatch",
        id="unique-gains-nulls-not-distinct",
    ),
    pytest.param(
        "DROP INDEX core.ix_widget_serial; "
        "CREATE INDEX ix_widget_serial ON core.tb_widget (serial) NULLS NOT DISTINCT",
        "missing_index",
        id="index-gains-nulls-not-distinct",
    ),
    pytest.param(
        "ALTER TABLE core.tb_widget DROP COLUMN maybe_null, ADD COLUMN maybe_null TEXT NOT NULL",
        "column_order_mismatch",
        id="column-order",
    ),
    pytest.param(
        "CREATE TRIGGER trg_handmade BEFORE INSERT ON core.tb_widget "
        "FOR EACH ROW EXECUTE FUNCTION core.fn_touch()",
        "extra_trigger",
        id="extra-trigger",
    ),
]


def test_a_pristine_database_is_no_drift_and_no_change(built: tuple[str, Path]) -> None:
    assert _disagreement(*built) == (set(), set(), set())


@pytest.mark.parametrize(
    ("mutation", "drift_type"),
    [pytest.param(p.values[0], p.values[1], id=p.id) for p in MUTATIONS] + MORE,
)
def test_drift_and_diff_are_about_the_same_objects(
    built: tuple[str, Path], mutation: str, drift_type: str
) -> None:
    url, schema_file = built
    apply_sql_via_psql(url, sql=mutation)
    drift_only, diff_only, reported = _disagreement(url, schema_file)
    assert drift_type in reported, f"{mutation}: drift reported {reported}"
    assert (drift_only, diff_only) == (set(), set()), (
        f"{mutation} ({drift_type})\n  drift only: {drift_only}\n  diff only:  {diff_only}"
    )
