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

from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from test_live_drift_identity import MUTATIONS, corpus_sql

from confiture import platform
from confiture.core.differ import MATERIALISED, SchemaDiffer
from confiture.core.drift import (
    DRIFT_OF,
    UNRENDERED_REDEFINITIONS,
    DriftItem,
    DriftType,
    SchemaDriftDetector,
    severity_of,
)
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
from confiture.core.schema_read import read_text
from confiture.core.schema_sources import database_side, materialised_side

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
    DriftType.VIEW_DEFINITION_MISMATCH: "object",
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


def _index_severities(url: str, schema_file: Path) -> tuple[dict[Key, str], dict[Key, str]]:
    """Each index item's severity as drift reports it, and as ``DRIFT_OF`` says for its change."""
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))
    reported = {
        (_drift_key(item), item.drift_type.value): item.severity.value
        for item in report.drift_items
        if _DRIFT_FAMILY[item.drift_type] == "index"
    }
    expected = {
        (key, DRIFT_OF[type(change)][0].value): severity_of(change).value
        for change in platform.diff(url, schema_file).changes
        if isinstance(change, IndexAdded | IndexDropped)
        and (key := _change_key(change)) is not None
    }
    return reported, expected


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
    pytest.param(
        "CREATE INDEX ix_mv_widget_extra ON core.mv_widget (n)",
        "extra_index",
        id="add-matview-index",
    ),
    pytest.param(
        "DROP INDEX core.ux_mv_widget_n; CREATE UNIQUE INDEX ux_mv_widget_n "
        "ON core.mv_widget (n) WHERE n > 0",
        "missing_index",
        id="matview-unique-index-gains-a-predicate",
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
    reported, expected = _index_severities(url, schema_file)
    assert reported == expected, mutation


# The materialised tier (a scratch server reads the tree back) compares a view's
# and a matview's query, so one whose query drifted is one redefinition: drift's
# ``view_definition_mismatch`` (#719), and the index changes a matview's carries are
# drift's findings beside it. ``platform.diff`` has no scratch tier, so the diff is
# asked as ``migrate diff --from db --scratch-url`` asks it.


def _change_keys(change: SchemaChange) -> set[Key]:
    """The objects *change* is about: a redefinition's own, unless unrendered, and what it carries."""
    own = _change_key(change)
    keys = set() if own is None else {own}
    if not isinstance(change, ObjectReplaced):
        return keys
    carried = {key for found in change.index_changes if (key := _change_key(found))}
    return carried if change.ref.kind in UNRENDERED_REDEFINITIONS else carried | keys


def _flattened(changes: list[SchemaChange]) -> list[SchemaChange]:
    """*changes*, with the index changes each redefinition carries beside it."""
    return [
        found
        for change in changes
        for found in (
            [change, *change.index_changes] if isinstance(change, ObjectReplaced) else [change]
        )
    ]


def _materialised(
    url: str, schema_file: Path, scratch_url: str
) -> tuple[list[DriftItem], list[SchemaChange]]:
    """Drift and the diff from the database, both at the materialised tier."""
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn, scratch_url=scratch_url).compare_with_schema_file(
            str(schema_file)
        )
    sql = schema_file.read_text(encoding="utf-8")
    read = read_text(sql)
    database = database_side(url, against=read.model)
    built = materialised_side(sql, scratch_url, read=read)
    policy = replace(MATERIALISED, author="new")
    return report.drift_items, SchemaDiffer().compare_sides(database, built, policy).changes


def test_a_pristine_corpus_is_no_drift_and_no_change_at_the_materialised_tier(
    built: tuple[str, Path], test_db_url: str
) -> None:
    assert _materialised(*built, test_db_url) == ([], [])


_REDEFINED_MATVIEW = (
    "DROP MATERIALIZED VIEW core.mv_widget; "
    "CREATE MATERIALIZED VIEW core.mv_widget AS SELECT count(*) + 0 AS n FROM core.tb_widget; "
)

_QUERY = "view_definition_mismatch"

