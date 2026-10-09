"""A NOT ENFORCED constraint read live is the one the tree declares (#603).

PostgreSQL 18 writes ``NOT ENFORCED`` in ``pg_get_constraintdef``, which the live
reader reads through the same constraint reader as the tree: on 18 a database
built from the tree reads back as the tree, enforcement included. Before 18 the
clause does not exist, the server refuses it, and every constraint the catalog
holds is enforced — which is the model's default. Either way drift says when the
tree and the database disagree about it.
"""

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.live_catalog import read
from confiture.core.schema_model import Constraint, normalise_for_parity
from confiture.core.schema_read import read_text

#: The first PostgreSQL that can declare a constraint NOT ENFORCED.
NOT_ENFORCED_SINCE = 18

PARENT = "CREATE TABLE p (id int PRIMARY KEY);\n"
UNENFORCED = PARENT + (
    "CREATE TABLE t (\n"
    "    a int CHECK (a > 0) NOT ENFORCED,\n"
    "    b int REFERENCES p (id) NOT ENFORCED,\n"
    "    CONSTRAINT t_c CHECK (b > 0) NOT ENFORCED,\n"
    "    CONSTRAINT t_f FOREIGN KEY (a) REFERENCES p (id) NOT ENFORCED DEFERRABLE\n"
    ");\n"
)
ENFORCED = PARENT + (
    "CREATE TABLE t (\n"
    "    a int,\n"
    "    b int,\n"
    "    CONSTRAINT t_c CHECK (b > 0),\n"
    "    CONSTRAINT t_f FOREIGN KEY (a) REFERENCES p (id)\n"
    ");\n"
)
NAMED_UNENFORCED = PARENT + (
    "CREATE TABLE t (\n"
    "    a int,\n"
    "    b int,\n"
    "    CONSTRAINT t_c CHECK (b > 0) NOT ENFORCED,\n"
    "    CONSTRAINT t_f FOREIGN KEY (a) REFERENCES p (id) NOT ENFORCED\n"
    ");\n"
)


def _major(conn: psycopg.Connection) -> int:
    return conn.info.server_version // 10000


def _table_constraints(model_constraints: dict) -> list[dict]:
    (t,) = (table for table in model_constraints["tables"] if table["name"] == "t")
    return sorted(t["constraints"], key=lambda c: (c["kind"], c["name"], str(c["expression"])))


def _enforcement(constraints: tuple[Constraint, ...]) -> list[tuple[str, bool]]:
    return sorted((c.kind, c.enforced) for c in constraints if c.kind != "primary_key")


def test_the_database_reads_back_the_enforcement_the_tree_declares(
    fresh_database_factory: Callable[[str], str],
) -> None:
    parsed = read_text(UNENFORCED).model
    with psycopg.connect(fresh_database_factory("confiture_enforced"), autocommit=True) as conn:
        if _major(conn) < NOT_ENFORCED_SINCE:
            # Before 18 the clause is a syntax error, and what the catalog holds
            # is enforced: the model's default, with nothing to read.
            with pytest.raises(psycopg.errors.SyntaxError):
                conn.execute(UNENFORCED)
            conn.execute(ENFORCED)
            live = read(conn, schemas=["public"])
            (table,) = (t for t in live.tables.values() if t.name == "t")
            assert _enforcement(table.constraints) == [("check", True), ("foreign_key", True)]
            return
        conn.execute(UNENFORCED)
        live = read(conn, schemas=["public"])

    (table,) = (t for t in live.tables.values() if t.name == "t")
    assert _enforcement(table.constraints) == [
        ("check", False),
        ("check", False),
        ("foreign_key", False),
        ("foreign_key", False),
    ]
    assert _table_constraints(normalise_for_parity(parsed).to_dict()) == _table_constraints(
        normalise_for_parity(live).to_dict()
    )


@pytest.mark.parametrize(
    ("built", "declared"),
    [
        pytest.param(ENFORCED, NAMED_UNENFORCED, id="tree-unenforces"),
        pytest.param(NAMED_UNENFORCED, ENFORCED, id="database-unenforces"),
    ],
)
def test_drift_reports_a_constraint_whose_enforcement_differs(
    built: str,
    declared: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(declared, encoding="utf-8")
    with psycopg.connect(fresh_database_factory("confiture_enforced"), autocommit=True) as conn:
        if built is NAMED_UNENFORCED and _major(conn) < NOT_ENFORCED_SINCE:
            # A database before 18 cannot hold an unenforced constraint: the
            # disagreement this row builds cannot exist there.
            with pytest.raises(psycopg.errors.SyntaxError):
                conn.execute(built)
            return
        conn.execute(built)
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))

    assert sorted((i.drift_type, i.severity, i.object_name) for i in report.drift_items) == [
        (DriftType.CONSTRAINT_MISMATCH, DriftSeverity.CRITICAL, "public.t.t_c"),
        (DriftType.CONSTRAINT_MISMATCH, DriftSeverity.CRITICAL, "public.t.t_f"),
    ]
