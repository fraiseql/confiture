"""Integration tests for :class:`AclDriftDetector` (issue #120).

Requires a running PostgreSQL accessible via ``CONFITURE_TEST_DB_URL``.

Roles are server-scoped, not database-scoped, so each test uses a small set
of well-known role names and the fixture cleans them up explicitly.
"""

from __future__ import annotations

from collections.abc import Generator

import psycopg
import pytest

from confiture.config.environment import AclExpectation, AclGrant
from confiture.core.drift import (
    AclDriftDetector,
    DriftSeverity,
    DriftType,
)

# Schema and role names scoped to this test module to avoid stomping on
# unrelated suites that share the same Postgres instance.
_TEST_SCHEMA = "acl_drift_test"
_TEST_ROLES = ("acl_app", "acl_etl", "acl_admin", "acl_missing_role")


@pytest.fixture
def acl_db(clean_test_db: psycopg.Connection) -> Generator[psycopg.Connection, None, None]:
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
        cur.execute(f"CREATE SCHEMA {_TEST_SCHEMA}")
        for role in _TEST_ROLES:
            cur.execute(f"CREATE ROLE {role}")
    conn.commit()

    yield conn

    _cleanup()


# ---------------------------------------------------------------------------
# MISSING_GRANT path — has_table_privilege()
# ---------------------------------------------------------------------------


def test_detects_missing_grant(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_foo TO acl_app")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT", "INSERT"])],
        )
    ]
    detector = AclDriftDetector(acl_db)
    items = detector.check(expectations)

    assert len(items) == 1
    assert items[0].drift_type == DriftType.MISSING_GRANT
    assert items[0].severity == DriftSeverity.CRITICAL
    assert "INSERT" in items[0].message
    assert f"{_TEST_SCHEMA}.tb_foo" in items[0].object_name
    assert "acl_app" in items[0].object_name or "acl_app" in items[0].message


def test_full_coverage_yields_no_items(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT, INSERT ON {_TEST_SCHEMA}.tb_foo TO acl_app")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT", "INSERT"])],
        )
    ]
    items = AclDriftDetector(acl_db).check(expectations)
    assert items == []


# ---------------------------------------------------------------------------
# EXTRA_GRANT path — information_schema.role_table_grants
# ---------------------------------------------------------------------------


def test_detects_extra_grant(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        # Spec says SELECT, INSERT — DB has UPDATE on top.
        cur.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TEST_SCHEMA}.tb_foo TO acl_app")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT", "INSERT"])],
        )
    ]
    items = AclDriftDetector(acl_db).check(expectations)

    extras = [i for i in items if i.drift_type == DriftType.EXTRA_GRANT]
    assert len(extras) == 1
    assert extras[0].severity == DriftSeverity.WARNING
    assert "UPDATE" in extras[0].message


# ---------------------------------------------------------------------------
# apply_to + ignore globs
# ---------------------------------------------------------------------------


def test_ignore_globs_skip_matched_tables(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        for name in ("tb_a", "tb_b", "tb_c", "tb_a_legacy", "tb_b_tmp"):
            cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.{name} (id int)")
            cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.{name} TO acl_app")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            ignore=["*_legacy", "*_tmp"],
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    detector = AclDriftDetector(acl_db)
    items = detector.check(expectations)
    assert items == []  # 3 checked, 2 ignored, 0 violations


def test_apply_to_pattern_list_filters_tables(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_match (id int)")
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.skip_me (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_match TO acl_app")
        # skip_me has no grants; should NOT be reported because pattern excludes it
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to=["tb_*"],
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    items = AclDriftDetector(acl_db).check(expectations)
    assert items == []


# ---------------------------------------------------------------------------
# PUBLIC inheritance asymmetry — directly granted vs inherited via PUBLIC
# ---------------------------------------------------------------------------


def test_public_inheritance_not_reported_as_extra(acl_db: psycopg.Connection) -> None:
    """A privilege the role only has via PUBLIC must not show up as EXTRA_GRANT.

    ``has_table_privilege`` answers YES for SELECT (via PUBLIC), so MISSING_GRANT
    works.  ``role_table_grants`` lists only direct grants, so it must NOT
    surface SELECT as extra when the role's expectation is empty.
    """
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_foo TO PUBLIC")
    acl_db.commit()

    # acl_app expects nothing — only SELECT-via-PUBLIC is in play.
    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=[])],
        )
    ]
    items = AclDriftDetector(acl_db).check(expectations)
    extras = [i for i in items if i.drift_type == DriftType.EXTRA_GRANT]
    assert extras == []


# ---------------------------------------------------------------------------
# Missing role → WARNING, not crash
# ---------------------------------------------------------------------------


def test_missing_role_reports_warning(acl_db: psycopg.Connection) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        # Drop the role specifically so we can reference a missing one.
        cur.execute("DROP ROLE acl_missing_role")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_missing_role", privileges=["SELECT"])],
        )
    ]
    items = AclDriftDetector(acl_db).check(expectations)
    assert len(items) >= 1
    assert all(i.severity == DriftSeverity.WARNING for i in items)
    assert any("acl_missing_role" in i.message for i in items)
