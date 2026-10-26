"""A materialized view's indexes are compared as a table's are (#690).

A matview holds no constraints, so its indexes are all a comparison has to say
about it besides its query. They go through the one index comparison under
every policy: an index missing, extra, changed or INVALID is the index change a
table would get, named by the matview's key. A matview that is added, dropped or
redefined carries its whole index set on its own change instead, so its indexes
are created with it and never ranked before it exists.
"""

import re
from dataclasses import replace

import pytest

from confiture.core.differ import (
    EXACT,
    MATERIALISED,
    SchemaDiffer,
    Side,
    slot_side,
    stated_side,
)
from confiture.core.drift import DriftReport, DriftSeverity, DriftType, _Findings
from confiture.core.schema_change import (
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    SchemaChange,
)
from confiture.core.schema_model import Coverage, ref_for
from confiture.core.schema_read import read_text

TABLE = "CREATE TABLE tb_item (id int PRIMARY KEY, n int);\n"
VIEW = "CREATE MATERIALIZED VIEW mv AS SELECT id, n FROM tb_item;\n"
OTHER_VIEW = "CREATE MATERIALIZED VIEW mv AS SELECT id, n + 1 AS n FROM tb_item;\n"
UNIQUE = "CREATE UNIQUE INDEX ux_mv ON mv (id);\n"
ON_N = "CREATE INDEX ix_mv ON mv (n);\n"
ON_ID = "CREATE INDEX ix_mv ON mv (id);\n"
MV = ref_for("matview", None, "mv")


def _trees(old: str, new: str) -> list[SchemaChange]:
    return SchemaDiffer().compare_sides(Side.of(read_text(old)), Side.of(read_text(new))).changes


def _database(sql: str, **index_changes: object) -> Side:
    """A database holding what *sql* declares, as ``drift`` and ``migrate diff`` read one."""
    model = read_text(sql).catalogued
    if index_changes:
        view = model.views[MV]
        indexes = tuple(replace(index, **index_changes) for index in view.indexes)
        model = replace(model, views={**model.views, MV: replace(view, indexes=indexes)})
    return stated_side(replace(model, source="catalog"))


def _tree(sql: str) -> Side:
    return Side.of(read_text(sql), held=True)


def _index_changes(changes: list[SchemaChange]) -> list[tuple[str, str | None]]:
    return [
        (type(c).__name__, c.index.name)
        for c in changes
        if isinstance(c, IndexAdded | IndexDropped)
    ]


def test_two_trees_see_a_matview_index_added() -> None:
    (change,) = _trees(TABLE + VIEW, TABLE + VIEW + UNIQUE)
    assert isinstance(change, IndexAdded)
    assert change.relation_kind == "matview"
    assert change.index.name == "ux_mv"


def test_two_trees_see_a_matview_index_dropped() -> None:
    (change,) = _trees(TABLE + VIEW + UNIQUE, TABLE + VIEW)
    assert isinstance(change, IndexDropped)
    assert change.relation_kind == "matview"
    assert change.index.name == "ux_mv"


def test_two_trees_rebuild_a_matview_index_whose_keys_change() -> None:
    changes = _trees(TABLE + VIEW + ON_N, TABLE + VIEW + ON_ID)
    assert _index_changes(changes) == [("IndexDropped", "ix_mv"), ("IndexAdded", "ix_mv")]
    assert len(changes) == 2


def test_a_redefined_matview_is_one_replace_and_no_index_change() -> None:
    for old_indexes, new_indexes in ((UNIQUE, UNIQUE), (ON_N, ON_ID + UNIQUE)):
        changes = _trees(TABLE + VIEW + old_indexes, TABLE + OTHER_VIEW + new_indexes)
        (change,) = changes
        assert isinstance(change, ObjectReplaced)
        assert [i.name for i in change.old_indexes] == [
            i.name for i in read_text(TABLE + VIEW + old_indexes).model.views[MV].indexes
        ]
        assert {i.name for i in change.new_indexes} == {
            i.name for i in read_text(TABLE + VIEW + new_indexes).model.views[MV].indexes
        }


