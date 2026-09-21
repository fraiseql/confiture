"""The generator writes the column the schema declared, not a stand-in.

``DifferSQLGenerator`` read a column's type, nullability and default out of
``change.details``. The differ does not put them there: it writes the whole
definition into ``new_value`` for an added column and ``old_value`` for a
dropped one, which is what ``MigrationGenerator`` has always read. So the SQL
generator substituted ``text`` for every added column and declared it could not
restore what it was holding.

Same shape as #316 one kind along: the change carries what the statement needs
and the generator looked in the wrong field.
"""

from __future__ import annotations

from dataclasses import replace

import pglast

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.models.schema import SchemaChange

ONE_COLUMN = ("CREATE TABLE tenant.t (id INT);", "CREATE TABLE tenant.t (id INT, x INT NOT NULL);")


def _change(old: str, new: str, change_type: str) -> SchemaChange:
    return next(c for c in SchemaDiffer().compare(old, new).changes if c.type == change_type)


def _parses(sql: str) -> bool:
    """Whether PostgreSQL's own parser accepts the statement.

    Raises rather than returning False, because the message names the syntax
    error and ``assert _parses(sql)`` would not.
    """
    pglast.parse_sql("\n".join(line.split("--")[0] for line in sql.splitlines()))
    return True


class TestAnAddedColumnKeepsItsDeclaration:
    def test_the_declared_type_is_written(self) -> None:
        sql = DifferSQLGenerator().generate_up(_change(*ONE_COLUMN, "ADD_COLUMN"))
        assert _parses(sql)
        assert sql.strip() == "ALTER TABLE tenant.t ADD COLUMN IF NOT EXISTS x INTEGER NOT NULL;"

    def test_no_column_is_invented_as_text(self) -> None:
        """``text`` was the fallback for a change with no ``details``, which is
        every column change the differ emits. A column of the wrong type is a
        worse artefact than one that does not parse."""
        sql = DifferSQLGenerator().generate_up(_change(*ONE_COLUMN, "ADD_COLUMN"))
        assert "text" not in sql

    def test_the_default_survives(self) -> None:
        sql = DifferSQLGenerator().generate_up(
            _change(
                "CREATE TABLE tenant.t (id INT);",
                "CREATE TABLE tenant.t (id INT, x INT NOT NULL DEFAULT 5);",
                "ADD_COLUMN",
            )
        )
        assert _parses(sql)
        assert "NOT NULL DEFAULT 5" in sql

    def test_a_generated_column_reparses_to_the_column_declared(self) -> None:
        """The round trip, which no field-name assertion can fake."""
        declared = SchemaDiffer().parse_schema(ONE_COLUMN[1]).tables[0].column("x")
        sql = DifferSQLGenerator().generate_up(_change(*ONE_COLUMN, "ADD_COLUMN"))
        regenerated = SchemaDiffer().parse_schema(ONE_COLUMN[0] + "\n" + sql).tables[0]
        # `line` is where each text wrote it, not what it declares.
        assert regenerated.column("x") == replace(declared, line=regenerated.column("x").line)

    def test_structured_details_still_win(self) -> None:
        """A hand-built change may carry the fields separately; that is the older
        shape and the one the method was written for."""
        sql = DifferSQLGenerator().generate_up(
            SchemaChange(
                type="ADD_COLUMN",
                table="tenant.t",
                column="x",
                new_value="INTEGER",
                details={"type": "bigint", "nullable": False, "default": "0"},
            )
        )
        assert _parses(sql)
        assert sql.strip() == (
            "ALTER TABLE tenant.t ADD COLUMN IF NOT EXISTS x bigint NOT NULL DEFAULT 0;"
        )

    def test_a_change_carrying_no_type_warns(self) -> None:
        sql = DifferSQLGenerator().generate_up(
            SchemaChange(type="ADD_COLUMN", table="tenant.t", column="x")
        )
        assert sql.startswith("-- WARNING:")
        assert _parses(sql)


class TestADroppedColumnIsRestoredByItsDown:
    """``DATA_LOSS_TYPES`` already says what a ``DROP_COLUMN`` down means: the
    down file recreates the column, never its rows. The SQL generator said it
    could not recreate it at all, while holding the definition in ``old_value``.
    """

    DROPPED = ("CREATE TABLE tenant.t (id INT, x INT NOT NULL);", "CREATE TABLE tenant.t (id INT);")

    def test_the_down_restores_the_column(self) -> None:
        sql = DifferSQLGenerator().generate_down(_change(*self.DROPPED, "DROP_COLUMN"))
        assert _parses(sql)
        assert "ADD COLUMN IF NOT EXISTS x INTEGER NOT NULL" in sql

    def test_the_down_says_the_rows_do_not_come_back(self) -> None:
        sql = DifferSQLGenerator().generate_down(_change(*self.DROPPED, "DROP_COLUMN"))
        assert "-- review:" in sql

    def test_a_change_carrying_no_definition_still_warns(self) -> None:
        sql = DifferSQLGenerator().generate_down(
            SchemaChange(type="DROP_COLUMN", table="tenant.t", column="x")
        )
        assert sql.startswith("-- WARNING:")


class TestADroppedTableIsRecreatedByItsDown:
    """``DROP_TABLE`` carries the columns — and, since 1.14.0, the constraints.

    ``MigrationGenerator`` has recreated the table from them all along, by
    delegating to this generator's ``ADD_TABLE``. This generator's own ``down``
    declared it could not.
    """

    DROPPED = (
        "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE tenant.t (id INT PRIMARY KEY, pid INT REFERENCES b.parent(id));",
        "CREATE TABLE b.parent (id INT PRIMARY KEY);",
    )

    def test_the_down_recreates_the_table(self) -> None:
        sql = DifferSQLGenerator().generate_down(_change(*self.DROPPED, "DROP_TABLE"))
        assert _parses(sql)
        assert "CREATE TABLE IF NOT EXISTS tenant.t" in sql

    def test_the_recreated_table_keeps_its_constraints(self) -> None:
        sql = DifferSQLGenerator().generate_down(_change(*self.DROPPED, "DROP_TABLE"))
        restored = SchemaDiffer().parse_schema(self.DROPPED[1] + "\n" + sql).tables[1]
        assert [(fk.columns, fk.ref_table) for fk in restored.constraints_of("foreign_key")] == [
            (("pid",), "b.parent")
        ]
        assert [c.name for c in restored.columns if c.primary_key] == ["id"]

    def test_a_change_carrying_no_columns_still_warns(self) -> None:
        sql = DifferSQLGenerator().generate_down(SchemaChange(type="DROP_TABLE", table="tenant.t"))
        assert sql.startswith("-- WARNING:")


class TestBothGeneratorsWriteTheSameColumn:
    """The divergence that hid the defect: one generator read ``new_value`` and
    the other read ``details``, and only one of them was right."""

    def test_the_added_column_definition_agrees(self, tmp_path) -> None:
        from confiture.core.migration_generator import MigrationGenerator

        change = _change(
            "CREATE TABLE tenant.t (id INT);",
            "CREATE TABLE tenant.t (id INT, x INT NOT NULL DEFAULT 5);",
            "ADD_COLUMN",
        )
        sql_gen = DifferSQLGenerator().generate_up(change)
        py_gen = MigrationGenerator(tmp_path)._change_to_up_sql(change)
        assert py_gen is not None
        definition = "x INTEGER NOT NULL DEFAULT 5"
        assert definition in sql_gen
        assert definition in py_gen
