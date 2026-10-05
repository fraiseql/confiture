"""A live ``NOT NULL … NOT VALID`` reads as one: the column may hold NULLs (#605).

PostgreSQL 18 keeps ``attnotnull`` true for a NOT NULL added ``NOT VALID``, while the
table still holds the NULL it held before; the constraint's own row (``contype =
'n'``) says ``convalidated = false``. ``live_catalog`` reads that row, so the column
reads ``not_null_validated=False`` — the same model a tree writing the same DDL reads
into (parse/live parity), and the fact drift and ``migrate diff`` compare. A server
before 18 cannot express it: there ``attnotnull`` is the whole answer and every
NOT NULL reads validated.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.live_catalog import column, read
from confiture.core.schema_change import ColumnNotNullValidityChanged
from confiture.core.schema_model import normalise_for_parity
from confiture.core.schema_read import read_text

#: The issue's reproduction, and a NOT NULL that is validated beside it.
REPRODUCTION = """
CREATE TABLE t (a int, b int CONSTRAINT nn_b NOT NULL);
INSERT INTO t VALUES (NULL, 1);
ALTER TABLE t ADD CONSTRAINT nn_a NOT NULL a NOT VALID;
"""

#: The same tree, without the row it was written to tolerate.
TREE = """
CREATE TABLE t (a int, b int CONSTRAINT nn_b NOT NULL);
ALTER TABLE t ADD CONSTRAINT nn_a NOT NULL a NOT VALID;
"""


def _major(conn: psycopg.Connection) -> int:
    row = conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    return int(row[0]) // 10000


@pytest.fixture
def database(fresh_database_factory: Callable[[str], str]) -> str:
    return fresh_database_factory("confiture_notnull")


def _on_18(url: str) -> None:
    with psycopg.connect(url) as conn:
        if _major(conn) < 18:
            pytest.skip("a NOT VALID NOT NULL is PostgreSQL 18's; before it, see the fallback test")


def test_an_unvalidated_not_null_reads_as_not_validated(database: str) -> None:
    _on_18(database)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(REPRODUCTION)
        a = column(conn, "public", "t", "a")
        b = column(conn, "public", "t", "b")
    assert a is not None and b is not None
    assert (a.not_null, a.not_null_validated) == (True, False)
    assert (b.not_null, b.not_null_validated) == (True, True)


def test_validating_it_reads_as_validated(database: str) -> None:
    _on_18(database)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(TREE)
        conn.execute("ALTER TABLE t VALIDATE CONSTRAINT nn_a")
        a = column(conn, "public", "t", "a")
    assert a is not None and (a.not_null, a.not_null_validated) == (True, True)


def test_before_18_attnotnull_is_the_answer(database: str) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        if _major(conn) >= 18:
            pytest.skip("PostgreSQL 18 reads the constraint row: see the tests above")
        conn.execute("CREATE TABLE t (a int NOT NULL, b int)")
        a = column(conn, "public", "t", "a")
        b = column(conn, "public", "t", "b")
    assert a is not None and (a.not_null, a.not_null_validated) == (True, True)
    assert b is not None and (b.not_null, b.not_null_validated) == (False, True)


def test_the_tree_and_the_database_read_alike(database: str) -> None:
    _on_18(database)
    parsed = read_text(TREE).model
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(TREE)
        live = read(conn, schemas=["public"])
    tables = [normalise_for_parity(side).to_dict()["tables"] for side in (parsed, live)]
    assert tables[1] == tables[0]


def test_drift_and_diff_report_the_unvalidated_not_null(database: str, tmp_path: Path) -> None:
    _on_18(database)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE t (a int NOT NULL);\n", encoding="utf-8")
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("CREATE TABLE t (a int); INSERT INTO t VALUES (NULL)")
        conn.execute("ALTER TABLE t ADD NOT NULL a NOT VALID")
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))
    assert [(i.drift_type, i.severity, i.object_name) for i in report.drift_items] == [
        (DriftType.NULLABLE_MISMATCH, DriftSeverity.WARNING, "public.t.a")
    ]
    changes = platform.diff(database, schema_file).changes
    assert [(type(c), c.column, c.validated) for c in changes] == [
        (ColumnNotNullValidityChanged, "a", True)
    ]
