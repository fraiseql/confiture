"""A generated migration applies, its down undoes it, and it applies again (#335).

Parsing proves a statement is grammatical; it does not prove PostgreSQL accepts
it, nor that the down file really undoes the up. Each scenario here builds the
*old* schema into a scratch database, writes the migration ``migrate diff
--generate`` writes for old → new, and applies the up file, the down file, then
the up file again — statement by statement, as ``CREATE INDEX CONCURRENTLY``
requires, with the destructive gate open so every derived statement is written.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core import sql_lexer
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator

pytestmark = pytest.mark.integration


def _apply(conn: psycopg.Connection, text: str) -> None:
    for statement in sql_lexer.split_statements(text):
        if sql_lexer.code_text(statement).text.strip():
            conn.execute(statement)


def _generated(tmp_path: Path, old: str, new: str) -> tuple[str, str]:
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiffer().compare(old, new),
        name="step",
        version="20260101000000",
        destructive="allow",
    )
    return up.read_text(), up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()


def round_trip(url: str, tmp_path: Path, old: str, new: str) -> psycopg.Connection:
    """*old* built, then up, down and up applied; the connection, left after the last up."""
    up, down = _generated(tmp_path, old, new)
    conn = psycopg.connect(url, autocommit=True)
    if old.strip():
        _apply(conn, old)
    _apply(conn, up)
    _apply(conn, down)
    _apply(conn, up)
    return conn


def _constraints(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype <> 'p'",
        (table,),
    ).fetchall()
    return {name for (name,) in rows}


PARENT = "CREATE TABLE parent (id INT PRIMARY KEY);\n"


class TestAddedConstraints:
    """The down of an added named constraint drops it; an unnamed one says it cannot."""

    OLD = PARENT + "CREATE TABLE t (id INT, pid INT);\n"
    NEW = PARENT + (
        "CREATE TABLE t (id INT, pid INT"
        ", CONSTRAINT fk_t_parent FOREIGN KEY (pid) REFERENCES parent(id)"
        ", CONSTRAINT ck_t_id CHECK (id > 0), CONSTRAINT uq_t_id UNIQUE (id));\n"
    )

    def test_named_ones_round_trip(self, fresh_database: str, tmp_path: Path) -> None:
        conn = round_trip(fresh_database, tmp_path, self.OLD, self.NEW)
        assert _constraints(conn, "t") == {"fk_t_parent", "ck_t_id", "uq_t_id"}

    def test_the_down_removes_them(self, fresh_database: str, tmp_path: Path) -> None:
        up, down = _generated(tmp_path, self.OLD, self.NEW)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        _apply(conn, down)
        assert _constraints(conn, "t") == set()
