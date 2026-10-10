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

from confiture.core.differ import SchemaDiffer, Side
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_change import IndexAdded, IndexDropped, TableAdded
from confiture.core.schema_model import RelationName, SchemaModel

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


def test_a_database_side_compares_none() -> None:
    """A database holds every index on a table it has: none is unattached there."""
    tree = SchemaDiffer().parse_schema(INDEX)
    database = Side(model=replace(SchemaModel(), source="database"))

    assert SchemaDiffer().compare_sides(database, tree).changes == []


def test_the_model_wire_carries_it() -> None:
    model = SchemaDiffer().parse_schema(INDEX).model

    assert SchemaModel.from_json(model.to_json()) == model
    [index] = model.unattached_indexes[RelationName(None, "tv_product").ref()]
    assert index.name == "ix_tv_product_name"