def test_an_added_matview_carries_its_indexes() -> None:
    changes = _trees(TABLE, TABLE + VIEW + UNIQUE + ON_N)
    (change,) = [c for c in changes if isinstance(c, ObjectAdded)]
    assert [i.name for i in change.indexes] == ["ux_mv", "ix_mv"]
    assert _index_changes(changes) == []


def test_a_dropped_matview_carries_its_indexes() -> None:
    changes = _trees(TABLE + VIEW + UNIQUE, TABLE)
    (change,) = [c for c in changes if isinstance(c, ObjectDropped)]
    assert [i.name for i in change.indexes] == ["ux_mv"]
    assert _index_changes(changes) == []


def test_two_databases_see_a_matview_index_on_one_side() -> None:
    (change,) = (
        SchemaDiffer()
        .compare_sides(_database(TABLE + VIEW), _database(TABLE + VIEW + UNIQUE))
        .changes
    )
    assert isinstance(change, IndexAdded)
    assert change.relation_kind == "matview"


def test_two_databases_with_the_same_invalid_matview_index_are_no_change() -> None:
    old = _database(TABLE + VIEW + UNIQUE, valid=False)
    new = _database(TABLE + VIEW + UNIQUE, valid=False)
    assert SchemaDiffer().compare_sides(old, new).changes == []


def test_a_catalog_side_missing_a_matview_index_is_an_index_added() -> None:
    changes = (
        SchemaDiffer().compare_sides(_database(TABLE + VIEW), _tree(TABLE + VIEW + UNIQUE)).changes
    )
    assert _index_changes(changes) == [("IndexAdded", "ux_mv")]
    assert not [c for c in changes if isinstance(c, ObjectReplaced)]
    assert len(changes) == 1


def test_an_invalid_matview_index_on_a_catalog_side_is_rebuilt() -> None:
    changes = (
        SchemaDiffer()
        .compare_sides(_database(TABLE + VIEW + UNIQUE, valid=False), _tree(TABLE + VIEW + UNIQUE))
        .changes
    )
    assert _index_changes(changes) == [("IndexDropped", "ux_mv"), ("IndexAdded", "ux_mv")]
    assert len(changes) == 2


def test_an_unnamed_tree_index_takes_the_invalid_live_name() -> None:
    database = _database(TABLE + VIEW + "CREATE UNIQUE INDEX mv_id_idx ON mv (id);\n", valid=False)
    changes = (
        SchemaDiffer()
        .compare_sides(database, _tree(TABLE + VIEW + "CREATE UNIQUE INDEX ON mv (id);\n"))
        .changes
    )
    assert _index_changes(changes) == [
        ("IndexDropped", "mv_id_idx"),
        ("IndexAdded", "mv_id_idx"),
    ]


def test_a_side_that_did_not_read_views_compares_no_matview_index() -> None:
    database = _database(TABLE + VIEW)
    tables_only = Coverage.of(
        {
            section: depth
            for section, depth in database.model.coverage.sections
            if section != "views"
        }
    )
    blind = replace(database, model=replace(database.model, coverage=tables_only))
    changes = SchemaDiffer().compare_sides(blind, _tree(TABLE + VIEW + UNIQUE)).changes
    assert _index_changes(changes) == []


def _author(sql: str) -> Side:
    """A tree as drift states it: the author's side of a materialised comparison."""
    return stated_side(replace(read_text(sql).catalogued, source="author"))


def _stored(sql: str) -> Side:
    """A database holding *sql*, its views' queries as text: what ``migrate diff`` reads."""
    read = read_text(sql)
    return Side(replace(read.catalogued, source="catalog"), read.declared.objects)


def _drift(database: Side, tree: Side) -> DriftReport:
    """Drift at the materialised tier: *tree* is the author's side, *database* the catalog."""
    changes = SchemaDiffer().compare_sides(database, tree, replace(MATERIALISED, author="new"))
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(tree.model, database.model, DriftSeverity.WARNING).render(
        changes.changes, report, column_order=False
    )
    return report


