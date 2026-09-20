"""A change names the table it changes, and so does the DDL generated from it (#313).

Detection and generation are two problems. Even with no collision anywhere,
1.12.0 detected a change in ``tenant.t`` and generated ``ALTER TABLE t`` — a
statement that resolves through ``search_path`` at apply time, which is not
necessarily where the change was detected.

The assertions here parse the generated SQL rather than matching strings: a
syntax error is exactly the failure mode a qualifier introduces, and a string
assertion cannot see one.
"""

from __future__ import annotations

from typing import ClassVar

import pglast

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.models.schema import SchemaChange


def _changes(old: str, new: str) -> list[SchemaChange]:
    return SchemaDiffer().compare(old, new).changes


def _by_type(changes: list[SchemaChange], change_type: str) -> SchemaChange:
    return next(c for c in changes if c.type == change_type)


class TestAChangeCarriesTheSpellingTheAuthorWrote:
    def test_add_column_names_the_qualified_table(self) -> None:
        change = _by_type(
            _changes("CREATE TABLE tenant.t (id INT);", "CREATE TABLE tenant.t (id INT, x TEXT);"),
            "ADD_COLUMN",
        )
        assert change.table == "tenant.t"

    def test_add_index_names_the_qualified_table(self) -> None:
        change = _by_type(
            _changes(
                "CREATE TABLE tenant.t (id INT, x TEXT);",
                "CREATE TABLE tenant.t (id INT, x TEXT);\nCREATE INDEX ix ON tenant.t (x);",
            ),
            "ADD_INDEX",
        )
        assert change.table == "tenant.t"

    def test_add_foreign_key_names_both_qualified_tables(self) -> None:
        old = "CREATE TABLE b.parent (id INT PRIMARY KEY);\nCREATE TABLE a.child (pid INT);"
        new = (
            "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
            "CREATE TABLE a.child (pid INT, CONSTRAINT fk_c FOREIGN KEY (pid)"
            " REFERENCES b.parent(id));"
        )
        change = _by_type(_changes(old, new), "ADD_FOREIGN_KEY")
        assert change.table == "a.child"
        assert (change.details or {})["ref_table"] == "b.parent"

    def test_an_unqualified_tree_is_unchanged(self) -> None:
        old = "CREATE TABLE tb_post (id INT);"
        new = "CREATE TABLE tb_post (id INT, x TEXT);\nCREATE INDEX ix ON tb_post (x);"
        assert sorted(str(c) for c in _changes(old, new)) == [
            "ADD COLUMN tb_post.x",
            "ADD INDEX ix ON tb_post",
        ]


class TestTheConstraintModelsKeepTheSchema:
    def test_an_index_carries_its_table_qualified(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE tenant.t (id INT);\nCREATE INDEX ix ON tenant.t (id);"
        )
        assert parsed.tables[0].indexes[0].table == "tenant.t"

    def test_a_foreign_key_carries_the_referenced_schema(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
            "CREATE TABLE a.child (pid INT, CONSTRAINT fk_c FOREIGN KEY (pid)"
            " REFERENCES b.parent(id));"
        )
        fk = parsed.tables[1].foreign_keys[0]
        assert (fk.table, fk.ref_table) == ("a.child", "b.parent")

    def test_an_alter_table_foreign_key_carries_the_referenced_schema(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
            "CREATE TABLE a.child (pid INT);\n"
            "ALTER TABLE a.child ADD CONSTRAINT fk_c FOREIGN KEY (pid) REFERENCES b.parent(id);"
        )
        fk = parsed.tables[1].foreign_keys[0]
        assert (fk.table, fk.ref_table) == ("a.child", "b.parent")

    def test_check_and_unique_constraints_carry_the_qualified_table(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0),"
            " CONSTRAINT uq UNIQUE (id));"
        )
        table = parsed.tables[0]
        assert table.check_constraints[0].table == "tenant.t"
        assert table.unique_constraints[0].table == "tenant.t"

    def test_an_unqualified_table_keeps_a_bare_constraint_table(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE t (id INT, CONSTRAINT uq UNIQUE (id));\nCREATE INDEX ix ON t (id);"
        )
        assert parsed.tables[0].unique_constraints[0].table == "t"
        assert parsed.tables[0].indexes[0].table == "t"


