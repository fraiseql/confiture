"""A NOT ENFORCED CHECK or foreign key is not the enforced one (#603).

PostgreSQL 18 lets a CHECK or a foreign key be declared ``NOT ENFORCED``: the
database then guarantees nothing the constraint says. The model holds it as
``Constraint.enforced``, read wherever the grammar puts the clause — at table
level, on a column (a sibling node, as deferrability is), in ``ADD CONSTRAINT``
— and what the catalog's ``pg_get_constraintdef`` writes is read by the same
reader. A constraint going from enforced to not, or back, is a change: the
differ replaces it, and drift reports it as the ``constraint_mismatch`` it is.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pglast
import pytest

from confiture.core.ddl_clauses import constraint_body
from confiture.core.ddl_walk import read_constraint
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ForeignKeyAdded,
    ForeignKeyDropped,
)
from confiture.platform import Constraint, RelationName, SchemaModel, parse_schema
from tests.unit._schema_models import column, model, table

PARENT = "CREATE TABLE p (id int PRIMARY KEY);\n"


def _constraints(sql: str, name: str = "t") -> tuple[Constraint, ...]:
    schema: SchemaModel = parse_schema(PARENT + sql)
    return next(t for ref, t in schema.tables.items() if ref.name == name).constraints


def _enforced(sql: str) -> list[tuple[str, bool]]:
    return [(c.kind, c.enforced) for c in _constraints(sql) if c.kind != "primary_key"]


# ---------------------------------------------------------------------------
# The tree: every place the grammar puts the clause
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        pytest.param(
            "CREATE TABLE t (a int, CONSTRAINT c CHECK (a > 0) NOT ENFORCED);",
            [("check", False)],
            id="table-level-check",
        ),
        pytest.param(
            "CREATE TABLE t (a int, CONSTRAINT f FOREIGN KEY (a) REFERENCES p NOT ENFORCED);",
            [("foreign_key", False)],
            id="table-level-foreign-key",
        ),
        pytest.param(
            "CREATE TABLE t (a int CHECK (a > 0) NOT ENFORCED);",
            [("check", False)],
            id="column-check",
        ),
        pytest.param(
            "CREATE TABLE t (a int REFERENCES p NOT ENFORCED DEFERRABLE);",
            [("foreign_key", False)],
            id="column-foreign-key-with-deferrability",
        ),
        pytest.param(
            "CREATE TABLE t (a int);\n"
            "ALTER TABLE t ADD CONSTRAINT f FOREIGN KEY (a) REFERENCES p NOT ENFORCED;",
            [("foreign_key", False)],
            id="add-constraint",
        ),
        pytest.param(
            "CREATE TABLE t (a int CHECK (a > 0) ENFORCED, CHECK (a < 9));",
            [("check", True), ("check", True)],
            id="enforced-said-or-not",
        ),
    ],
)
def test_the_tree_reads_whether_a_constraint_is_enforced(
    sql: str, expected: list[tuple[str, bool]]
) -> None:
    assert _enforced(sql) == expected


def test_a_column_attribute_qualifies_the_constraint_before_it() -> None:
    sql = "CREATE TABLE t (a int REFERENCES p NOT ENFORCED CHECK (a > 0));"
    assert sorted(_enforced(sql)) == [("check", True), ("foreign_key", False)]


def test_deferrability_survives_beside_enforcement() -> None:
    (fk,) = (
        c
        for c in _constraints("CREATE TABLE t (a int REFERENCES p NOT ENFORCED DEFERRABLE);")
        if c.kind == "foreign_key"
    )
    assert (fk.enforced, fk.deferrable) == (False, "immediate")


def test_a_hand_built_node_that_says_nothing_is_enforced() -> None:
    """A ``Constraint`` node built without ``is_enforced`` reads as PostgreSQL's default."""
    stmt = pglast.parse_sql("ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0)")[0].stmt
    node = stmt.cmds[0].def_
    node.is_enforced = None
    read = read_constraint(node)
    assert isinstance(read, Constraint)
    assert read.enforced is True