def test_a_redefined_matview_under_materialised_reports_a_lost_unique_index() -> None:
    """Its query and its unique index both differ: the index is still a finding (#701)."""
    report = _drift(_database(TABLE + VIEW), _author(TABLE + OTHER_VIEW + UNIQUE))
    (item,) = [i for i in report.drift_items if i.drift_type is DriftType.MISSING_INDEX]
    assert (item.drift_type, item.severity) == (DriftType.MISSING_INDEX, DriftSeverity.CRITICAL)
    assert item.object_name == "public.mv.ux_mv"
    assert item.subject is not None
    assert item.subject.relation == "mv"
    assert report.indexes_checked == 1


def test_a_redefined_matview_with_an_invalid_live_index_is_the_critical_pair() -> None:
    database = _database(TABLE + VIEW + UNIQUE, valid=False)
    report = _drift(database, _author(TABLE + OTHER_VIEW + UNIQUE))
    found = [(i.drift_type, i.severity) for i in report.drift_items]
    assert found == [
        (DriftType.MISSING_INDEX, DriftSeverity.CRITICAL),
        (DriftType.EXTRA_INDEX, DriftSeverity.INFO),
        (DriftType.VIEW_DEFINITION_MISMATCH, DriftSeverity.WARNING),
    ]
    assert "INVALID" in report.drift_items[0].message


def test_a_redefined_matview_alone_is_a_view_definition_mismatch() -> None:
    """The query itself differs: one warning, each side's query named by its hash (#719)."""
    report = _drift(_database(TABLE + VIEW + UNIQUE), _author(TABLE + OTHER_VIEW + UNIQUE))
    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (
        DriftType.VIEW_DEFINITION_MISMATCH,
        DriftSeverity.WARNING,
    )
    assert item.drift_type.value == "view_definition_mismatch"
    assert item.subject is not None
    assert (item.subject.schema, item.subject.relation) == ("public", "mv")
    assert item.object_name == "public.mv"
    assert re.fullmatch(r"[0-9a-f]{12}", item.expected)
    assert re.fullmatch(r"[0-9a-f]{12}", item.actual)
    assert item.expected != item.actual
    assert "--check-body-views --show-diff" in item.message


def test_a_redefined_view_is_a_view_definition_mismatch() -> None:
    """A plain view's query is compared as a matview's is."""
    view = "CREATE VIEW v AS SELECT id, n FROM tb_item;\n"
    other = "CREATE VIEW v AS SELECT id FROM tb_item WHERE n > 0;\n"
    (item,) = _drift(_database(TABLE + view), _author(TABLE + other)).drift_items
    assert item.drift_type is DriftType.VIEW_DEFINITION_MISMATCH
    assert item.object_name == "public.v"
    assert "View 'public.v'" in item.message


def test_the_hashes_are_the_body_checks_hashes() -> None:
    """``expected``/``actual`` are ``--check-body-views``' ``source_hash``/``db_hash``."""
    from confiture.core.view_body_drift import viewdef_hash

    report = _drift(_database(TABLE + VIEW), _author(TABLE + OTHER_VIEW))
    (item,) = report.drift_items
    tree, database = read_text(TABLE + OTHER_VIEW), read_text(TABLE + VIEW)
    assert item.expected == viewdef_hash(tree.catalogued.views[MV].definition or "")
    assert item.actual == viewdef_hash(database.catalogued.views[MV].definition or "")


def test_a_side_with_the_statement_and_no_model_entry_carries_no_indexes() -> None:
    """A slot side holds a matview's statement and no model entry for it."""
    read = read_text(TABLE + VIEW + UNIQUE)
    statements = {MV: read.declared.objects[MV]}
    changes = SchemaDiffer().compare_sides(slot_side("views", {}), slot_side("views", statements))
    (change,) = changes.changes
    assert isinstance(change, ObjectAdded)
    assert change.indexes == ()


# A matview redefined is one change; how its indexes differ rides on it, for a
# reader that asks about the indexes rather than the recreate.

#: The index sets a redefined matview may go from and to, and what they are.
INDEX_SHAPES = {
    "unique-dropped": (UNIQUE, "", [("IndexDropped", "ux_mv")]),
    "index-added": ("", ON_N, [("IndexAdded", "ix_mv")]),
    "keys-changed": (ON_N, ON_ID, [("IndexDropped", "ix_mv"), ("IndexAdded", "ix_mv")]),
}


