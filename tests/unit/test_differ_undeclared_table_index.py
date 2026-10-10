"""An index on a table the tree does not declare reaches the diff (#679).

A desired state can declare an index without the table it is on: the table is
someone else's to author, and the index is what a consumer's queries need. The
index is carried as written, ``CONCURRENTLY`` since the table exists and is in
use, with a comment and a ``DIFFER_405`` warning naming the undeclared table —
never dropped in silence.
"""

from dataclasses import replace
from pathlib import Path

import pglast
import pytest

from confiture.core.differ import SchemaDiffer, Side
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_change import IndexAdded, IndexDropped, TableAdded
from confiture.core.schema_model import RelationName, SchemaModel
from confiture.exceptions import DifferError

INDEX = "CREATE INDEX IF NOT EXISTS ix_tv_product_name ON tv_product ((data->>'name'));"


def _generated(tmp_path: Path, old: str, new: str) -> tuple[str, str]:
    diff = SchemaDiffer().compare(old, new)
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        diff, name="probe", version="20260101000000"
    )
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
    return up.read_text(), down.read_text()


def test_an_index_on_an_undeclared_table_is_added() -> None:
    diff = SchemaDiffer().compare("", INDEX)

    [change] = diff.changes
    assert isinstance(change, IndexAdded)
    assert change.table == RelationName(None, "tv_product")
    assert change.index.name == "ix_tv_product_name"


def test_the_migration_creates_it_concurrently_and_names_the_table(tmp_path: Path) -> None:
    up, _ = _generated(tmp_path, "", INDEX)

    [statement] = pglast.parse_sql(up)
    assert statement.stmt.concurrent
    assert statement.stmt.relation.relname == "tv_product"
    assert "tv_product is not declared in this schema" in up


def test_the_down_drops_it_concurrently(tmp_path: Path) -> None:
    _, down = _generated(tmp_path, "", INDEX)

    [statement] = pglast.parse_sql(down)
    assert statement.stmt.concurrent
    assert "tv_product is not declared in this schema" in down


def test_the_diff_warns_naming_the_index_and_the_table() -> None:
    diff = SchemaDiffer().compare("", INDEX)

    [warning] = diff.warnings
    assert warning.code == "DIFFER_405"
    assert "ix_tv_product_name" in warning.message
    assert "tv_product" in warning.message


def test_the_same_index_on_both_sides_is_no_change() -> None:
    diff = SchemaDiffer().compare(INDEX, INDEX)

    assert diff.changes == []
    assert diff.warnings == []


def test_an_index_only_the_old_tree_writes_is_dropped() -> None:
    [change] = SchemaDiffer().compare(INDEX, "").changes

    assert isinstance(change, IndexDropped)
    assert change.table == RelationName(None, "tv_product")


def test_a_changed_index_is_dropped_then_added() -> None:
    changed = INDEX.replace("'name'", "'title'")

    kinds = [type(c) for c in SchemaDiffer().compare(INDEX, changed).changes]

    assert kinds == [IndexDropped, IndexAdded]


def test_the_schema_qualifier_is_the_identity() -> None:
    qualified = INDEX.replace("ON tv_product", "ON public.tv_product")

    assert SchemaDiffer().compare(INDEX, qualified).changes == []


def test_an_index_written_before_its_table_is_the_tables() -> None:
    tree = f"{INDEX}\nCREATE TABLE tv_product (id INT, data JSONB);"

    [change] = SchemaDiffer().compare("", tree).changes

    assert isinstance(change, TableAdded)
    assert [ix.name for ix in change.table.indexes] == ["ix_tv_product_name"]


def test_a_dropped_index_is_not_carried() -> None:
    tree = f"{INDEX}\nDROP INDEX ix_tv_product_name;"

    assert SchemaDiffer().compare("", tree).changes == []


def test_a_database_side_never_holds_one() -> None:
    """A database holds every index on a table it has: none is unattached there."""
    database = SchemaDiffer().parse_schema(INDEX).model

    assert replace(database, source="database").unattached_indexes == database.unattached_indexes