# ---------------------------------------------------------------------------
# The one clause, written and read back
# ---------------------------------------------------------------------------

UNENFORCED_FK = Constraint(
    kind="foreign_key",
    name="f",
    columns=("a",),
    ref_table=RelationName(None, "p"),
    ref_columns=("id",),
    enforced=False,
)
UNENFORCED_CHECK = Constraint(kind="check", name="c", expression="a > 0", enforced=False)


@pytest.mark.parametrize(
    ("constraint", "body"),
    [
        (UNENFORCED_CHECK, "CHECK (a > 0) NOT ENFORCED"),
        (UNENFORCED_FK, "FOREIGN KEY (a) REFERENCES p (id) NOT ENFORCED"),
        (
            replace(UNENFORCED_FK, deferrable="deferred"),
            "FOREIGN KEY (a) REFERENCES p (id) DEFERRABLE INITIALLY DEFERRED NOT ENFORCED",
        ),
        (replace(UNENFORCED_CHECK, enforced=True), "CHECK (a > 0)"),
    ],
)
def test_the_clause_says_not_enforced_and_reads_back_as_itself(
    constraint: Constraint, body: str
) -> None:
    assert constraint_body(constraint) == body
    stmt = pglast.parse_sql(f"ALTER TABLE t ADD CONSTRAINT {constraint.name} {body}")[0].stmt
    assert read_constraint(stmt.cmds[0].def_) == constraint


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

ENFORCED_TREE = (
    PARENT + "CREATE TABLE t (a int, CONSTRAINT c CHECK (a > 0),"
    " CONSTRAINT f FOREIGN KEY (a) REFERENCES p (id));\n"
)
UNENFORCED_TREE = (
    PARENT + "CREATE TABLE t (a int, CONSTRAINT c CHECK (a > 0) NOT ENFORCED,"
    " CONSTRAINT f FOREIGN KEY (a) REFERENCES p (id) NOT ENFORCED);\n"
)


@pytest.mark.parametrize(
    ("old", "new", "written"),
    [
        pytest.param(ENFORCED_TREE, UNENFORCED_TREE, False, id="enforced-to-not"),
        pytest.param(UNENFORCED_TREE, ENFORCED_TREE, True, id="not-to-enforced"),
    ],
)
def test_a_change_of_enforcement_replaces_the_constraint(old: str, new: str, written: bool) -> None:
    changes = SchemaDiffer().compare(old, new).changes
    assert [type(c) for c in changes] == [
        ForeignKeyDropped,
        ForeignKeyAdded,
        CheckConstraintDropped,
        CheckConstraintAdded,
    ]
    for change in changes:
        if isinstance(change, ForeignKeyAdded | CheckConstraintAdded):
            sql = DifferSQLGenerator().generate_up(change) or ""
            stmt = pglast.parse_sql(sql)[0].stmt
            read = read_constraint(stmt.cmds[0].def_)
            assert isinstance(read, Constraint)
            assert read.enforced is written


def test_the_same_enforcement_is_no_change() -> None:
    assert SchemaDiffer().compare(UNENFORCED_TREE, UNENFORCED_TREE).changes == []


# ---------------------------------------------------------------------------
# Drift: the existing constraint_mismatch, nothing new
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("declared", [UNENFORCED_CHECK, UNENFORCED_FK], ids=["check", "fk"])
@pytest.mark.parametrize("tree_enforces", [True, False], ids=["tree-enforces", "db-enforces"])
def test_drift_reports_a_change_of_enforcement_as_a_constraint_mismatch(
    declared: Constraint, tree_enforces: bool
) -> None:
    expected = replace(declared, enforced=tree_enforces)
    live = replace(declared, enforced=not tree_enforces)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    report = SchemaDriftDetector(conn).compare_schemas(
        model(table("t", column("a"), constraints=[expected])),
        model(table("t", column("a"), constraints=[live])),
    )
    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (
        DriftType.CONSTRAINT_MISMATCH,
        DriftSeverity.CRITICAL,
    )
    assert (item.expected, item.actual) == (constraint_body(expected), constraint_body(live))