#: ``(mutation SQL, redefined kind, drift types)``: a view or matview redefined, with
#: what drift reports.
MATERIALISED_MORE = [
    pytest.param(
        _REDEFINED_MATVIEW,
        "matview",
        {_QUERY, "missing_index"},
        id="redefine-matview-drop-unique-index",
    ),
    pytest.param(
        _REDEFINED_MATVIEW
        + "CREATE UNIQUE INDEX ux_mv_widget_n ON core.mv_widget (n); "
        + "CREATE INDEX ix_mv_widget_extra ON core.mv_widget (n)",
        "matview",
        {_QUERY, "extra_index"},
        id="redefine-matview-add-index",
    ),
    pytest.param(
        _REDEFINED_MATVIEW + "CREATE UNIQUE INDEX ux_mv_widget_n ON core.mv_widget (n)",
        "matview",
        {_QUERY},
        id="redefine-matview-only",
    ),
    pytest.param(
        "CREATE OR REPLACE VIEW core.v_widget AS "
        "SELECT id, serial FROM core.tb_widget WHERE id > 0",
        "view",
        {_QUERY},
        id="redefine-view",
    ),
]


@pytest.mark.parametrize(("mutation", "kind", "drift_types"), MATERIALISED_MORE)
def test_drift_and_diff_agree_at_the_materialised_tier(
    built: tuple[str, Path], test_db_url: str, mutation: str, kind: str, drift_types: set[str]
) -> None:
    url, schema_file = built
    apply_sql_via_psql(url, sql=mutation)
    items, changes = _materialised(url, schema_file, test_db_url)

    assert [c.ref.kind for c in changes if isinstance(c, ObjectReplaced)] == [kind]
    assert {item.drift_type.value for item in items} == drift_types
    found = {_drift_key(item) for item in items}
    changed = set().union(*map(_change_keys, changes))
    assert (found - changed, changed - found) == (set(), set()), mutation
    reported = {
        (_drift_key(item), item.drift_type.value): item.severity.value
        for item in items
        if _DRIFT_FAMILY[item.drift_type] == "index"
    }
    expected = {
        (key, DRIFT_OF[type(change)][0].value): severity_of(change).value
        for change in _flattened(changes)
        if isinstance(change, IndexAdded | IndexDropped)
        and (key := _change_key(change)) is not None
    }
    assert reported == expected, mutation


#: A TVIEW whose user indexes drift checks as a table's (pg_tviews 0.1.0-beta.27).
TVIEW_TREE = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, title text);
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, p.title, jsonb_build_object('id', p.id, 'title', p.title) AS data
FROM tb_post p;
CREATE INDEX ix_tv_post_title ON tv_post (title);
CREATE UNIQUE INDEX ux_tv_post_title ON tv_post (title, pk_post);
"""


@pytest.fixture
def built_tview(fresh_database: str, tmp_path: Path) -> tuple[str, Path]:
    from tests.conftest import create_supported_pg_tviews

    with psycopg.connect(fresh_database, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(TVIEW_TREE)
    schema_file = tmp_path / "schema_tview.sql"
    # The extension is the tree's too, or the diff would drop it.
    schema_file.write_text("CREATE EXTENSION pg_tviews;\n" + TVIEW_TREE, encoding="utf-8")
    return fresh_database, schema_file


def test_a_pristine_tview_is_no_drift_and_no_change(built_tview: tuple[str, Path]) -> None:
    assert _disagreement(*built_tview) == (set(), set(), set())


@pytest.mark.parametrize(
    ("mutation", "drift_type"),
    [
        pytest.param("DROP INDEX ix_tv_post_title", "missing_index", id="drop-tview-index"),
        pytest.param("DROP INDEX ux_tv_post_title", "missing_index", id="drop-tview-unique-index"),
        pytest.param(
            "CREATE INDEX ix_tv_post_extra ON tv_post (id, title)",
            "extra_index",
            id="add-tview-index",
        ),
    ],
)
def test_drift_and_diff_agree_on_a_tview_s_indexes(
    built_tview: tuple[str, Path], mutation: str, drift_type: str
) -> None:
    url, schema_file = built_tview
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(mutation)
    drift_only, diff_only, reported = _disagreement(url, schema_file)
    assert drift_type in reported, f"{mutation}: drift reported {reported}"
    assert (drift_only, diff_only) == (set(), set()), mutation
    reported, expected = _index_severities(url, schema_file)
    assert reported == expected, mutation
