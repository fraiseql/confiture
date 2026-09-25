"""An ``EXCLUDE`` constraint is modelled, compared, generated and drift-checked (#322).

It was the one constraint kind the model declined by name: the table parsed clean,
adding one reported nothing in either spelling, and a new table's generated
``CREATE TABLE`` dropped it.
"""

from __future__ import annotations

import pglast

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import ExclusionConstraintAdded, ExclusionConstraintDropped
from confiture.core.schema_model import Constraint

EXCL = (
    "CREATE TABLE tenant.tb_booking (\n"
    "  room_id INT,\n"
    "  during TSRANGE,\n"
    "  CONSTRAINT no_overlap EXCLUDE USING gist (room_id WITH =, during WITH &&)\n"
    ");\n"
)
WITHOUT = "CREATE TABLE tenant.tb_booking (room_id INT, during TSRANGE);\n"
BY_ALTER = WITHOUT + (
    "ALTER TABLE tenant.tb_booking ADD CONSTRAINT no_overlap"
    " EXCLUDE USING gist (room_id WITH =, during WITH &&);\n"
)

NO_OVERLAP = Constraint(
    kind="exclusion",
    name="no_overlap",
    columns=("room_id", "during"),
    operators=("=", "&&"),
    method="gist",
)


class TestTheModelHoldsIt:
    def test_a_table_level_one(self) -> None:
        (table,) = SchemaDiffer().parse_schema(EXCL).tables
        assert table.constraints == (NO_OVERLAP,)

    def test_one_added_by_alter(self) -> None:
        (table,) = SchemaDiffer().parse_schema(BY_ALTER).tables
        assert table.constraints == (NO_OVERLAP,)

    def test_an_expression_a_qualified_operator_and_a_predicate(self) -> None:
        sql = (
            "CREATE TABLE t (r TSRANGE, k INT, EXCLUDE USING gist"
            " ((lower(r)) WITH OPERATOR(pg_catalog.=), k WITH =) WHERE (k > 0) DEFERRABLE);"
        )
        (table,) = SchemaDiffer().parse_schema(sql).tables
        assert table.constraints == (
            Constraint(
                kind="exclusion",
                columns=("lower(r)", "k"),
                operators=("OPERATOR(pg_catalog.=)", "="),
                method="gist",
                where="k > 0",
                deferrable="immediate",
            ),
        )

    def test_the_parser_still_holds_what_the_reader_reads(self) -> None:
        node = pglast.parse_sql(EXCL)[0].stmt.tableElts[2]
        assert node.access_method == "gist"
        assert [len(pair) for pair in node.exclusions] == [2, 2]


class TestAddingOneIsAChange:
    def _changes(self, old: str, new: str) -> list:
        return SchemaDiffer().compare(old, new).changes

    def test_the_create_table_spelling(self) -> None:
        (change,) = self._changes(WITHOUT, EXCL)
        assert change == ExclusionConstraintAdded("tenant.tb_booking", NO_OVERLAP)

    def test_the_alter_table_spelling(self) -> None:
        (change,) = self._changes(WITHOUT, BY_ALTER)
        assert change == ExclusionConstraintAdded("tenant.tb_booking", NO_OVERLAP)

    def test_dropping_one(self) -> None:
        (change,) = self._changes(EXCL, WITHOUT)
        assert change == ExclusionConstraintDropped("tenant.tb_booking", NO_OVERLAP)

    def test_two_unnamed_ones_are_two(self) -> None:
        new = (
            "CREATE TABLE tenant.tb_booking (room_id INT, during TSRANGE,"
            " EXCLUDE USING gist (during WITH &&), EXCLUDE USING gist (room_id WITH =));\n"
        )
        assert [type(c) for c in self._changes(WITHOUT, new)] == [ExclusionConstraintAdded] * 2

    def test_a_changed_operator_is_a_drop_then_an_add(self) -> None:
        changed = EXCL.replace("during WITH &&", "during WITH =")
        assert [type(c) for c in self._changes(EXCL, changed)] == [
            ExclusionConstraintDropped,
            ExclusionConstraintAdded,
        ]

    def test_the_wire(self) -> None:
        (change,) = self._changes(WITHOUT, EXCL)
        wire = change.to_wire()
        assert (wire.type, wire.table) == ("ADD_EXCLUSION_CONSTRAINT", "tenant.tb_booking")
        assert wire.details == {
            "name": "no_overlap",
            "method": "gist",
            "elements": [
                {"element": "room_id", "operator": "="},
                {"element": "during", "operator": "&&"},
            ],
            "where": None,
        }


class TestTheGeneratedDDLKeepsIt:
    def test_a_new_tables_create_table(self) -> None:
        (change,) = SchemaDiffer().compare("", EXCL).changes
        assert DifferSQLGenerator().generate_up(change) == (
            "CREATE TABLE IF NOT EXISTS tenant.tb_booking (\n"
            "    room_id INTEGER,\n"
            "    during TSRANGE,\n"
            "    CONSTRAINT no_overlap EXCLUDE USING gist (room_id WITH =, during WITH &&)\n"
            ");\n"
        )

    def test_an_added_one_and_its_down(self) -> None:
        (change,) = SchemaDiffer().compare(WITHOUT, EXCL).changes
        generator = DifferSQLGenerator()
        assert generator.generate_up(change) == (
            "ALTER TABLE tenant.tb_booking ADD CONSTRAINT no_overlap"
            " EXCLUDE USING gist (room_id WITH =, during WITH &&);\n"
        )
        assert generator.generate_down(change) == (
            "ALTER TABLE tenant.tb_booking DROP CONSTRAINT IF EXISTS no_overlap;\n"
        )

    def test_an_expression_options_a_predicate_and_deferral(self) -> None:
        new = (
            "CREATE TABLE tenant.tb_booking (room_id INT, during TSRANGE, EXCLUDE USING gist"
            " ((lower(during)) WITH =, during range_ops WITH &&) WHERE (room_id > 0)"
            " DEFERRABLE INITIALLY DEFERRED);\n"
        )
        (change,) = SchemaDiffer().compare(WITHOUT, new).changes
        assert DifferSQLGenerator().generate_up(change) == (
            "ALTER TABLE tenant.tb_booking ADD EXCLUDE USING gist"
            " ((lower(during)) WITH =, during range_ops WITH &&) WHERE (room_id > 0)"
            " DEFERRABLE INITIALLY DEFERRED;\n"
        )


def test_a_deferrable_constraint_is_generated_deferrable() -> None:
    """The model carried ``deferrable`` and no generated clause wrote it."""
    old = "CREATE TABLE p (id INT PRIMARY KEY); CREATE TABLE c (pid INT);"
    new = (
        "CREATE TABLE p (id INT PRIMARY KEY); CREATE TABLE c (pid INT,"
        " CONSTRAINT fk_c FOREIGN KEY (pid) REFERENCES p (id) DEFERRABLE);"
    )
    (change,) = SchemaDiffer().compare(old, new).changes
    assert (
        DifferSQLGenerator()
        .generate_up(change)
        .startswith(
            "ALTER TABLE c ADD CONSTRAINT fk_c FOREIGN KEY (pid) REFERENCES p (id)"
            " DEFERRABLE INITIALLY IMMEDIATE NOT VALID;\n"
        )
    )
