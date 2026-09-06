"""``drift --schema`` reads every schema the DDL declares, keyed ``schema.table`` (#227).

The live side used to read ``public`` only, and the expected side recorded
``tenant.tb_user`` as a table called ``tenant`` — so a two-schema database
reported every schema name as a critical ``missing_table`` and never compared
the qualified tables at all. This runs the real comparison against a database
with a ``tenant`` schema next to ``public``.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector

EXPECTED = """
CREATE SCHEMA tenant;
CREATE TABLE tenant.tb_user (
    id bigint PRIMARY KEY,
    name text NOT NULL DEFAULT 'x'
);
CREATE TABLE tb_plain (id integer PRIMARY KEY);
CREATE INDEX idx_user_name ON tenant.tb_user (name);
"""


def _apply(conn: psycopg.Connection, sql: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def test_two_schemas_compare_clean_when_live_matches(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    _apply(clean_test_db, EXPECTED)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(EXPECTED)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert [i for i in report.drift_items if i.drift_type == DriftType.MISSING_TABLE] == []
    assert [i for i in report.drift_items if i.drift_type == DriftType.EXTRA_TABLE] == []
    assert report.tables_checked == 2
    # The implicit primary-key index is a pre-existing info-level extra on any
    # table that declares an index; nothing above info may remain.
    assert [str(i) for i in report.drift_items if i.severity != DriftSeverity.INFO] == []


def test_a_dropped_column_in_the_tenant_schema_is_named_qualified(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    _apply(clean_test_db, EXPECTED)
    _apply(clean_test_db, "ALTER TABLE tenant.tb_user DROP COLUMN name;")
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(EXPECTED)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert [
        (i.drift_type, i.object_name)
        for i in report.drift_items
        if i.drift_type == DriftType.MISSING_COLUMN
    ] == [(DriftType.MISSING_COLUMN, "tenant.tb_user.name")]
    assert [i for i in report.drift_items if i.drift_type == DriftType.MISSING_TABLE] == []


def test_a_table_only_in_the_tenant_schema_live_is_an_extra_table(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    _apply(clean_test_db, EXPECTED)
    _apply(clean_test_db, "CREATE TABLE tenant.tb_stray (id int);")
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(EXPECTED)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert [i.object_name for i in report.drift_items if i.drift_type == DriftType.EXTRA_TABLE] == [
        "tenant.tb_stray"
    ]
