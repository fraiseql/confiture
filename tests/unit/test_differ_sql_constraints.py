"""Every constraint statement the generator writes parses, and says what the schema said.

A generated migration is *applied*. A statement that does not parse fails the
deploy; a statement that parses and drops half of what the schema declared —
a referential action, a referenced column list — succeeds and is wrong. The
second is worse, so both are asserted here.

Asserted by parsing with pglast and, where the question is "did confiture invent
something", by reading the generated statement back through ``SchemaDiffer``:
a name confiture made up comes back as a name.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    CheckConstraintAdded,
    ForeignKeyAdded,
    ForeignKeyDropped,
    SchemaChange,
    TableAdded,
    UniqueConstraintAdded,
)
from confiture.core.schema_model import Constraint

PARENT = "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"


def _up(old: str, new: str, kind: type[SchemaChange]) -> str:
    change = next(c for c in SchemaDiffer().compare(old, new).changes if isinstance(c, kind))
    return DifferSQLGenerator(force_destructive=True).generate_up(change)


def _parses(sql: str) -> bool:
    """Whether PostgreSQL's own parser accepts the generated statement.

    It raises rather than returning False, because the message names the syntax
    error and ``assert _parses(sql)`` would not.
    """
    pglast.parse_sql(_without_comments(sql))
    return True


def _without_comments(sql: str) -> str:
    return "\n".join(line.split("--")[0] for line in sql.splitlines())


class TestACheckConstraintIsGeneratedAsItsExpression:
    """#316: ``CHECK (A_Expr) ()`` — the AST class name, then an empty column list."""

    def test_an_added_check_generates_ddl_that_parses(self) -> None:
        sql = _up(
            "CREATE TABLE tenant.t (id INT);",
            "CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0));",
            CheckConstraintAdded,
        )
        assert _parses(sql)
        assert sql.strip() == "ALTER TABLE tenant.t ADD CONSTRAINT ck CHECK (id > 0);"

    def test_a_check_has_no_column_list(self) -> None:
        sql = _up(
            "CREATE TABLE tenant.t (id INT);",
            "CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0));",
            CheckConstraintAdded,
        )
        assert "()" not in sql

    def test_a_check_with_no_expression_is_a_warning_not_empty_parentheses(self) -> None:
        generator = DifferSQLGenerator()
        sql = generator.generate_up(
            CheckConstraintAdded("tenant.t", Constraint(kind="check", name="ck", expression=""))
        )
        assert sql.startswith("-- WARNING:")
        assert _without_comments(sql).strip() == ""


class TestTheReferencedSideIsGeneratedAsWritten:
    def test_a_reference_with_no_column_list_generates_no_empty_parentheses(self) -> None:
        sql = _up(
            PARENT + "CREATE TABLE a.child (pid INT);",
            PARENT + "CREATE TABLE a.child (pid INT,"
            " CONSTRAINT fk FOREIGN KEY (pid) REFERENCES b.parent);",
            ForeignKeyAdded,
        )
        assert _parses(sql)
        assert "b.parent()" not in sql

    def test_the_referenced_columns_are_rendered_when_written(self) -> None:
        sql = _up(
            PARENT + "CREATE TABLE a.child (pid INT);",
            PARENT + "CREATE TABLE a.child (pid INT,"
            " CONSTRAINT fk FOREIGN KEY (pid) REFERENCES b.parent(id));",
            ForeignKeyAdded,
        )
        assert _parses(sql)
        assert "REFERENCES b.parent (id)" in sql

    @pytest.mark.parametrize(
        ("clause", "rendered"),
        [
            ("ON DELETE CASCADE", "ON DELETE CASCADE"),
            ("ON DELETE SET NULL", "ON DELETE SET NULL"),
            ("ON UPDATE RESTRICT", "ON UPDATE RESTRICT"),
        ],
    )
    def test_a_referential_action_survives_into_the_migration(
        self, clause: str, rendered: str
    ) -> None:
        """A generated foreign key that silently stops cascading applies cleanly
        and is wrong, which is worse than one that does not parse."""
        sql = _up(
            PARENT + "CREATE TABLE a.child (pid INT);",
            PARENT + "CREATE TABLE a.child (pid INT, CONSTRAINT fk FOREIGN KEY (pid)"
            f" REFERENCES b.parent(id) {clause});",
            ForeignKeyAdded,
        )
        assert _parses(sql)
        assert rendered in sql

    def test_no_action_writes_no_clause(self) -> None:
        sql = _up(
            PARENT + "CREATE TABLE a.child (pid INT);",
            PARENT + "CREATE TABLE a.child (pid INT, CONSTRAINT fk FOREIGN KEY (pid)"
            " REFERENCES b.parent(id) ON DELETE NO ACTION);",
            ForeignKeyAdded,
        )
        assert _parses(sql)
        assert "ON DELETE" not in sql


