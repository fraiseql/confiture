"""A materialized view's indexes are compared as a table's are (#690).

A matview holds no constraints, so its indexes are all a comparison has to say
about it besides its query. They go through the one index comparison under
every policy: an index missing, extra, changed or INVALID is the index change a
table would get, named by the matview's key. A matview that is added, dropped or
redefined carries its whole index set on its own change instead, so its indexes
are created with it and never ranked before it exists.
"""

from dataclasses import replace

from confiture.core.differ import (
    MATERIALISED,
    SchemaDiffer,
    Side,
    slot_side,
    stated_side,
)
from confiture.core.drift import DriftReport, DriftSeverity, _Findings
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


def test_a_redefined_matview_under_materialised_hides_a_lost_unique_index() -> None:
    """A known limit: drift renders no redefined matview, so its lost index goes unsaid."""
    actual, expected = _database(TABLE + VIEW), _database(TABLE + OTHER_VIEW + UNIQUE)
    expected = replace(expected, model=replace(expected.model, source="author"))
    policy = replace(MATERIALISED, author="new")
    changes = SchemaDiffer().compare_sides(actual, expected, policy).changes
    (change,) = changes
    assert isinstance(change, ObjectReplaced)
    assert [i.name for i in change.new_indexes] == ["ux_mv"]
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(expected.model, actual.model, DriftSeverity.WARNING).render(
        changes, report, column_order=False
    )
    assert report.drift_items == []


def test_a_side_with_the_statement_and_no_model_entry_carries_no_indexes() -> None:
    """A slot side holds a matview's statement and no model entry for it."""
    read = read_text(TABLE + VIEW + UNIQUE)
    statements = {MV: read.declared.objects[MV]}
    changes = SchemaDiffer().compare_sides(slot_side("views", {}), slot_side("views", statements))
    (change,) = changes.changes
    assert isinstance(change, ObjectAdded)
    assert change.indexes == ()
