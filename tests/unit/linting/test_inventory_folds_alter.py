"""The inventory folds an ``ALTER TABLE`` into the table the tree already created.

A build-from-DDL tree may append an ``ALTER TABLE`` rather than edit the
``CREATE TABLE``; what a database ends up with is the two together, so that is
what the expected schema has to hold. Before this, ``_apply_alter`` folded
``ADD COLUMN`` and the primary-key flag and nothing else, so `confiture drift`
reported a **critical** `missing_column` for a column the tree had dropped —
on a database applied verbatim from that tree (#301).

The DDL below is #301's own reproduction.
"""

import pytest

from confiture.core.linting.inventory import SchemaObject
from confiture.core.schema_read import read_text
from confiture.core.type_lattice import canonical_type

REPRO = """
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE core.tb_widget (
    id BIGINT PRIMARY KEY,
    serial TEXT NOT NULL,
    legacy_drop TEXT,
    maybe_null TEXT,
    ratio INT
);
ALTER TABLE core.tb_widget DROP COLUMN legacy_drop;
ALTER TABLE core.tb_widget ALTER COLUMN maybe_null SET NOT NULL;
ALTER TABLE core.tb_widget ALTER COLUMN ratio TYPE BIGINT;
"""


@pytest.fixture
def widget() -> SchemaObject:
    table = read_text(REPRO).inventory.find("core", "tb_widget")
    assert table is not None
    return table


def test_a_dropped_column_is_not_in_the_expected_schema(widget: SchemaObject) -> None:
    assert [column.folded for column in widget.columns] == [
        "id",
        "serial",
        "maybe_null",
        "ratio",
    ]


def test_a_retyped_column_carries_the_type_the_alter_gave_it(widget: SchemaObject) -> None:
    ratio = next(column for column in widget.columns if column.folded == "ratio")
    assert canonical_type(ratio.type_text) == "bigint"


def test_an_alter_naming_a_table_the_tree_never_creates_is_ignored() -> None:
    """It belongs to a schema built elsewhere — both readers ignore it, and must."""
    inventory = read_text("ALTER TABLE elsewhere.tb_absent DROP COLUMN x;").inventory
    assert inventory.objects == []


def test_a_column_added_then_dropped_is_gone() -> None:
    sql = """
    CREATE TABLE t (a int);
    ALTER TABLE t ADD COLUMN b int;
    ALTER TABLE t DROP COLUMN b;
    """
    table = read_text(sql).inventory.find(None, "t")
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]


def test_dropping_a_column_the_tree_never_created_changes_nothing() -> None:
    table = read_text("CREATE TABLE t (a int); ALTER TABLE t DROP COLUMN absent;").inventory.find(
        None, "t"
    )
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]


def test_retyping_a_column_the_tree_never_created_adds_nothing() -> None:
    """A retype is an edit to a column, never a way to invent one."""
    table = read_text(
        "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN absent TYPE bigint;"
    ).inventory.find(None, "t")
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]


def test_set_not_null_lands_on_the_column(widget: SchemaObject) -> None:
    """#301's third item: neither reader folded this, in either direction."""
    maybe_null = next(column for column in widget.columns if column.folded == "maybe_null")
    assert maybe_null.not_null is True


def test_drop_not_null_lands_on_the_column() -> None:
    table = read_text(
        "CREATE TABLE t (a int NOT NULL); ALTER TABLE t ALTER COLUMN a DROP NOT NULL;"
    ).inventory.find(None, "t")
    assert table is not None
    assert table.columns[0].not_null is False


def test_set_default_and_drop_default_land_on_the_column() -> None:
    table = read_text(
        "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN a SET DEFAULT 7;"
    ).inventory.find(None, "t")
    assert table is not None
    assert table.columns[0].default == "7"

    dropped = read_text(
        "CREATE TABLE t (a int DEFAULT 7); ALTER TABLE t ALTER COLUMN a DROP DEFAULT;"
    ).inventory.find(None, "t")
    assert dropped is not None
    assert dropped.columns[0].default is None


def _table_t(sql: str) -> SchemaObject:
    table = read_text(sql).inventory.find(None, "t")
    assert table is not None
    return table


def test_a_dropped_constraint_is_not_in_the_expected_schema() -> None:
    """#624: a key a later ``DROP CONSTRAINT`` drops is not one the table holds."""
    table = _table_t(
        "CREATE TABLE t (id int PRIMARY KEY, code text, CONSTRAINT t_code_key UNIQUE (code));\n"
        "ALTER TABLE t DROP CONSTRAINT t_code_key;\n"
    )
    assert [c.kind for c in table.constraints] == ["primary_key"]


def test_a_dropped_constraint_leaves_the_model() -> None:
    model = read_text(
        "CREATE TABLE t (id int, CONSTRAINT t_id_check CHECK (id > 0));\n"
        "ALTER TABLE t DROP CONSTRAINT IF EXISTS t_id_check;\n"
    ).model
    (table,) = model.tables.values()
    assert table.constraints == ()


def test_a_dropped_primary_key_leaves_its_columns_not_null() -> None:
    """Measured on PostgreSQL 18.4: the key goes, the column's ``NOT NULL`` stays."""
    table = _table_t(
        "CREATE TABLE t (id int, CONSTRAINT t_pkey PRIMARY KEY (id));\n"
        "ALTER TABLE t DROP CONSTRAINT t_pkey;\n"
    )
    assert table.constraints == []
    assert table.has_primary_key is False
    assert (table.columns[0].primary_key, table.columns[0].not_null) == (False, True)


def test_a_constraint_dropped_then_added_again_is_held() -> None:
    """The fold is in statement order: the ``ADD`` after the ``DROP`` is what remains."""
    table = _table_t(
        "CREATE TABLE t (a int, b int, CONSTRAINT k UNIQUE (a));\n"
        "ALTER TABLE t DROP CONSTRAINT k, ADD CONSTRAINT k UNIQUE (a, b);\n"
    )
    assert [c.columns for c in table.constraints] == [("a", "b")]


def test_dropping_a_constraint_the_tree_never_named_changes_nothing() -> None:
    """An unnamed key is identified by what it says; a name the tree never wrote is not it."""
    table = _table_t("CREATE TABLE t (a int UNIQUE);\nALTER TABLE t DROP CONSTRAINT absent;\n")
    assert [c.columns for c in table.constraints] == [("a",)]
