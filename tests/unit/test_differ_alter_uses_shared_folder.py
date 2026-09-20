"""The differ folds an ``ALTER TABLE`` through the same decision the inventory reads.

``SchemaDiffer`` and the lint inventory both fold ``ALTER TABLE`` into an
expected schema, over object models that share nothing — a ``ColumnType`` enum
and a ``raw_sql_type`` here, ``type_text`` as written there. So the *decision*
is shared (``ddl_walk.column_edit``) and the application is not, and neither
reader names an ``AlterTableType`` member of its own.

What this pins is that the differ's behaviour did not move when the decision
did: add, drop and retype all still land, and an ``ALTER`` against a table this
tree never creates is still ignored.
"""

from __future__ import annotations

import pytest

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import ColumnType, Table

REPRO = """
CREATE TABLE tb_widget (
    id BIGINT PRIMARY KEY,
    serial TEXT NOT NULL,
    legacy_drop TEXT,
    maybe_null TEXT,
    ratio INT
);
ALTER TABLE tb_widget DROP COLUMN legacy_drop;
ALTER TABLE tb_widget ALTER COLUMN ratio TYPE BIGINT;
ALTER TABLE tb_widget ADD COLUMN added_later TEXT;
ALTER TABLE tb_widget ALTER COLUMN maybe_null SET NOT NULL;
ALTER TABLE tb_widget ALTER COLUMN serial SET DEFAULT 'x';
"""


@pytest.fixture
def widget() -> Table:
    tables = SchemaDiffer().parse_schema(REPRO).tables
    return next(table for table in tables if table.name == "tb_widget")


def test_a_dropped_column_is_gone(widget: Table) -> None:
    assert [column.name for column in widget.columns] == [
        "id",
        "serial",
        "maybe_null",
        "ratio",
        "added_later",
    ]


def test_a_retyped_column_carries_the_new_type(widget: Table) -> None:
    ratio = widget.get_column("ratio")
    assert ratio is not None
    assert ratio.type is ColumnType.BIGINT
    # `raw_sql_type` is the type as generated DDL should write it, recorded for
    # every column. It used to be filled only for a type `_COLUMN_TYPE_MAP` does
    # not model, which is what dropped `VARCHAR(50)`'s length on the floor: the
    # length lives in the spelling, and a modelled type had no spelling to keep
    # it in. `ColumnType` is still the canonical identity.
    assert ratio.raw_sql_type == "BIGINT"


def test_an_added_column_lands_where_the_alter_put_it(widget: Table) -> None:
    added = widget.get_column("added_later")
    assert added is not None
    assert added.type is ColumnType.TEXT


def test_an_alter_naming_a_table_this_tree_never_creates_is_ignored() -> None:
    """It belongs to a schema built elsewhere — the differ's own docstring says so."""
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int); ALTER TABLE absent DROP COLUMN x;"
    )
    assert [table.name for table in parsed.tables] == ["t"]
    assert [column.name for column in parsed.tables[0].columns] == ["a"]


def test_an_add_column_of_a_name_already_written_overwrites_it() -> None:
    """``_replace_column``'s contract, kept when the dispatch moved."""
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int); ALTER TABLE t ADD COLUMN a bigint;"
    )
    columns = parsed.tables[0].columns
    assert [column.name for column in columns] == ["a"]
    assert columns[0].type is ColumnType.BIGINT


def test_set_not_null_lands_on_the_column(widget: Table) -> None:
    maybe_null = widget.get_column("maybe_null")
    assert maybe_null is not None
    assert maybe_null.nullable is False


def test_set_default_lands_on_the_column(widget: Table) -> None:
    serial = widget.get_column("serial")
    assert serial is not None
    assert serial.default == "'x'"


def test_drop_not_null_and_drop_default_land_on_the_column() -> None:
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int NOT NULL DEFAULT 7);"
        "ALTER TABLE t ALTER COLUMN a DROP NOT NULL;"
        "ALTER TABLE t ALTER COLUMN a DROP DEFAULT;"
    )
    column = parsed.tables[0].columns[0]
    assert column.nullable is True
    assert column.default is None
