"""Generated DDL quotes an identifier exactly where PostgreSQL needs it (#479).

``migrate diff`` / ``migrate generate`` wrote every name bare, so a table named
``"New Table"``, a column named ``user`` or ``"Mixed Col"``, an index or a
constraint whose name needs quotes produced a migration PostgreSQL refuses. Each
statement is checked by parsing it and reading the names back from the tree,
never by matching text.
"""

from __future__ import annotations

import pglast
import pytest
from pglast import ast

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.platform import diff

#: Generated DDL is tested with names the differ refuses (DIFFER_403): the second layer.
pytestmark = pytest.mark.usefixtures("quoted_names_allowed")

OLD = """CREATE SCHEMA app;
CREATE TABLE app."Order Line" ("Line Id" int PRIMARY KEY, "Mixed Col" text, "user" text,
    qty int CONSTRAINT "Qty Positive" CHECK (qty > 0));
CREATE INDEX "Old Index" ON app."Order Line" ("Mixed Col");
"""

NEW = """CREATE SCHEMA app;
CREATE TABLE app."Order Line" ("Line Id" int PRIMARY KEY, "Mixed Col" varchar(20) NOT NULL DEFAULT 'x',
    "user" text, "Parent Id" int, "Added Col" int);
CREATE TABLE app."New Table" ("Weird Id" int PRIMARY KEY, "user" text,
    CONSTRAINT "Weird Unique" UNIQUE ("user"));
CREATE INDEX "My Index" ON app."Order Line" ("Mixed Col");
CREATE INDEX "Lower Index" ON app."Order Line" (lower("Mixed Col"));
ALTER TABLE app."Order Line" ADD CONSTRAINT "Parent Fk" FOREIGN KEY ("Parent Id")
    REFERENCES app."New Table" ("Weird Id");
CREATE TYPE app."My Enum" AS ENUM ('a');
CREATE SEQUENCE app."My Seq";
"""


def _statements(sql: str) -> list[object]:
    return [raw.stmt for raw in pglast.parse_sql(sql)]


def _generated(direction: str) -> list[tuple[str, str]]:
    generator = DifferSQLGenerator()
    render = generator.generate_up if direction == "up" else generator.generate_down
    return [(type(c).__name__, render(c) or "") for c in diff(OLD, NEW).changes]


@pytest.mark.parametrize("direction", ["up", "down"])
def test_every_generated_statement_parses(direction: str) -> None:
    refused = []
    for kind, sql in _generated(direction):
        try:
            pglast.parse_sql(sql)
        except pglast.parser.ParseError as error:
            refused.append(f"{kind}: {error}: {sql.strip()}")

    assert refused == []


def _up(kind: str) -> list[object]:
    return [stmt for name, sql in _generated("up") if name == kind for stmt in _statements(sql)]


def test_a_new_table_keeps_its_names() -> None:
    (create,) = [s for s in _up("TableAdded") if isinstance(s, ast.CreateStmt)]
    columns = [e.colname for e in create.tableElts if isinstance(e, ast.ColumnDef)]
    constraints = [e for e in create.tableElts if isinstance(e, ast.Constraint)]

    assert (create.relation.schemaname, create.relation.relname) == ("app", "New Table")
    assert columns == ["Weird Id", "user"]
    assert {c.conname for c in constraints} >= {"Weird Unique"}
    assert [k.sval for c in constraints if c.conname == "Weird Unique" for k in c.keys] == ["user"]


def test_an_added_column_keeps_its_name() -> None:
    names = {cmd.def_.colname for s in _up("ColumnAdded") for cmd in s.cmds}

    assert names == {"Parent Id", "Added Col"}


def test_a_changed_column_is_named_by_its_name() -> None:
    changed = [
        *_up("ColumnTypeChanged"),
        *_up("ColumnNullabilityChanged"),
        *_up("ColumnDefaultChanged"),
    ]

    assert {cmd.name for s in changed for cmd in s.cmds} == {"Mixed Col"}
    assert {(s.relation.schemaname, s.relation.relname) for s in changed} == {("app", "Order Line")}


def test_an_index_keeps_its_name_and_a_column_key_stays_a_column() -> None:
    created = {s.idxname: s for s in _up("IndexAdded")}

    assert set(created) == {"My Index", "Lower Index"}
    (column_key,) = created["My Index"].indexParams
    assert (column_key.name, column_key.expr) == ("Mixed Col", None)
    (expression_key,) = created["Lower Index"].indexParams
    assert expression_key.name is None and expression_key.expr is not None


def test_a_dropped_index_is_named_in_its_tables_schema() -> None:
    (drop,) = _up("IndexDropped")

    assert [[n.sval for n in obj] for obj in drop.objects] == [["app", "Old Index"]]


def test_a_constraint_keeps_its_name_and_its_columns() -> None:
    (added, _validate) = _up("ForeignKeyAdded")
    (cmd,) = added.cmds
    fk = cmd.def_

    assert fk.conname == "Parent Fk"
    assert [k.sval for k in fk.fk_attrs] == ["Parent Id"]
    assert [k.sval for k in fk.pk_attrs] == ["Weird Id"]
    (dropped,) = _up("CheckConstraintDropped")
    assert dropped.cmds[0].name == "Qty Positive"


def test_an_enum_and_a_sequence_keep_their_names() -> None:
    (enum,) = _up("EnumTypeAdded")
    (sequence,) = _up("SequenceAdded")

    assert [n.sval for n in enum.typeName] == ["app", "My Enum"]
    assert (sequence.sequence.schemaname, sequence.sequence.relname) == ("app", "My Seq")


def test_an_ordinary_name_is_written_bare() -> None:
    old = "CREATE TABLE t (id int PRIMARY KEY);"
    new = "CREATE TABLE t (id int PRIMARY KEY, name text);\nCREATE INDEX ix_t ON t (name);"
    sql = "".join(DifferSQLGenerator().generate_up(c) or "" for c in diff(old, new).changes)

    assert '"' not in sql
