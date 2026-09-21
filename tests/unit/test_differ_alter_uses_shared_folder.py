"""The differ folds an ``ALTER TABLE`` through the same decision the inventory reads.

``SchemaDiffer`` and the lint inventory both fold ``ALTER TABLE`` into an
expected schema, and the differ now reads the model the inventory builds: one *decision*
(``ddl_walk.column_edit``) and one application of it, and no reader names an
``AlterTableType`` member of its own.

What this pins is that the differ's behaviour did not move when the decision
did: add, drop and retype all still land, and an ``ALTER`` against a table this
tree never creates is still ignored.
"""

from __future__ import annotations

import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.schema_model import Table

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
    ratio = widget.column("ratio")
    assert ratio is not None
    assert ratio.type_key == "bigint"
    # `raw_sql_type` is the type as generated DDL should write it, recorded for
    # every column: the length lives in the spelling. `type_key` is the identity.
    assert ratio.raw_sql_type == "BIGINT"


def test_an_added_column_lands_where_the_alter_put_it(widget: Table) -> None:
    added = widget.column("added_later")
    assert added is not None
    assert added.type_key == "text"


def test_an_alter_naming_a_table_this_tree_never_creates_is_ignored() -> None:
    """It belongs to a schema built elsewhere — the differ's own docstring says so."""
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int); ALTER TABLE absent DROP COLUMN x;"
    )
    assert [table.name for table in parsed.tables] == ["t"]
    assert [column.name for column in parsed.tables[0].columns] == ["a"]


def test_an_add_column_of_a_name_already_written_leaves_the_first() -> None:
    """What a database built from the tree holds.

    ``ADD COLUMN IF NOT EXISTS`` is a no-op on a column that exists, and a plain
    ``ADD COLUMN`` fails the build at that statement: either way the column is
    the one the ``CREATE`` declared. The differ used to let the second overwrite
    the first, and the lint inventory kept both.
    """
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int); ALTER TABLE t ADD COLUMN IF NOT EXISTS a bigint;"
    )
    columns = parsed.tables[0].columns
    assert [column.name for column in columns] == ["a"]
    assert columns[0].type_key == "integer"


def test_set_not_null_lands_on_the_column(widget: Table) -> None:
    maybe_null = widget.column("maybe_null")
    assert maybe_null is not None
    assert maybe_null.not_null is True


def test_set_default_lands_on_the_column(widget: Table) -> None:
    serial = widget.column("serial")
    assert serial is not None
    assert serial.default == "'x'"


def test_drop_not_null_and_drop_default_land_on_the_column() -> None:
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int NOT NULL DEFAULT 7);"
        "ALTER TABLE t ALTER COLUMN a DROP NOT NULL;"
        "ALTER TABLE t ALTER COLUMN a DROP DEFAULT;"
    )
    column = parsed.tables[0].columns[0]
    assert column.not_null is False
    assert column.default is None
