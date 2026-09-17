"""The inventory folds an ``ALTER TABLE`` into the table the tree already created.

A build-from-DDL tree may append an ``ALTER TABLE`` rather than edit the
``CREATE TABLE``; what a database ends up with is the two together, so that is
what the expected schema has to hold. Before this, ``_apply_alter`` folded
``ADD COLUMN`` and the primary-key flag and nothing else, so `confiture drift`
reported a **critical** `missing_column` for a column the tree had dropped —
on a database applied verbatim from that tree (#301).

The DDL below is #301's own reproduction.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.inventory import SchemaObject, build_inventory
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
    table = build_inventory(REPRO).find("core", "tb_widget")
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
    inventory = build_inventory("ALTER TABLE elsewhere.tb_absent DROP COLUMN x;")
    assert inventory.objects == []


def test_a_column_added_then_dropped_is_gone() -> None:
    sql = """
    CREATE TABLE t (a int);
    ALTER TABLE t ADD COLUMN b int;
    ALTER TABLE t DROP COLUMN b;
    """
    table = build_inventory(sql).find(None, "t")
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]


def test_dropping_a_column_the_tree_never_created_changes_nothing() -> None:
    table = build_inventory("CREATE TABLE t (a int); ALTER TABLE t DROP COLUMN absent;").find(
        None, "t"
    )
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]


def test_retyping_a_column_the_tree_never_created_adds_nothing() -> None:
    """A retype is an edit to a column, never a way to invent one."""
    table = build_inventory(
        "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN absent TYPE bigint;"
    ).find(None, "t")
    assert table is not None
    assert [column.folded for column in table.columns] == ["a"]