class TestBothGeneratorsEmitWhatParses:
    """Every statement either generator writes for a qualified schema must parse.

    Asserted by parsing, not by matching strings: a syntax error is exactly the
    failure mode a qualifier introduces, and a string assertion cannot see one.
    """

    OLD = (
        "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE tenant.t (id INT, old_col TEXT);\n"
        "CREATE TABLE tenant.gone (id INT);\n"
        "CREATE TABLE tenant.tb_a (id INT);\n"
    )
    NEW = (
        "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE tenant.t (id INT, old_col TEXT NOT NULL, pid INT,"
        " CONSTRAINT fk_c FOREIGN KEY (pid) REFERENCES b.parent(id),"
        " CONSTRAINT ck CHECK (id > 0), CONSTRAINT uq UNIQUE (id));\n"
        "CREATE INDEX ix ON tenant.t (old_col);\n"
        "CREATE TABLE tenant.tb_b (id INT);\n"
        "CREATE TABLE etl.fresh (id INT);\n"
    )

    #: Change kinds whose generated DDL does **not** parse, and why. A defect
    #: that pre-dates #313 and is orthogonal to it; the entry is a reason, and a
    #: kind that starts parsing fails the test below, so the table cannot
    #: outlive what it excuses.
    NOT_YET_PARSEABLE: ClassVar[dict[str, str]] = {
        "ADD_CHECK_CONSTRAINT": (
            "`_parse_table_constraint_pglast` stores the expression's *node type "
            "name* as a placeholder (`A_Expr`) because the comparison only ever "
            "needed identity, and `_up_add_constraint` then appends an empty "
            "column list: `ALTER TABLE t ADD CONSTRAINT ck CHECK (A_Expr) ()`."
        ),
    }

    def _statements(self, tmp_path) -> list[tuple[str, str]]:
        """Every (change type, statement) both generators write for this diff."""
        from confiture.core.migration_generator import MigrationGenerator

        sql_generator = DifferSQLGenerator(force_destructive=True)
        py_generator = MigrationGenerator(tmp_path)
        emitted: list[tuple[str, str]] = []
        for change in _changes(self.OLD, self.NEW):
            for produce in (
                sql_generator.generate_up,
                sql_generator.generate_down,
                py_generator._change_to_up_sql,
                py_generator._change_to_down_sql,
            ):
                try:
                    sql = produce(change)
                except NotImplementedError:
                    continue  # a kind with no generator writes nothing, and that parses
                if sql:
                    emitted.append((change.type, sql))
        return emitted

    def test_only_the_excused_kinds_fail_to_parse(self, tmp_path) -> None:
        unparseable: set[str] = set()
        seen: set[str] = set()
        for change_type, sql in self._statements(tmp_path):
            seen.add(change_type)
            try:
                pglast.parse_sql(_without_comments(sql))
            except pglast.parser.ParseError:
                unparseable.add(change_type)
        assert unparseable == set(self.NOT_YET_PARSEABLE)
        assert set(self.NOT_YET_PARSEABLE) <= seen, "an excused kind is no longer generated"

    def test_the_diff_exercises_every_shape_this_campaign_touches(self, tmp_path) -> None:
        """A sweep that stopped covering a kind would pass by emitting nothing."""
        assert {change_type for change_type, _ in self._statements(tmp_path)} >= {
            "RENAME_TABLE",
            "ADD_TABLE",
            "DROP_TABLE",
            "ADD_COLUMN",
            "ADD_INDEX",
            "ADD_FOREIGN_KEY",
            "ADD_UNIQUE_CONSTRAINT",
        }

    def test_rename_table_generates_a_qualified_source_and_a_bare_target(self, tmp_path) -> None:
        from confiture.core.migration_generator import MigrationGenerator

        change = _by_type(_changes(self.OLD, self.NEW), "RENAME_TABLE")
        generator = MigrationGenerator(tmp_path)
        up = generator._change_to_up_sql(change)
        down = generator._change_to_down_sql(change)
        assert up == "ALTER TABLE tenant.tb_a RENAME TO tb_b"
        assert down == "ALTER TABLE tenant.tb_b RENAME TO tb_a"
        pglast.parse_sql(up)
        pglast.parse_sql(down)

    def test_an_unqualified_rename_generates_what_it_always_did(self, tmp_path) -> None:
        from confiture.core.migration_generator import MigrationGenerator

        change = _by_type(
            _changes("CREATE TABLE tb_a (id INT);", "CREATE TABLE tb_b (id INT);"),
            "RENAME_TABLE",
        )
        generator = MigrationGenerator(tmp_path)
        assert generator._change_to_up_sql(change) == "ALTER TABLE tb_a RENAME TO tb_b"
        assert generator._change_to_down_sql(change) == "ALTER TABLE tb_b RENAME TO tb_a"


def _without_comments(sql: str) -> str:
    """The generator writes ``-- WARNING:`` lines that carry no statement."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return "\n".join(lines) or "SELECT 1"
