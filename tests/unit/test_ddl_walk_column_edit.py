"""What one ``AlterTableCmd`` does to a table's columns, in no reader's vocabulary.

``core/ddl_walk.column_edit`` is the one place that decides it. Two readers fold
`ALTER TABLE` into an expected schema — the lint inventory and the differ — over
object models that share nothing (a `ColumnType` enum and a `raw_sql_type` on one
side, `type_text` as written on the other), so what they can share is the
*decision*, not the application of it.

Every subtype is resolved by name through ``core/_pglast_enums``: PostgreSQL 18
inserted a member into ``AlterTableType`` and pglast 8 renumbered everything at
index >= 13 down by one, so a literal ordinal stops matching silently and the
branch is simply never taken (#192).
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import column_edit, type_name
from confiture.core.type_lattice import canonical_type


def cmd_of(sql: str, index: int = 0):
    """The *index*-th ``AlterTableCmd`` of a one-statement ``ALTER TABLE``."""
    stmt = pglast.parse_sql(sql)[0].stmt
    return stmt.cmds[index]


def test_add_column_names_the_column_in_its_coldef() -> None:
    edit = column_edit(cmd_of("ALTER TABLE t ADD COLUMN a int"))
    assert edit is not None
    assert edit.kind == "add"
    assert edit.coldef is not None
    assert edit.coldef.colname == "a"


def test_drop_column_names_the_column() -> None:
    edit = column_edit(cmd_of("ALTER TABLE t DROP COLUMN b"))
    assert edit is not None
    assert (edit.kind, edit.column) == ("drop", "b")


def test_retype_reads_the_column_from_the_cmd_and_the_type_from_the_coldef() -> None:
    """``AT_AlterColumnType`` puts the name on ``cmd.name``, not in the ``ColumnDef``.

    ``AT_AddColumn`` does the opposite. Getting it backwards yields an edit that
    applies to nothing and reports no error.
    """
    edit = column_edit(cmd_of("ALTER TABLE t ALTER COLUMN c TYPE bigint"))
    assert edit is not None
    assert (edit.kind, edit.column) == ("retype", "c")
    # `type_name` keeps PostgreSQL's internal spelling on purpose — pglast
    # records `TYPE bigint` as `pg_catalog.int8` — and leaves the aliasing to
    # the one canonicaliser, which is how both callers read it.
    assert type_name(edit.coldef.typeName) == "int8"
    assert canonical_type(type_name(edit.coldef.typeName)) == "bigint"


def test_a_subtype_this_module_does_not_model_is_none() -> None:
    """``None``, never a silently-empty edit — that is how #192 lost an operation."""
    assert column_edit(cmd_of("ALTER TABLE t OWNER TO someone")) is None


@pytest.mark.parametrize(
    ("sql", "kind", "column"),
    [
        ("ALTER TABLE t ADD COLUMN a int", "add", None),
        ("ALTER TABLE t DROP COLUMN b", "drop", "b"),
        ("ALTER TABLE t ALTER COLUMN c TYPE bigint", "retype", "c"),
    ],
)
def test_the_kind_and_the_column(sql: str, kind: str, column: str | None) -> None:
    edit = column_edit(cmd_of(sql))
    assert edit is not None
    assert (edit.kind, edit.column) == (kind, column)


def test_add_column_if_not_exists_is_the_same_edit() -> None:
    """``missing_ok`` is deliberately not carried — see ``ColumnEdit``'s docstring."""
    edit = column_edit(cmd_of("ALTER TABLE t ADD COLUMN IF NOT EXISTS a int"))
    assert edit is not None
    assert edit.kind == "add"