def test_the_model_wire_carries_it() -> None:
    model = SchemaDiffer().parse_schema(INDEX).model

    assert SchemaModel.from_json(model.to_json()) == model
    [index] = model.unattached_indexes[RelationName(None, "tv_product").ref()]
    assert index.name == "ix_tv_product_name"


# DIFFER_406: the desired state indexes a relation it would drop, or one no side holds.

_BASE = "CREATE TABLE tb_product (id INT, data JSONB);\n"
_DECLARED = {
    "table": "CREATE TABLE tv_product (id INT, data JSONB);",
    "matview": "CREATE MATERIALIZED VIEW tv_product AS SELECT id, data FROM tb_product;",
    "tview": "CREATE TABLE tv_product AS SELECT id, data FROM tb_product;",
}


def _side(sql: str, source: str = "author") -> Side:
    side = SchemaDiffer().parse_schema(sql)
    return replace(side, model=replace(side.model, source=source))


@pytest.mark.parametrize("source", ["author", "catalog"])
@pytest.mark.parametrize("kind", list(_DECLARED))
def test_indexing_a_relation_the_desired_state_drops_is_refused(kind: str, source: str) -> None:
    current = _side(_BASE + _DECLARED[kind], source)
    desired = _side(_BASE + INDEX)

    with pytest.raises(DifferError) as refused:
        SchemaDiffer().compare_sides(current, desired)

    assert refused.value.error_code == "DIFFER_406"
    assert "ix_tv_product_name" in str(refused.value)
    assert "tv_product" in str(refused.value)


def test_a_database_without_the_relation_refuses_too() -> None:
    """The migration would create an index on a table the database does not hold."""
    current = _side(_BASE, "catalog")
    desired = _side(_BASE + INDEX)

    with pytest.raises(DifferError) as refused:
        SchemaDiffer().compare_sides(current, desired)

    assert refused.value.error_code == "DIFFER_406"


def test_a_relation_both_sides_declare_is_compared_as_usual() -> None:
    tree = _BASE + _DECLARED["table"]

    [change] = SchemaDiffer().compare(tree, tree + INDEX).changes

    assert isinstance(change, IndexAdded)
    assert change.table_declared


def test_an_old_tree_indexing_a_relation_the_new_declares_is_no_refusal() -> None:
    """The new tree adds the table with the index: the old side's index says nothing."""
    [change] = SchemaDiffer().compare(_BASE + INDEX, _BASE + _DECLARED["table"]).changes

    assert isinstance(change, TableAdded)


def test_the_model_a_database_is_compared_with_keeps_them() -> None:
    """``catalogued`` is the tree a database is compared with: it holds the same indexes."""
    from confiture.core.schema_read import read_text

    read = read_text(INDEX)

    assert read.catalogued.unattached_indexes == read.model.unattached_indexes != {}


# DIFFER_407: an index on a declared TVIEW is a warning until the model carries it.

_TVIEW_INDEX = "CREATE INDEX ix_tv_product_id ON tv_product (id);"


def test_an_index_on_a_tview_is_a_warning_naming_both() -> None:
    from confiture.core.schema_read import read_text

    [warning] = read_text(_BASE + _DECLARED["tview"] + _TVIEW_INDEX).warnings

    assert warning.code == "DIFFER_407"
    assert warning.severity == "warning"
    assert "ix_tv_product_id" in warning.message
    assert "tv_product" in warning.message


def test_the_diff_says_so_and_carries_nothing() -> None:
    tree = _BASE + _DECLARED["tview"]

    diff = SchemaDiffer().compare(tree, tree + _TVIEW_INDEX)

    assert diff.changes == []
    assert [w.code for w in diff.warnings] == ["DIFFER_407"]


def test_an_index_on_a_table_or_matview_is_no_warning() -> None:
    from confiture.core.schema_read import read_text

    for kind in ("table", "matview"):
        assert read_text(_BASE + _DECLARED[kind] + _TVIEW_INDEX).warnings == []
