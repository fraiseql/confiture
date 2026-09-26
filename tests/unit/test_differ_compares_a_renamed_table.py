"""A table the differ pairs as a rename is still compared, column by column.

``_compare_tables`` emitted ``RENAME TABLE`` for a paired vanished/appeared table
and moved on: the renamed table's new columns, indexes and constraints were never
compared. The generated migration was one ``ALTER TABLE … RENAME TO`` and the
applied schema lacked everything else the new table declares.
"""

from __future__ import annotations

import pglast

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.platform import diff

_OLD = "CREATE TABLE app.tb_gone (id bigint PRIMARY KEY, title text);"
_NEW = """CREATE TABLE app.tb_post (id bigint PRIMARY KEY, title text, body text, author_id bigint);
CREATE INDEX ix_post_author ON app.tb_post (author_id);"""


def test_the_renamed_table_is_compared_after_the_rename() -> None:
    changes = [type(c).__name__ for c in diff(_OLD, _NEW).changes]

    assert changes[0] == "TableRenamed"
    assert changes.count("ColumnAdded") == 2
    assert "IndexAdded" in changes


def test_the_generated_migration_leaves_the_table_as_the_tree_declares() -> None:
    generator = DifferSQLGenerator()
    up = "".join(generator.generate_up(c) or "" for c in diff(_OLD, _NEW).changes)

    statements = [type(raw.stmt).__name__ for raw in pglast.parse_sql(up)]
    assert statements[0] == "RenameStmt"
    assert statements.count("AlterTableStmt") == 2  # one ADD COLUMN per new column
    assert "IndexStmt" in statements


def test_the_additions_name_the_table_by_its_new_name() -> None:
    added = [c for c in diff(_OLD, _NEW).changes if type(c).__name__ == "ColumnAdded"]

    assert added
    assert all("tb_post" in str(c.to_wire()) for c in added)
