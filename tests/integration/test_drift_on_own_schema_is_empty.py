"""Drift on a database built from this repository's own schema reports nothing.

``db/schema`` is built exactly as ``confiture build --env local --schema-only``
builds it, applied to a fresh database, and read back through
``SchemaDriftDetector.compare_with_schema_file`` — the schema model on both sides.
A database applied verbatim from a tree is the one case where every finding is a
false one, whatever the comparison has learnt to compare: constraints, defaults,
unnamed indexes, an identity column.

The tree's one table is ``tb_confiture``, which the detector ignores everywhere
else as confiture's own bookkeeping. Here it *is* the schema under test, so the
ignore list is emptied: a comparison of zero tables would pass whatever it does.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg

from confiture.core.builder import SchemaBuilder
from confiture.core.drift import SchemaDriftDetector

REPO = Path(__file__).resolve().parents[2]


def test_drift_on_the_repositorys_own_schema_is_empty(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    schema_sql = SchemaBuilder(env="local", project_dir=REPO).build(schema_only=True)
    schema_file = tmp_path / "schema_local.sql"
    schema_file.write_text(schema_sql)

    url = fresh_database_factory("confiture_dogfood")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(schema_sql)

    with psycopg.connect(url) as conn:
        detector = SchemaDriftDetector(conn)
        detector.ignore_tables.clear()
        report = detector.compare_with_schema_file(str(schema_file))

    assert report.tables_checked >= 1, "the tree declares no table drift could compare"
    assert report.drift_items == [], report.to_dict()
