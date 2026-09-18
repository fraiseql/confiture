"""``SchemaDiffer`` reads a drop, a rename and a schema move the way the inventory does.

Both walkers read the same DDL tree for the same purpose — what schema does this
tree declare — so a statement one folds and the other does not is a disagreement
about the tree, which is how #301 happened in the first place. The decision is
``ddl_walk.object_edits``; only the application differs.
"""

from __future__ import annotations

from confiture.core.differ import SchemaDiffer


def tables_of(sql: str) -> list[str]:
    return [table.name for table in SchemaDiffer().parse_schema(sql).tables]


def test_a_table_created_and_dropped_is_not_declared() -> None:
    assert tables_of("CREATE TABLE t (a int); DROP TABLE t;") == []


def test_the_drop_if_exists_then_create_idiom_declares_the_table() -> None:
    assert tables_of("DROP TABLE IF EXISTS t; CREATE TABLE t (a int);") == ["t"]


def test_dropping_one_of_several_leaves_the_others() -> None:
    assert tables_of(
        "CREATE TABLE a (x int); CREATE TABLE b (x int); CREATE TABLE c (x int); DROP TABLE a, c;"
    ) == ["b"]


def test_a_renamed_table_is_declared_under_its_new_name() -> None:
    assert tables_of("CREATE TABLE t (a int); ALTER TABLE t RENAME TO t2;") == ["t2"]


def test_a_renamed_column_is_declared_under_its_new_name() -> None:
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (id int, old_name text); ALTER TABLE t RENAME COLUMN old_name TO new_name;"
    )
    assert [column.name for column in parsed.tables[0].columns] == ["id", "new_name"]


def test_a_dropped_enum_type_and_sequence_are_not_declared() -> None:
    """The differ's own models, which the inventory does not hold."""
    parsed = SchemaDiffer().parse_schema(
        "CREATE TYPE mood AS ENUM ('ok'); DROP TYPE mood;CREATE SEQUENCE s; DROP SEQUENCE s;"
    )
    assert parsed.enum_types == []
    assert parsed.sequences == []


def test_a_dropped_index_is_not_declared() -> None:
    parsed = SchemaDiffer().parse_schema(
        "CREATE TABLE t (a int); CREATE INDEX ix ON t (a); DROP INDEX ix;"
    )
    assert parsed.tables[0].indexes == []


def test_a_statement_naming_something_this_tree_never_created_changes_nothing() -> None:
    assert tables_of("CREATE TABLE t (a int); DROP TABLE absent;") == ["t"]


def test_a_tree_with_no_such_statement_is_unchanged() -> None:
    """The control: the overwhelmingly common tree must parse exactly as before."""
    sql = """
    CREATE TABLE tb_machine (pk_machine UUID PRIMARY KEY, name TEXT NOT NULL);
    CREATE INDEX ix_machine_name ON tb_machine (name);
    CREATE VIEW v_machine AS SELECT pk_machine FROM tb_machine;
    """
    parsed = SchemaDiffer().parse_schema(sql)
    assert [table.name for table in parsed.tables] == ["tb_machine"]
    assert [index.name for index in parsed.tables[0].indexes] == ["ix_machine_name"]
    assert len(parsed.objects) == 1
