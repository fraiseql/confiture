"""``drift`` compares the indexes a schema declares, not the ones PostgreSQL creates for it.

A ``PRIMARY KEY`` or ``UNIQUE`` constraint is backed by an index PostgreSQL
names itself (``t_pkey``, ``t_code_key``, or the constraint's name). The DDL
never declares that index, so comparing bare name sets reported one
info-level ``extra_index`` per constraint on every table — noise that hid the
one signal the check exists for: an index the live database carries and the
DDL does not.

Runs the real comparison against the local test database.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from confiture.core.drift import DriftType, SchemaDriftDetector
from confiture.core.schema_analyzer import SchemaAnalyzer

DDL = """
CREATE TABLE t (
    id integer PRIMARY KEY,
    code text UNIQUE,
    label text,
    CONSTRAINT t_label_uq UNIQUE (label)
);
CREATE INDEX idx_t_code ON t (code);
CREATE TABLE u (id integer PRIMARY KEY);
"""


def _apply(conn: psycopg.Connection, sql: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _items(report, drift_type: DriftType) -> list[str]:
    return sorted(i.object_name for i in report.drift_items if i.drift_type == drift_type)


def test_constraint_backed_indexes_are_not_extra(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    _apply(clean_test_db, DDL)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(DDL)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert _items(report, DriftType.EXTRA_INDEX) == [], report.to_dict()
    assert _items(report, DriftType.MISSING_INDEX) == []
    assert not report.has_drift, report.to_dict()


def test_a_free_standing_live_index_still_reports(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    _apply(clean_test_db, DDL)
    _apply(clean_test_db, "CREATE INDEX idx_t_code2 ON t (code);")
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(DDL)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert _items(report, DriftType.EXTRA_INDEX) == ["public.t.idx_t_code2"]


def test_a_table_that_declares_no_index_is_still_compared(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    # ``u`` declares no CREATE INDEX at all; an index the live database grew
    # is drift on it just the same.
    _apply(clean_test_db, DDL)
    _apply(clean_test_db, "CREATE INDEX idx_u_id ON u (id);")
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(DDL)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert _items(report, DriftType.EXTRA_INDEX) == ["public.u.idx_u_id"]


def test_a_declared_index_that_backs_a_constraint_is_neither_missing_nor_extra(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    # ``UNIQUE USING INDEX`` promotes a declared index into a constraint: the
    # live side knows it as constraint-backed, the DDL still declares it by
    # name, and the two must agree.
    ddl = (
        "CREATE TABLE v (id integer PRIMARY KEY, email text);\n"
        "CREATE UNIQUE INDEX v_email_uq ON v (email);\n"
        "ALTER TABLE v ADD CONSTRAINT v_email_uq UNIQUE USING INDEX v_email_uq;\n"
    )
    _apply(clean_test_db, ddl)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert _items(report, DriftType.EXTRA_INDEX) == []
    assert _items(report, DriftType.MISSING_INDEX) == []


def test_schema_info_names_the_constraint_backed_indexes(
    clean_test_db: psycopg.Connection,
) -> None:
    _apply(clean_test_db, DDL)

    info = SchemaAnalyzer(clean_test_db).get_schema_info(schemas=["public"])

    assert info.constraint_indexes == {
        "public.t": {"t_pkey", "t_code_key", "t_label_uq"},
        "public.u": {"u_pkey"},
    }
    assert set(info.indexes["public.t"]) == {"t_pkey", "t_code_key", "t_label_uq", "idx_t_code"}
