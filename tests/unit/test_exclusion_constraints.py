"""An ``EXCLUDE`` constraint is modelled, compared, generated and drift-checked (#322).

It was the one constraint kind the model declined by name: the table parsed clean,
adding one reported nothing in either spelling, and a new table's generated
``CREATE TABLE`` dropped it.
"""

from __future__ import annotations

import pglast

from confiture.core.differ import SchemaDiffer
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
