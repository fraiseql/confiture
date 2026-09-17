"""What a statement that is not ``ALTER TABLE`` does to the objects a tree declares.

Four common statements are not ``AlterTableStmt`` and were invisible to every
reader of a DDL tree:

===================================  =========================
``ALTER TABLE t RENAME COLUMN a TO b``  ``RenameStmt``
``ALTER TABLE t RENAME TO t2``          ``RenameStmt``
``ALTER TABLE t SET SCHEMA s2``         ``AlterObjectSchemaStmt``
``DROP TABLE t``                        ``DropStmt``
===================================  =========================

So a tree that created and then dropped a table still expected it — one critical
``missing_table`` on a database that matches the tree exactly — and a tree that
renamed a column expected the old name and called the new one extra. #301's
defect class, one node type over.

``object_edits`` answers for all four in no reader's vocabulary, the way
``column_edit`` answers for the ``ALTER TABLE`` subtypes.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import ObjectEdit, object_edits


def edits_of(sql: str) -> list[ObjectEdit]:
    return object_edits(pglast.parse_sql(sql)[0].stmt)


def test_drop_table() -> None:
    assert edits_of("DROP TABLE core.t") == [
        ObjectEdit("drop", "table", "core", "t"),
    ]


def test_one_statement_can_drop_several_objects() -> None:
    assert edits_of("DROP TABLE a, b") == [
        ObjectEdit("drop", "table", None, "a"),
        ObjectEdit("drop", "table", None, "b"),
    ]


@pytest.mark.parametrize(
    ("sql", "kind", "name"),
    [
        ("DROP VIEW v", "view", "v"),
        ("DROP MATERIALIZED VIEW mv", "matview", "mv"),
        ("DROP SEQUENCE s", "sequence", "s"),
        ("DROP TYPE t", "type", "t"),
        ("DROP DOMAIN d", "domain", "d"),
        ("DROP INDEX ix", "index", "ix"),
        ("DROP SCHEMA s", "schema", "s"),
        ("DROP EXTENSION citext", "extension", "citext"),
    ],
)
def test_drop_reads_the_object_kind(sql: str, kind: str, name: str) -> None:
    assert edits_of(sql) == [ObjectEdit("drop", kind, None, name)]


def test_drop_routine_carries_its_argument_types() -> None:
    """A routine is identified by its arguments, so a drop has to name them."""
    (edit,) = edits_of("DROP FUNCTION core.f(bigint)")
    assert (edit.kind, edit.object_kind, edit.schema, edit.name) == (
        "drop",
        "function",
        "core",
        "f",
    )
    assert edit.arg_types == ("int8",)


def test_drop_if_exists_is_the_same_edit() -> None:
    assert edits_of("DROP TABLE IF EXISTS core.t") == [ObjectEdit("drop", "table", "core", "t")]


def test_a_drop_of_a_kind_no_expected_schema_models_is_no_edit() -> None:
    assert edits_of("DROP ROLE r") == []
    assert edits_of("DROP DATABASE d") == []


def test_rename_column() -> None:
    assert edits_of("ALTER TABLE core.t RENAME COLUMN a TO b") == [
        ObjectEdit("rename_column", "table", "core", "t", column="a", new_name="b"),
    ]


def test_rename_table() -> None:
    assert edits_of("ALTER TABLE core.t RENAME TO t2") == [
        ObjectEdit("rename", "table", "core", "t", new_name="t2"),
    ]


def test_rename_view() -> None:
    assert edits_of("ALTER VIEW core.v RENAME TO v2") == [
        ObjectEdit("rename", "view", "core", "v", new_name="v2"),
    ]


def test_a_rename_of_a_kind_no_expected_schema_models_is_no_edit() -> None:
    """The decision a reader gets wrong: ``RenameStmt`` spans far more than tables.

    Its ``renameType`` covers constraints, roles, tablespaces and the columns of
    a composite type. Folding those would invent objects, so they are no edit.
    """
    assert edits_of("ALTER TABLE t RENAME CONSTRAINT c TO c2") == []
    assert edits_of("ALTER ROLE r RENAME TO r2") == []
    assert edits_of("ALTER TABLESPACE ts RENAME TO ts2") == []


def test_a_per_table_object_is_keyed_table_first() -> None:
    """A trigger name is unique per table, not per schema, so ``t.trg`` is the name.

    That is how ``ddl_objects`` keys one, and two tables may each carry a
    ``trg_touch``.
    """
    assert edits_of("DROP TRIGGER trg ON core.t") == [
        ObjectEdit("drop", "trigger", "core", "t.trg"),
    ]
    assert edits_of("DROP POLICY p ON core.t") == [ObjectEdit("drop", "policy", "core", "t.p")]
    assert edits_of("ALTER TRIGGER trg ON core.t RENAME TO trg2") == [
        ObjectEdit("rename", "trigger", "core", "t.trg", new_name="t.trg2"),
    ]


def test_a_routine_dropped_without_an_argument_list_matches_any_overload() -> None:
    (edit,) = edits_of("DROP FUNCTION core.f")
    assert edit.arg_types is None


def test_set_schema() -> None:
    assert edits_of("ALTER TABLE core.t SET SCHEMA archive") == [
        ObjectEdit("set_schema", "table", "core", "t", new_schema="archive"),
    ]


def test_set_schema_of_a_view() -> None:
    assert edits_of("ALTER VIEW core.v SET SCHEMA archive") == [
        ObjectEdit("set_schema", "view", "core", "v", new_schema="archive"),
    ]


def test_a_statement_that_changes_no_declared_object_is_no_edit() -> None:
    assert edits_of("CREATE TABLE t (a int)") == []
    assert edits_of("ALTER TABLE t ADD COLUMN a int") == []
    assert edits_of("GRANT SELECT ON t TO r") == []


def test_drop_routine_may_name_a_function_a_procedure_or_an_aggregate() -> None:
    """``DROP ROUTINE`` does not say which, and a reader of a tree cannot know."""
    from confiture.core.ddl_walk import object_kinds

    (edit,) = edits_of("DROP ROUTINE core.f(bigint)")
    assert edit.object_kind == "routine"
    assert object_kinds(edit.object_kind) == ("function", "procedure", "aggregate")
    assert object_kinds("table") == ("table",)
