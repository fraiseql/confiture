"""The live catalog's text answers are read by the code that reads DDL.

``pg_get_constraintdef``, ``pg_get_indexdef``, ``format_type`` and ``pg_get_expr``
answer in SQL text. ``core/live_catalog`` hands that text to the same readers the
lint inventory uses — ``ddl_walk.read_constraint``, ``read_index`` and
``written_type`` — so a parse/live comparison is between two readings by one
reader. This pins the text shapes PostgreSQL produces, with no database, so the
``pglast-matrix`` leg can run it on every supported pglast.
"""

from __future__ import annotations

import pglast

from confiture.core.ddl_walk import read_index, written_type
from confiture.core.live_catalog import _constraint, _expression, _type_nodes
from confiture.core.schema_model import Constraint


def test_a_foreign_key_definition_reads_as_the_ddl_would() -> None:
    assert _constraint(
        "fk", "FOREIGN KEY (pid) REFERENCES b.p(id) ON DELETE CASCADE"
    ) == Constraint(
        kind="foreign_key",
        name="fk",
        columns=("pid",),
        ref_table="b.p",
        ref_columns=("id",),
        on_delete="CASCADE",
    )


def test_a_deferrable_unique_definition_keeps_its_deferral() -> None:
    read = _constraint("uq", "UNIQUE (a, b) DEFERRABLE INITIALLY DEFERRED")
    assert read == Constraint(kind="unique", name="uq", columns=("a", "b"), deferrable="deferred")


def test_a_name_that_needs_quoting_survives() -> None:
    read = _constraint('Weird "name"', "CHECK ((a > 0))")
    assert read is not None and read.name == 'Weird "name"'


def test_format_type_reads_to_the_ddl_spelling() -> None:
    nodes = _type_nodes(["character varying(50)", "integer[]", "numeric(10,2)", "character(2)"])
    assert [written_type(n) for n in nodes] == [
        "VARCHAR(50)",
        "int4[]",
        "NUMERIC(10,2)",
        "bpchar(2)",
    ]


def test_an_index_definition_reads_through_the_one_index_reader() -> None:
    stmt = pglast.parse_sql("CREATE UNIQUE INDEX ix ON public.t USING hash (a) WHERE (a > 0)")[
        0
    ].stmt
    index = read_index(stmt, table="public.t")
    assert (index.name, index.columns, index.unique, index.method, index.where) == (
        "ix",
        ("a",),
        True,
        "hash",
        "a > 0",
    )


def test_a_stored_expression_parses() -> None:
    assert type(_expression("'x'::text")).__name__ == "TypeCast"