class TestAnUnnamedConstraintIsGeneratedUnnamed:
    """PostgreSQL names it at apply time, the same way it would have named the
    author's. Writing ``child_pid_fkey`` here would be confiture inventing an
    identifier — the defect the ``-- WARNING:`` idiom exists to prevent."""

    ADDED_UNNAMED_FK = (
        PARENT + "CREATE TABLE a.child (pid INT);",
        PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id));",
    )

    def test_it_parses(self) -> None:
        assert _parses(_up(*self.ADDED_UNNAMED_FK, ForeignKeyAdded))

    def test_it_carries_no_constraint_clause(self) -> None:
        sql = _up(*self.ADDED_UNNAMED_FK, ForeignKeyAdded)
        assert "CONSTRAINT" not in _without_comments(sql)

    def test_reading_it_back_finds_no_invented_name(self) -> None:
        sql = _up(*self.ADDED_UNNAMED_FK, ForeignKeyAdded)
        parsed = SchemaDiffer().parse_schema(
            PARENT + "CREATE TABLE a.child (pid INT);\n" + _without_comments(sql)
        )
        assert [fk.name for fk in parsed.tables[1].constraints_of("foreign_key")] == [""]

    def test_it_says_why_it_is_not_validated_separately(self) -> None:
        """``NOT VALID`` is only useful with a matching ``VALIDATE CONSTRAINT``,
        which needs the name. The lock difference is stated, not hidden."""
        sql = _up(*self.ADDED_UNNAMED_FK, ForeignKeyAdded)
        assert "NOT VALID" not in _without_comments(sql)
        assert "-- review:" in sql

    def test_an_unnamed_unique_constraint_parses(self) -> None:
        assert _parses(
            _up(
                "CREATE TABLE tenant.t (u INT);",
                "CREATE TABLE tenant.t (u INT UNIQUE);",
                UniqueConstraintAdded,
            )
        )

    def test_an_unnamed_check_constraint_parses(self) -> None:
        assert _parses(
            _up(
                "CREATE TABLE tenant.t (c INT);",
                "CREATE TABLE tenant.t (c INT CHECK (c > 0));",
                CheckConstraintAdded,
            )
        )

    def test_dropping_an_unnamed_constraint_is_a_warning(self) -> None:
        """``DROP CONSTRAINT`` takes a name and confiture does not have one.

        This is the case the ``-- WARNING:`` idiom is for, and the one place the
        generator must not guess: guessing wrong drops the wrong constraint.
        """
        sql = _up(
            PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id));",
            PARENT + "CREATE TABLE a.child (pid INT);",
            ForeignKeyDropped,
        )
        assert sql.startswith("-- WARNING:")
        assert _without_comments(sql).strip() == ""


class TestANewTableIsGeneratedWhole:
    """``_up_add_table`` rendered the columns and nothing else.

    A new table's foreign keys, CHECKs, UNIQUEs and primary key were dropped
    from the generated ``CREATE TABLE`` — measured true for the table-level
    spellings too, so it pre-dates #315 and would have outlived it: a
    column-level foreign key on a *new* table would still have vanished.

    The assertion is a round trip. Generate, parse the result back through
    ``SchemaDiffer``, and compare the models: anything the generator drops or
    invents shows up as a difference.
    """

    DECLARED = (
        PARENT + "CREATE TABLE a.child (\n"
        "  pk INT PRIMARY KEY,\n"
        "  pid INT REFERENCES b.parent(id) ON DELETE CASCADE,\n"
        "  named INT,\n"
        "  u INT UNIQUE,\n"
        "  c INT CHECK (c > 0),\n"
        "  CONSTRAINT fk_named FOREIGN KEY (named) REFERENCES b.parent(id),\n"
        "  CONSTRAINT uq_named UNIQUE (named),\n"
        "  CONSTRAINT ck_named CHECK (named > 0)\n"
        ");"
    )

    def _regenerated(self) -> tuple[object, object]:
        differ = SchemaDiffer()
        declared = differ.parse_schema(self.DECLARED).tables[1]
        sql = _up(PARENT, self.DECLARED, TableAdded)
        assert _parses(sql)
        return declared, SchemaDiffer().parse_schema(PARENT + sql).tables[1]

    def test_the_columns_round_trip(self) -> None:
        declared, regenerated = self._regenerated()
        assert regenerated.columns == declared.columns  # ty: ignore[unresolved-attribute]

    def test_the_foreign_keys_round_trip(self) -> None:
        declared, regenerated = self._regenerated()
        assert regenerated.constraints_of("foreign_key") == declared.constraints_of("foreign_key")  # ty: ignore[unresolved-attribute]

    def test_the_check_constraints_round_trip(self) -> None:
        declared, regenerated = self._regenerated()
        assert (
            regenerated.constraints_of("check")  # ty: ignore[unresolved-attribute]
            == declared.constraints_of("check")  # ty: ignore[unresolved-attribute]
        )

    def test_the_unique_constraints_round_trip(self) -> None:
        declared, regenerated = self._regenerated()
        assert (
            regenerated.constraints_of("unique")  # ty: ignore[unresolved-attribute]
            == declared.constraints_of("unique")  # ty: ignore[unresolved-attribute]
        )

    def test_a_table_with_no_constraints_is_unchanged(self) -> None:
        sql = _up("", "CREATE TABLE tenant.t (id INT);", TableAdded)
        assert sql.strip() == "CREATE TABLE IF NOT EXISTS tenant.t (\n    id INTEGER\n);"
