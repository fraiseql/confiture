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
    report = detector.check(expectations)

    assert report.database_name  # populated, not the empty string
    assert report.expected_schema_source == "acls"
    items = report.drift_items
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
    report = AclDriftDetector(acl_db).check(expectations)
    assert report.drift_items == []
    assert report.has_drift is False


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
    report = AclDriftDetector(acl_db).check(expectations)

    extras = [i for i in report.drift_items if i.drift_type == DriftType.EXTRA_GRANT]
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
    report = detector.check(expectations)
    assert report.drift_items == []  # 3 checked, 2 ignored, 0 violations


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
    report = AclDriftDetector(acl_db).check(expectations)
    assert report.drift_items == []


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
    report = AclDriftDetector(acl_db).check(expectations)
    extras = [i for i in report.drift_items if i.drift_type == DriftType.EXTRA_GRANT]
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
    report = AclDriftDetector(acl_db).check(expectations)
    items = report.drift_items
    assert len(items) >= 1
    assert all(i.severity == DriftSeverity.WARNING for i in items)
    assert any("acl_missing_role" in i.message for i in items)


# ---------------------------------------------------------------------------
# Group A — Design-rationale tests pinning the asymmetric query paths.
#
# A future maintainer who "simplifies" both paths to one form will trip
# these.  They exist to make sure role-membership inheritance, PUBLIC,
# ownership, and WITH GRANT OPTION all stay correctly handled.
# ---------------------------------------------------------------------------


def test_role_inheritance_does_not_false_positive(acl_db: psycopg.Connection) -> None:
    """Child of ``parent`` sees a grant on the parent via inheritance.

    ``has_table_privilege`` honours role membership; ``role_table_grants``
    only enumerates direct grants — so the child neither shows MISSING
    (because privilege is held via inheritance) nor EXTRA (no direct row).
    """
    with acl_db.cursor() as cur:
        # acl_app is the inheriting child of acl_admin.
        cur.execute("GRANT acl_admin TO acl_app")
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_foo TO acl_admin")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    assert report.drift_items == []


def test_public_grant_does_not_false_positive(acl_db: psycopg.Connection) -> None:
    """``GRANT SELECT TO PUBLIC`` satisfies ANY role's SELECT expectation."""
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_foo TO PUBLIC")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    # SELECT-via-PUBLIC means no MISSING.  No direct grant means no EXTRA.
    missing = [i for i in report.drift_items if i.drift_type == DriftType.MISSING_GRANT]
    extras = [i for i in report.drift_items if i.drift_type == DriftType.EXTRA_GRANT]
    assert missing == []
    assert extras == []


def test_ownership_does_not_false_positive(acl_db: psycopg.Connection) -> None:
    """Table owner holds implicit ALL — must not show as MISSING."""
    with acl_db.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_owned (id int)",
        )
        cur.execute(f"ALTER TABLE {_TEST_SCHEMA}.tb_owned OWNER TO acl_admin")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_admin", privileges=["SELECT", "UPDATE", "DELETE"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    missing = [i for i in report.drift_items if i.drift_type == DriftType.MISSING_GRANT]
    assert missing == []


def test_with_grant_option_is_normalized(acl_db: psycopg.Connection) -> None:
    """``WITH GRANT OPTION`` doesn't affect coverage detection."""
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_foo TO acl_app WITH GRANT OPTION")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    assert report.drift_items == []


def test_unrelated_table_not_in_acls_is_ignored(acl_db: psycopg.Connection) -> None:
    """Tables outside the apply_to scope don't surface even with random grants."""
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.tb_listed (id int)")
        cur.execute(f"CREATE TABLE {_TEST_SCHEMA}.unrelated (id int)")
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_listed TO acl_app")
        # ``unrelated`` carries a grant we deliberately don't expect.
        cur.execute(f"GRANT INSERT ON {_TEST_SCHEMA}.unrelated TO acl_etl")
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to=["tb_*"],
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    # Only ``tb_listed`` is in scope; ``unrelated`` is outside ``tb_*``.
    assert report.drift_items == []


# ---------------------------------------------------------------------------
# Partition handling — phase 06.  Parent appears in ``relkind = 'p'`` and
# must be discovered; children with ``relispartition = true`` must not
# spuriously surface as extras.
# ---------------------------------------------------------------------------


def test_detects_missing_grant_on_partitioned_parent(acl_db: psycopg.Connection) -> None:
    """Partitioned parent (``relkind = 'p'``) is included in discovery."""
    with acl_db.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events "
            "(id int, occurred_at date) PARTITION BY RANGE (occurred_at)"
        )
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events_2026 "
            f"PARTITION OF {_TEST_SCHEMA}.tb_events "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')"
        )
        # No grant on the parent — should be flagged.
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    parent_items = [
        i
        for i in report.drift_items
        if "tb_events" in i.object_name and "2026" not in i.object_name
    ]
    assert any(i.drift_type == DriftType.MISSING_GRANT for i in parent_items)


def test_partition_child_not_double_reported(acl_db: psycopg.Connection) -> None:
    """Child of a partitioned parent doesn't generate spurious items."""
    with acl_db.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events "
            "(id int, occurred_at date) PARTITION BY RANGE (occurred_at)"
        )
        cur.execute(f"GRANT SELECT ON {_TEST_SCHEMA}.tb_events TO acl_app")
        cur.execute(
            f"CREATE TABLE {_TEST_SCHEMA}.tb_events_2026 "
            f"PARTITION OF {_TEST_SCHEMA}.tb_events "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')"
        )
    acl_db.commit()

    expectations = [
        AclExpectation(
            schema="acl_drift_test",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="acl_app", privileges=["SELECT"])],
        )
    ]
    report = AclDriftDetector(acl_db).check(expectations)
    # The child is excluded; only the parent's row is in scope and it has
    # the required SELECT.  Zero drift items.
    assert report.drift_items == []
