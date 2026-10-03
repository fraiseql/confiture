"""An object and each of its columns are placed in the file that wrote them, at the line in it.

Each file of a tree is parsed on its own, so a position is a line of a file the
author edits — never a line of the files joined together. A column an ``ALTER
TABLE … ADD COLUMN`` in a later file adds is that file's, not its table's: a
finding about it points where it was written.
"""

from __future__ import annotations

from confiture.core.schema_read import Segment, read_segments

SCHEMA_FILE = "CREATE SCHEMA IF NOT EXISTS core;\n"

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

ALTER TABLE core.tb_widget ADD COLUMN added_later TEXT;
CREATE INDEX ix_widget_ratio ON core.tb_widget (ratio);
"""


def _widget():
    read = read_segments(
        [
            Segment(None, SCHEMA_FILE, "010_schema.sql"),
            Segment(None, CREATE_FILE, "020_tables.sql"),
            Segment(None, ALTER_FILE, "030_alters.sql"),
        ]
    )
    table = read.inventory.find("core", "tb_widget")
    assert table is not None
    return table


def test_the_table_is_placed_in_the_file_that_creates_it() -> None:
    table = _widget()
    assert (table.file, table.line) == ("020_tables.sql", 1)


def test_every_column_is_placed_where_it_is_written() -> None:
    assert {column.folded: (column.file, column.line) for column in _widget().columns} == {
        "id": ("020_tables.sql", 2),
        "serial": ("020_tables.sql", 3),
        "maybe_null": ("020_tables.sql", 5),
        "ratio": ("020_tables.sql", 6),
        "added_later": ("030_alters.sql", 4),
    }


def test_an_index_is_placed_where_its_statement_is() -> None:
    table = _widget()
    (index,) = table.indexes
    assert table.index_sites[index] == ("030_alters.sql", 5)
