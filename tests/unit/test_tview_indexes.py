"""A TVIEW's indexes are compared, carried and ordered as a table's are.

pg_tviews keeps a user's index on a TVIEW across a refresh, a cascade and a
replace, and drops it with the TVIEW. An index a tree writes on one therefore
reaches the diff as an index change on the TVIEW (``relation_kind="tview"``),
built ``CONCURRENTLY``; a TVIEW added or dropped carries its indexes, created
after ``pg_tviews_create_or_replace()``. pg_tviews' own indexes
(``TView.managed_indexes``) are never compared: a tree that writes one exactly
writes what pg_tviews adopts as its own, and one that writes another index
under its name is refused (``DIFFER_410``), since pg_tviews skipped it.
"""

from dataclasses import replace

import pytest

from confiture.core import differ
from confiture.core.differ import (
    CATALOGUED,
    EXACT,
    SchemaDiffer,
    Side,
    stated_side,
)
from confiture.core.schema_change import (
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    SchemaChange,
)
from confiture.core.schema_model import Index, RelationName, ref_for
from confiture.core.schema_read import read_text
from confiture.exceptions import DifferError

TABLE = "CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid, title text);\n"
TV = "CREATE TABLE tv_post AS SELECT p.pk_post, p.id, p.title FROM tb_post p;\n"
TV_WIDER = (
    "CREATE TABLE tv_post AS SELECT p.pk_post, p.id, p.title, upper(p.title) AS shout "
    "FROM tb_post p;\n"
)
ON_TITLE = "CREATE INDEX ix_tv_post_title ON tv_post (title);\n"
ON_ID_TITLE = "CREATE INDEX ix_tv_post_title ON tv_post (id, title);\n"
ON_SHOUT = "CREATE INDEX ix_tv_post_shout ON tv_post (shout);\n"
TVREF = ref_for("tview", None, "tv_post")
#: pg_tviews' own index on the TVIEW's ``id``, as ``tviews.registry.managed_indexes`` names it.
MANAGED = Index(
    name="idx_tv_post_id",
    table=RelationName("public", "tv_post"),
    columns=("id",),
    method="btree",
    expressions=(False,),
)


def _trees(old: str, new: str) -> list[SchemaChange]:
    return SchemaDiffer().compare_sides(Side.of(read_text(old)), Side.of(read_text(new))).changes


def _database(sql: str, *, managed: tuple[Index, ...] = (), indexes: object = ...) -> Side:
    """A database holding what *sql* declares, its TVIEW holding pg_tviews' *managed* indexes."""
    model = read_text(sql).catalogued
    tview = replace(model.tviews[TVREF], managed_indexes=managed)
    if indexes is not ...:
        tview = replace(tview, indexes=indexes)
    return stated_side(replace(model, tviews={**model.tviews, TVREF: tview}, source="catalog"))


def _tree(sql: str) -> Side:
    return Side.of(read_text(sql), held=True)


def _index_changes(changes: list[SchemaChange]) -> list[tuple[str, str | None, str]]:
    return [
        (type(c).__name__, c.index.name, c.relation_kind)
        for c in changes
        if isinstance(c, IndexAdded | IndexDropped)
    ]


def test_two_trees_see_a_tview_index_added() -> None:
    (change,) = _trees(TABLE + TV, TABLE + TV + ON_TITLE)
    assert isinstance(change, IndexAdded)
    assert (change.index.name, change.relation_kind) == ("ix_tv_post_title", "tview")
    assert change.ref == TVREF
    assert change.ref in read_text(TABLE + TV + ON_TITLE).model.tviews


def test_two_trees_see_a_tview_index_dropped() -> None:
    (change,) = _trees(TABLE + TV + ON_TITLE, TABLE + TV)
    assert isinstance(change, IndexDropped)
    assert (change.index.name, change.relation_kind) == ("ix_tv_post_title", "tview")
    assert change.ref == TVREF


def test_two_trees_rebuild_a_tview_index_whose_keys_change() -> None:
    changes = _trees(TABLE + TV + ON_TITLE, TABLE + TV + ON_ID_TITLE)
    assert _index_changes(changes) == [
        ("IndexDropped", "ix_tv_post_title", "tview"),
        ("IndexAdded", "ix_tv_post_title", "tview"),
    ]
    assert len(changes) == 2


def test_an_index_only_difference_against_a_database_is_no_redefinition() -> None:
    """The index is compared as a table's is, never as part of the TVIEW's options."""
    changes = SchemaDiffer().compare_sides(_database(TABLE + TV), _tree(TABLE + TV + ON_TITLE))
    assert _index_changes(changes.changes) == [("IndexAdded", "ix_tv_post_title", "tview")]
    assert len(changes.changes) == 1


