"""Integration tests for :class:`OwnershipDriftDetector` (issue #124).

Requires a running PostgreSQL accessible via ``CONFITURE_TEST_DB_URL``.

Mirrors :mod:`tests.integration.test_acl_drift_detector` on the ownership
axis.  Each test creates the relevant relkinds (table, sequence, view,
matview) under a dedicated schema, sets their owners, then asks the
detector to compare against an :class:`OwnershipExpectation`.
"""

from __future__ import annotations

from collections.abc import Generator

import psycopg
import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.drift import (
    DriftSeverity,
    DriftType,
    OwnershipDriftDetector,
)

_TEST_SCHEMA = "own_drift_test"
_TEST_ROLES = ("own_migrator", "own_intruder")


@pytest.fixture
def own_db(clean_test_db: psycopg.Connection) -> Generator[psycopg.Connection, None, None]:
    """Clean test schema and roles before/after each test."""
    conn = clean_test_db

    def _cleanup() -> None:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
            for role in _TEST_ROLES:
                cur.execute(f"DROP ROLE IF EXISTS {role}")
        conn.commit()

    _cleanup()
    with conn.cursor() as cur:
        for role in _TEST_ROLES:
            cur.execute(f"CREATE ROLE {role}")
        # Grant CREATE on database to the migrator so it can own things.
        cur.execute(f"CREATE SCHEMA {_TEST_SCHEMA} AUTHORIZATION own_migrator")
        # Make the current user a member of both roles so ALTER ... OWNER TO
        # works in tests (the test runner needs membership in the target).
        cur.execute("GRANT own_migrator TO current_user")
        cur.execute("GRANT own_intruder TO current_user")
    conn.commit()

    yield conn

    _cleanup()


def _expectation_for(relkinds: list[str]) -> OwnershipExpectation:
    return OwnershipExpectation(
        expected_owner="own_migrator",
        apply_to=[OwnershipApplyTo(schema=_TEST_SCHEMA, relkinds=relkinds)],
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_detects_table_owned_by_wrong_role(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.orphan_table (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.orphan_table OWNER TO own_intruder")
    own_db.commit()

    detector = OwnershipDriftDetector(own_db)
    report = detector.check(_expectation_for(["r"]))

    assert report.database_name
    assert report.expected_schema_source == "ownership"
    items = report.drift_items
    assert len(items) == 1
    assert items[0].drift_type == DriftType.WRONG_OWNER
    assert items[0].severity == DriftSeverity.CRITICAL
    assert "own_intruder" in items[0].message
    assert "own_migrator" in items[0].message
    assert f"{_TEST_SCHEMA}.orphan_table" in items[0].object_name


def test_correct_owner_yields_no_drift(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_good (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_good OWNER TO own_migrator")
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["r"]))
    assert report.drift_items == []
    assert report.has_drift is False


# ---------------------------------------------------------------------------
# Ignore list
# ---------------------------------------------------------------------------


def test_ignore_list_skips_drifted_objects(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_a (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_a OWNER TO own_intruder")
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_b (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_b OWNER TO own_intruder")
    own_db.commit()

    exp = OwnershipExpectation(
        expected_owner="own_migrator",
        apply_to=[OwnershipApplyTo(schema=_TEST_SCHEMA, relkinds=["r"])],
        ignore=[f"{_TEST_SCHEMA}.tb_a"],
    )
    report = OwnershipDriftDetector(own_db).check(exp)
    assert len(report.drift_items) == 1
    assert "tb_b" in report.drift_items[0].object_name


def test_ignore_glob_star_schema(own_db: psycopg.Connection) -> None:
    """``*.legacy_audit_log`` matches across schemas."""
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.legacy_audit_log (id int)")
        cur.execute(
            f"ALTER TABLE {_TEST_SCHEMA}.legacy_audit_log OWNER TO own_intruder"
        )
    own_db.commit()

    exp = OwnershipExpectation(
        expected_owner="own_migrator",
        apply_to=[OwnershipApplyTo(schema=_TEST_SCHEMA, relkinds=["r"])],
        ignore=["*.legacy_audit_log"],
    )
    report = OwnershipDriftDetector(own_db).check(exp)
    assert report.drift_items == []


# ---------------------------------------------------------------------------
# Cross-relkind coverage
# ---------------------------------------------------------------------------


def test_sequence_owned_by_wrong_role_flagged(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE SEQUENCE {_TEST_SCHEMA}.seq_drift")
        cur.execute(f"ALTER SEQUENCE {_TEST_SCHEMA}.seq_drift OWNER TO own_intruder")
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["S"]))
    assert len(report.drift_items) == 1
    assert report.drift_items[0].drift_type == DriftType.WRONG_OWNER
    assert "seq_drift" in report.drift_items[0].object_name


def test_view_owned_by_wrong_role_flagged(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.base_tb (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.base_tb OWNER TO own_migrator")
        cur.execute(f"CREATE VIEW {_TEST_SCHEMA}.v_drift AS SELECT id FROM {_TEST_SCHEMA}.base_tb")
        cur.execute(f"ALTER VIEW {_TEST_SCHEMA}.v_drift OWNER TO own_intruder")
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["v"]))
    assert len(report.drift_items) == 1
    assert "v_drift" in report.drift_items[0].object_name


def test_materialized_view_owned_by_wrong_role_flagged(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.mv_base (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.mv_base OWNER TO own_migrator")
        cur.execute(
            f"CREATE MATERIALIZED VIEW {_TEST_SCHEMA}.mv_drift AS "
            f"SELECT id FROM {_TEST_SCHEMA}.mv_base"
        )
        cur.execute(
            f"ALTER MATERIALIZED VIEW {_TEST_SCHEMA}.mv_drift OWNER TO own_intruder"
        )
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["m"]))
    assert len(report.drift_items) == 1
    assert "mv_drift" in report.drift_items[0].object_name


# ---------------------------------------------------------------------------
# Partition children are individually checked
# ---------------------------------------------------------------------------


def test_partition_child_with_drifted_owner_is_flagged(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events "
            "(id int, occurred_at date) PARTITION BY RANGE (occurred_at)"
        )
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_events OWNER TO own_migrator")
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events_2026 "
            f"PARTITION OF {_TEST_SCHEMA}.tb_events "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')"
        )
        cur.execute(
            f"ALTER TABLE {_TEST_SCHEMA}.tb_events_2026 OWNER TO own_intruder"
        )
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["r"]))
    drifted = [i for i in report.drift_items if "2026" in i.object_name]
    assert len(drifted) == 1


# ---------------------------------------------------------------------------
# Empty schema
# ---------------------------------------------------------------------------


def test_empty_schema_yields_no_drift(own_db: psycopg.Connection) -> None:
    report = OwnershipDriftDetector(own_db).check(_expectation_for(["r", "S", "v", "m"]))
    assert report.drift_items == []
    assert report.has_drift is False


def test_report_counts_relations_checked(own_db: psycopg.Connection) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_a (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_a OWNER TO own_migrator")
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_b (id int)")
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_b OWNER TO own_migrator")
    own_db.commit()

    report = OwnershipDriftDetector(own_db).check(_expectation_for(["r"]))
    assert report.tables_checked == 2
