"""A tree that drops, renames or moves an object declares the result, not the statement.

``build_inventory`` folded ``ALTER TABLE`` and nothing else, so a table the tree
created and then dropped was still in the expected schema, a renamed column was
still expected under its old name, and a table moved to another schema was
expected in both. Every one of those is a drift item on a database that matches
the tree exactly.
"""

from confiture.core.schema_read import read_text


def test_a_table_created_and_dropped_is_not_declared() -> None:
    inventory = read_text("CREATE TABLE core.t (a int); DROP TABLE core.t;").inventory
    assert inventory.tables == []


def test_the_everyday_drop_if_exists_then_create_idiom_declares_the_table() -> None:
    """``DROP TABLE IF EXISTS x; CREATE TABLE x (…);`` is ordinary DDL.

    ``build_inventory`` collects every ``CREATE`` before it folds anything, so an
    order-blind fold would delete a table the tree really does declare — a
    *false* ``missing_table`` on a correct database, which is the defect this
    campaign is closing rather than one to introduce.
    """
    inventory = read_text("DROP TABLE IF EXISTS core.t; CREATE TABLE core.t (a int);").inventory
    assert [table.folded_name for table in inventory.tables] == ["t"]


def test_a_table_recreated_after_its_drop_is_the_one_declared() -> None:
    """The statement's position decides, both ways."""
    inventory = read_text(
        "CREATE TABLE core.t (a int); DROP TABLE core.t; CREATE TABLE core.t (b text);"
    ).inventory
    assert [[column.folded for column in table.columns] for table in inventory.tables] == [["b"]]


def test_dropping_one_of_several_leaves_the_others() -> None:
    inventory = read_text(
        "CREATE TABLE a (x int); CREATE TABLE b (x int); CREATE TABLE c (x int); DROP TABLE a, c;"
    ).inventory
    assert [table.folded_name for table in inventory.tables] == ["b"]


def test_a_view_created_and_dropped_is_not_declared() -> None:
    inventory = read_text("CREATE VIEW core.v AS SELECT 1; DROP VIEW core.v;").inventory
    assert [obj.folded_name for obj in inventory.objects] == []


def test_a_routine_created_and_dropped_is_not_declared() -> None:
    inventory = read_text(
        "CREATE FUNCTION core.f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
        "DROP FUNCTION core.f();"
    ).inventory
    assert inventory.objects == []


def test_a_dropped_overload_leaves_its_sibling() -> None:
    """A routine's identity is its arguments, so a drop names one overload."""
    inventory = read_text(
        "CREATE FUNCTION f(a int) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
        "CREATE FUNCTION f(a bigint) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
        "DROP FUNCTION f(int);"
    ).inventory
    assert [obj.signature for obj in inventory.objects] == ["bigint"]


def test_a_routine_dropped_without_arguments_takes_every_overload() -> None:
    """``DROP FUNCTION f`` names no argument list; PostgreSQL accepts it when
    there is exactly one, and an expected schema has no more right to guess
    which than PostgreSQL does."""
    inventory = read_text(
        "CREATE FUNCTION f(a int) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$; DROP FUNCTION f;"
    ).inventory
    assert inventory.objects == []


def test_a_renamed_column_is_declared_under_its_new_name() -> None:
    table = read_text(
        "CREATE TABLE core.t (id int, old_name text);"
        "ALTER TABLE core.t RENAME COLUMN old_name TO new_name;"
    ).inventory.find("core", "t")
    assert table is not None
    assert [column.folded for column in table.columns] == ["id", "new_name"]


def test_a_renamed_table_is_declared_under_its_new_name() -> None:
    inventory = read_text("CREATE TABLE core.t (a int); ALTER TABLE core.t RENAME TO t2;").inventory
    assert [(t.folded_schema, t.folded_name) for t in inventory.tables] == [("core", "t2")]


def test_a_moved_table_is_declared_in_its_new_schema() -> None:
    inventory = read_text(
        "CREATE TABLE core.t (a int); ALTER TABLE core.t SET SCHEMA archive;"
    ).inventory
    assert [(t.folded_schema, t.folded_name) for t in inventory.tables] == [("archive", "t")]


def test_a_statement_naming_something_the_tree_never_created_changes_nothing() -> None:
    """It belongs to a schema built elsewhere — the same rule ``ALTER TABLE`` follows."""
    inventory = read_text("CREATE TABLE core.t (a int); DROP TABLE elsewhere.absent;").inventory
    assert [table.folded_name for table in inventory.tables] == ["t"]


def test_a_dropped_schema_is_not_declared() -> None:
    inventory = read_text("CREATE SCHEMA core; DROP SCHEMA core;").inventory
    assert inventory.schemas == []