def test_an_index_only_difference_with_no_author_side_is_no_redefinition() -> None:
    old, new = _database(TABLE + TV), _database(TABLE + TV + ON_TITLE)
    changes = SchemaDiffer().compare_sides(old, new, CATALOGUED).changes
    assert _index_changes(changes) == [("IndexAdded", "ix_tv_post_title", "tview")]
    assert not [c for c in changes if isinstance(c, ObjectReplaced)]


def test_an_exact_copy_of_pg_tviews_own_index_is_no_change() -> None:
    """pg_tviews adopts an index that is exactly its own: it is not the TVIEW's user index."""
    copy = "CREATE INDEX idx_tv_post_id ON tv_post (id);\n"
    database = _database(TABLE + TV, managed=(MANAGED,))
    assert SchemaDiffer().compare_sides(database, _tree(TABLE + TV + copy)).changes == []


def test_another_index_under_pg_tviews_own_name_is_refused() -> None:
    """pg_tviews skipped the tree's ``CREATE INDEX IF NOT EXISTS``: the name was its own."""
    other = "CREATE INDEX IF NOT EXISTS idx_tv_post_id ON tv_post (lower(id::text));\n"
    database = _database(TABLE + TV, managed=(MANAGED,))
    with pytest.raises(DifferError) as refused:
        SchemaDiffer().compare_sides(database, _tree(TABLE + TV + other))
    assert refused.value.error_code == "DIFFER_410"
    assert "idx_tv_post_id" in str(refused.value)
    assert "tv_post" in str(refused.value)


def test_the_adoption_is_one_pure_answer() -> None:
    author = read_text(TABLE + TV + "CREATE INDEX idx_tv_post_id ON tv_post (id);\n" + ON_TITLE)
    tview = author.catalogued.tviews[TVREF]
    catalog = replace(tview, indexes=(), managed_indexes=(MANAGED,))
    adopted = getattr(differ, "adopted_by_pg_tviews", None)
    assert adopted is not None
    kept, conflicts = adopted(tview, catalog, CATALOGUED.rules)
    assert [i.name for i in kept] == ["ix_tv_post_title"]
    assert conflicts == ()


def test_two_databases_compare_no_adoption() -> None:
    """Both sides are pg_tviews' answer already: an index is either side's user index."""
    user = replace(MANAGED, columns=("title",))
    old = _database(TABLE + TV, managed=(MANAGED,))
    new = _database(TABLE + TV, indexes=(user,))
    changes = SchemaDiffer().compare_sides(old, new, EXACT).changes
    assert _index_changes(changes) == [("IndexAdded", "idx_tv_post_id", "tview")]


def test_two_trees_compare_no_adoption() -> None:
    copy = "CREATE INDEX idx_tv_post_id ON tv_post (id);\n"
    assert _index_changes(_trees(TABLE + TV, TABLE + TV + copy)) == [
        ("IndexAdded", "idx_tv_post_id", "tview")
    ]


def test_an_index_on_a_tview_is_no_warning() -> None:
    tree = TABLE + TV
    assert read_text(tree + ON_TITLE).warnings == []
    assert SchemaDiffer().compare(tree, tree + ON_TITLE).warnings == []


def test_indexes_not_read_are_not_compared() -> None:
    database = _database(TABLE + TV, indexes=None)
    assert SchemaDiffer().compare_sides(database, _tree(TABLE + TV + ON_TITLE)).changes == []


def test_an_added_tview_carries_its_indexes() -> None:
    changes = _trees(TABLE, TABLE + TV + ON_TITLE)
    (change,) = [c for c in changes if isinstance(c, ObjectAdded)]
    assert [i.name for i in change.indexes] == ["ix_tv_post_title"]
    assert _index_changes(changes) == []


def test_a_dropped_tview_carries_its_indexes() -> None:
    changes = _trees(TABLE + TV + ON_TITLE, TABLE)
    (change,) = [c for c in changes if isinstance(c, ObjectDropped)]
    assert [i.name for i in change.indexes] == ["ix_tv_post_title"]
    assert _index_changes(changes) == []


def test_a_redefined_tview_carries_none_and_its_index_changes_are_pairs() -> None:
    """``pg_tviews_create_or_replace()`` keeps a user's index: nothing is created again."""
    changes = _trees(TABLE + TV + ON_TITLE, TABLE + TV_WIDER + ON_SHOUT)
    (replaced,) = [c for c in changes if isinstance(c, ObjectReplaced)]
    assert (replaced.old_indexes, replaced.new_indexes) == ((), ())
    assert sorted(_index_changes(changes)) == [
        ("IndexAdded", "ix_tv_post_shout", "tview"),
        ("IndexDropped", "ix_tv_post_title", "tview"),
    ]
