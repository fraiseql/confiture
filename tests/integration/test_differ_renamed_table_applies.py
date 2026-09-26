"""A migration generated across a table rename leaves the database as the new tree declares.

Built from the old DDL, migrated with what ``migrate diff`` generates, and read
back: the live schema and the new DDL differ in nothing. Before the fix the
generated migration was one ``RENAME`` — and when the renamed table was first
compared, its follow-up changes named the old table, which no longer existed.
"""

from __future__ import annotations

import pglast
import psycopg

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import SchemaDriftDetector
from confiture.platform import diff, parse_schema

_OLD = "CREATE SCHEMA app;\nCREATE TABLE app.tb_gone (id bigint PRIMARY KEY, title text);\n"
_NEW = (
    "CREATE SCHEMA app;\n"
    "CREATE TABLE app.tb_post (id bigint PRIMARY KEY, title text, body text, author_id bigint);\n"
    "CREATE INDEX ix_post_author ON app.tb_post (author_id);\n"
)


def test_the_migrated_database_matches_the_new_tree(fresh_database: str) -> None:
    generator = DifferSQLGenerator()
    up = "".join(generator.generate_up(c) or "" for c in diff(_OLD, _NEW).changes)

    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(_OLD)
        # One statement at a time, outside a transaction: CREATE INDEX CONCURRENTLY.
        for raw in pglast.parse_sql(up):
            conn.execute(pglast.stream.RawStream()(raw.stmt))

        report = SchemaDriftDetector(conn).compare_with_expected(parse_schema(_NEW))

    assert [(i.drift_type.value, i.object_name) for i in report.drift_items] == []
