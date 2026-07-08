"""Integration test for issue #175 — confiture build output round-trips through
``confiture drift``.

The expected-schema parser used by ``drift --schema`` must parse the DDL that
``confiture build`` itself emits (block-comment file separators, ``--`` line
comments including non-ASCII). Previously it yielded zero tables and reported
every live table as spurious ``extra_table`` drift with exit 0.

Requires a running PostgreSQL server accessible via CONFITURE_TEST_DB_URL.
"""

from __future__ import annotations

import psycopg

from confiture.core.drift import DriftType, SchemaDriftDetector

# The exact block-comment file separator SchemaBuilder emits by default.
_SEP = "\n/* " + "=" * 42 + "\n * File: {rel}\n * " + "=" * 42 + " */\n\n"

_LIVE_DDL = """
CREATE TABLE tb_machine (
    pk_machine UUID PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'active'
);
CREATE TABLE tb_part (
    pk_part UUID PRIMARY KEY,
    fk_machine UUID REFERENCES tb_machine(pk_machine),
    label TEXT NOT NULL
);
"""

# What `confiture build` would write: the same DDL, wrapped in the default
# block-comment separators and a non-ASCII line comment.
_BUILD_OUTPUT = (
    _SEP.format(rel="db/schema/10_tables/10_machine.sql")
    + "-- Machine registry — core entity\n"
    + "CREATE TABLE tb_machine (\n"
    + "    pk_machine UUID PRIMARY KEY,\n"
    + "    name TEXT NOT NULL,\n"
    + "    status TEXT DEFAULT 'active'\n"
    + ");\n"
    + _SEP.format(rel="db/schema/10_tables/20_part.sql")
    + "CREATE TABLE tb_part (\n"
    + "    pk_part UUID PRIMARY KEY,\n"
    + "    fk_machine UUID REFERENCES tb_machine(pk_machine),\n"
    + "    label TEXT NOT NULL\n"
    + ");\n"
)


def test_build_output_round_trips_through_drift(
    clean_test_db: psycopg.Connection, tmp_path
) -> None:
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute(_LIVE_DDL)
    conn.commit()

    schema_file = tmp_path / "schema_local.sql"
    schema_file.write_text(_BUILD_OUTPUT)

    report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))

    # Both tables parsed and compared — not reported as spurious extra tables.
    assert report.tables_checked == 2, report.to_dict()
    extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_TABLE]
    assert extra == [], [d.message for d in extra]
    assert not report.has_drift, report.to_dict()