def _materialised(database: str, tree: str) -> list[SchemaChange]:
    policy = replace(MATERIALISED, author="new")
    return SchemaDiffer().compare_sides(_database(database), _author(tree), policy).changes


def _replaced(changes: list[SchemaChange]) -> ObjectReplaced:
    (change,) = changes
    assert isinstance(change, ObjectReplaced)
    return change


def test_a_redefined_matview_carries_its_index_changes() -> None:
    change = _replaced(_materialised(TABLE + VIEW, TABLE + OTHER_VIEW + UNIQUE))
    (index_change,) = change.index_changes
    assert isinstance(index_change, IndexAdded)
    assert index_change.relation_kind == "matview"
    assert index_change.index.name == "ux_mv"
    assert index_change.ref == MV


def test_a_redefined_matview_with_an_invalid_live_index_carries_the_rebuild_pair() -> None:
    database = _database(TABLE + VIEW + UNIQUE, valid=False)
    policy = replace(MATERIALISED, author="new")
    changes = SchemaDiffer().compare_sides(database, _author(TABLE + OTHER_VIEW + UNIQUE), policy)
    change = _replaced(changes.changes)
    assert _index_changes(list(change.index_changes)) == [
        ("IndexDropped", "ux_mv"),
        ("IndexAdded", "ux_mv"),
    ]


def test_a_redefined_matview_whose_indexes_did_not_change_carries_none() -> None:
    change = _replaced(_materialised(TABLE + VIEW + UNIQUE, TABLE + OTHER_VIEW + UNIQUE))
    assert change.index_changes == ()


#: Each policy that can redefine a matview, and the two sides it compares.
REDEFINING = {
    "materialised": lambda old, new: SchemaDiffer().compare_sides(
        _database(old), _author(new), replace(MATERIALISED, author="new")
    ),
    "author": lambda old, new: SchemaDiffer().compare_sides(
        Side.of(read_text(old)), Side.of(read_text(new))
    ),
    "exact": lambda old, new: SchemaDiffer().compare_sides(_stored(old), _stored(new)),
}


@pytest.mark.parametrize("shape", sorted(INDEX_SHAPES))
@pytest.mark.parametrize("policy", sorted(REDEFINING))
def test_the_carried_changes_are_the_paired_comparisons(policy: str, shape: str) -> None:
    """A redefined matview's index changes are what the same indexes on a paired one are."""
    old, new, expected = INDEX_SHAPES[shape]
    compare = REDEFINING[policy]
    paired = compare(TABLE + VIEW + old, TABLE + VIEW + new).changes
    change = _replaced(compare(TABLE + VIEW + old, TABLE + OTHER_VIEW + new).changes)
    assert _index_changes(paired) == expected
    assert list(change.index_changes) == paired


def test_the_catalogued_policy_redefines_no_matview() -> None:
    """Its rules leave a matview's query only as existing: the matview is paired."""
    changes = (
        SchemaDiffer()
        .compare_sides(_database(TABLE + VIEW), _tree(TABLE + OTHER_VIEW + UNIQUE))
        .changes
    )
    assert _index_changes(changes) == [("IndexAdded", "ux_mv")]
    assert not [c for c in changes if isinstance(c, ObjectReplaced)]


def test_a_body_comparison_carries_no_index_changes() -> None:
    """Two slot sides compare a matview's query alone: no model, no index to compare."""
    before = {MV: read_text(TABLE + VIEW + UNIQUE).declared.objects[MV]}
    after = {MV: read_text(TABLE + OTHER_VIEW).declared.objects[MV]}
    changes = SchemaDiffer().compare_sides(
        slot_side("views", before), slot_side("views", after), EXACT
    )
    change = _replaced(changes.changes)
    assert change.index_changes == ()


def test_the_carried_changes_are_not_on_the_wire() -> None:
    change = _replaced(_materialised(TABLE + VIEW, TABLE + OTHER_VIEW + UNIQUE))
    assert change.index_changes
    assert change.to_wire() == replace(change, index_changes=()).to_wire()
