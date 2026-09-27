"""A migration generated for names that need quotes applies, and undoes (#479).

Built from the old DDL, migrated with what ``migrate diff`` generates, and read
back against the new DDL; then migrated down and read back against the old.
Every name in both trees needs quotes: a space, a capital, a reserved word.
"""

from __future__ import annotations

import pglast
import psycopg
import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import SchemaDriftDetector
from confiture.platform import diff, parse_schema

#: Generated DDL is tested with names the differ refuses (DIFFER_403): the second layer.
pytestmark = pytest.mark.usefixtures("quoted_names_allowed")

_OLD = """CREATE SCHEMA app;
CREATE TABLE app."Order Line" ("Line Id" int PRIMARY KEY, "Mixed Col" text, "user" text,
    qty int CONSTRAINT "Qty Positive" CHECK (qty > 0));
CREATE INDEX "Old Index" ON app."Order Line" ("Mixed Col");
"""

_NEW = """CREATE SCHEMA app;
CREATE TABLE app."Order Line" ("Line Id" int PRIMARY KEY, "Mixed Col" varchar(20) NOT NULL DEFAULT 'x',
    "user" text, qty int, "Parent Id" int);
CREATE TABLE app."New Table" ("Weird Id" int PRIMARY KEY, "user" text,
    CONSTRAINT "Weird Unique" UNIQUE ("user"));
CREATE INDEX "My Index" ON app."Order Line" ("Mixed Col");
CREATE INDEX "Lower Index" ON app."Order Line" (lower("Mixed Col"));
ALTER TABLE app."Order Line" ADD CONSTRAINT "Parent Fk" FOREIGN KEY ("Parent Id")
    REFERENCES app."New Table" ("Weird Id");
CREATE SEQUENCE app."My Seq";
"""


def _apply(conn: psycopg.Connection, sql: str) -> None:
    # One statement at a time, outside a transaction: CREATE INDEX CONCURRENTLY.
    for raw in pglast.parse_sql(sql):
        conn.execute(pglast.stream.RawStream()(raw.stmt))


def _drift(conn: psycopg.Connection, sql: str) -> list[tuple[str, str]]:
    report = SchemaDriftDetector(conn).compare_with_expected(parse_schema(sql))
    return [(item.drift_type.value, item.object_name) for item in report.drift_items]


def test_the_generated_migration_applies_and_undoes(fresh_database: str) -> None:
    generator = DifferSQLGenerator()
    changes = diff(_OLD, _NEW).changes
    up = "".join(generator.generate_up(c) or "" for c in changes)
    down = "".join(generator.generate_down(c) or "" for c in reversed(changes))

    with psycopg.connect(fresh_database, autocommit=True) as conn:
        _apply(conn, _OLD)
        _apply(conn, up)
        after_up = _drift(conn, _NEW)
        _apply(conn, down)
        after_down = _drift(conn, _OLD)

    assert after_up == []
    assert after_down == []
