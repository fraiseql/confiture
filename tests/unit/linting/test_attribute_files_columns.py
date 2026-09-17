"""A finding names the line the column is written on, whatever a later file did to it.

`confiture lint` builds two inventories: one over the concatenated build, where a
``COMMENT ON`` in one file resolves against a ``CREATE`` in another, and one per
file, which is the only thing that knows which file a statement came from.
:func:`attribute_files` copies the file and the in-file line across.

It used to copy the columns' lines by **position**. That is exact only while the
whole-build inventory and the per-file one hold the same columns in the same
order — true when the only fold is ``ADD COLUMN``, false the moment a
``DROP COLUMN`` in a *second* file is folded: the whole-build table is then one
column shorter than the file's own, and every column after the dropped one takes
its predecessor's line. A finding pointing at the wrong line is worse than one
with no line at all, which is the rule this function already states.
"""

from __future__ import annotations

from confiture.core.linting.inventory import Inventory, attribute_files, build_inventory

CREATE_FILE = """CREATE TABLE core.tb_widget (
    id BIGINT PRIMARY KEY,
    serial TEXT NOT NULL,
    legacy_drop TEXT,
    maybe_null TEXT,
    ratio INT
);
"""

ALTER_FILE = """ALTER TABLE core.tb_widget DROP COLUMN legacy_drop;
ALTER TABLE core.tb_widget ALTER COLUMN ratio TYPE BIGINT;
"""

SCHEMA_FILE = "CREATE SCHEMA IF NOT EXISTS core;\n"


def _per_file_objects(files: dict[str, str]) -> list:
    """What ``SchemaLinter._inventory_per_file`` produces: each file alone, labelled."""
    located = []
    for label, text in files.items():
        for obj in build_inventory(text).objects:
            obj.file = label
            located.append(obj)
    return located


def _attributed() -> Inventory:
    files = {
        "010_schema.sql": SCHEMA_FILE,
        "020_tables.sql": CREATE_FILE,
        "030_alters.sql": ALTER_FILE,
    }
    whole = build_inventory("".join(files.values()))
    attribute_files(whole, _per_file_objects(files))
    return whole


def test_every_surviving_column_keeps_its_own_line() -> None:
    table = _attributed().find("core", "tb_widget")
    assert table is not None
    assert {column.folded: column.line for column in table.columns} == {
        "id": 2,
        "serial": 3,
        "maybe_null": 5,
        "ratio": 6,
    }


def test_the_table_is_attributed_to_the_file_that_creates_it() -> None:
    table = _attributed().find("core", "tb_widget")
    assert table is not None
    assert table.file == "020_tables.sql"
