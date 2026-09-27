"""A relation one object names is held as schema and name, never one dotted string (#478).

PostgreSQL accepts ``app."a.b"``. The model used to carry a foreign key's target,
an index's table and a partition's parent as ``schema.name`` text and split it
back on its last dot, so ``REFERENCES app."a.b"`` named table ``b`` in schema
``app.a``. Now the parts come from the parser as parts and stay apart.
"""

from __future__ import annotations

import json

import pglast
import pytest
from pglast import ast

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.linting.inventory import build_inventory
from confiture.platform import (
    ObjectRef,
    RelationName,
    SchemaModel,
    column_facts,
    dependency_order,
    diff,
    parse_schema,
)

DOTTED = """CREATE SCHEMA app;
CREATE TABLE app.c (id int PRIMARY KEY, fk int REFERENCES app."a.b" (id));
CREATE TABLE app."a.b" (id int PRIMARY KEY);
CREATE INDEX ix_c ON app.c (fk);
"""


def _table(model: SchemaModel, schema: str, name: str):
    return next(t for ref, t in model.tables.items() if (ref.schema, ref.name) == (schema, name))


def test_a_foreign_key_holds_its_target_as_parts() -> None:
    (fk,) = _table(parse_schema(DOTTED), "app", "c").constraints_of("foreign_key")

    assert fk.ref_table == RelationName("app", "a.b")


def test_an_index_holds_its_table_as_parts() -> None:
    (index,) = _table(parse_schema(DOTTED), "app", "c").indexes

    assert index.table == RelationName("app", "c")


def test_an_unqualified_reference_keeps_no_schema_and_its_identity_defaults_one() -> None:
    model = parse_schema(
        "CREATE TABLE p (id int PRIMARY KEY);\nCREATE TABLE c (fk int REFERENCES p);"
    )
    (fk,) = _table(model, "public", "c").constraints_of("foreign_key")

    assert fk.ref_table == RelationName(None, "p")
    assert fk.ref_table.identity == ("public", "p")


def test_the_wire_carries_the_parts_and_reads_back() -> None:
    model = parse_schema(DOTTED)
    wire = json.loads(model.to_json())
    (c,) = [t for t in wire["tables"] if t["name"] == "c"]
    (fk,) = [k for k in c["constraints"] if k["kind"] == "foreign_key"]

    assert fk["ref_table"] == {"schema": "app", "name": "a.b"}
    assert c["indexes"][0]["table"] == {"schema": "app", "name": "c"}
    assert SchemaModel.from_json(model.to_json()) == model


def test_dependency_order_puts_the_dotted_parent_first() -> None:
    """The parent sorts last by name, so only the foreign key can put it first."""
    sql = DOTTED.replace('"a.b"', '"z.y"')
    order = [(ref.schema, ref.name) for ref in dependency_order(parse_schema(sql))]

    assert order.index(("app", "z.y")) < order.index(("app", "c"))


def test_column_facts_name_the_dotted_target() -> None:
    facts = column_facts(parse_schema(DOTTED), "app.c", "fk")

    assert facts.foreign_key is not None
    assert (facts.foreign_key.table.schema, facts.foreign_key.table.name) == ("app", "a.b")
    assert isinstance(facts.foreign_key.table, ObjectRef)


@pytest.mark.usefixtures("quoted_names_allowed")
def test_a_generated_foreign_key_references_the_dotted_table() -> None:
    old = 'CREATE SCHEMA app;\nCREATE TABLE app."a.b" (id int PRIMARY KEY);\nCREATE TABLE app.c (id int PRIMARY KEY, fk int);'
    (change,) = [c for c in diff(old, DOTTED).changes if type(c).__name__ == "ForeignKeyAdded"]

    sql = DifferSQLGenerator().generate_up(change) or ""
    (raw,) = pglast.parse_sql(sql.split(";")[0])
    (cmd,) = raw.stmt.cmds
    pktable = cmd.def_.pktable

    assert isinstance(raw.stmt, ast.AlterTableStmt)
    assert (pktable.schemaname, pktable.relname) == ("app", "a.b")


def test_a_partition_and_an_inheriting_child_hold_their_parents_as_parts() -> None:
    inventory = build_inventory(
        'CREATE SCHEMA app;\nCREATE TABLE app."p.q" (id int, at date) PARTITION BY RANGE (at);\n'
        "CREATE TABLE app.part PARTITION OF app.\"p.q\" FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
        'CREATE TABLE app."r.s" (id int);\nCREATE TABLE app.child (x int) INHERITS (app."r.s");\n'
    )
    by_name = {t.name: t for t in inventory.tables}

    assert by_name["part"].parent == RelationName("app", "p.q")
    assert by_name["child"].inherits == (RelationName("app", "r.s"),)
