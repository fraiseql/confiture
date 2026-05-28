"""Integration tests for ``BootstrapExecutor`` (issue #137 part 1).

Requires a local PostgreSQL superuser ``postgres``.  Each test
provisions a throwaway database, runs the planner + executor, and
verifies the post-state in pg_catalog.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.bootstrap import BootstrapExecutor, BootstrapPlanner


def _drop_test_roles() -> None:
    """Best-effort cleanup of test roles; called pre- and post-test."""
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
    except psycopg.OperationalError:
        return
    try:
        for role in ("bootstrap_migrator_test", "bootstrap_app_test"):
            try:
                admin.execute(f"DROP OWNED BY {role} CASCADE")
            except psycopg.Error:
                pass
            try:
                admin.execute(f'DROP ROLE IF EXISTS "{role}"')
            except psycopg.Error:
                pass
    finally:
        admin.close()


@pytest.fixture()
def bootstrap_db() -> str:
    """Provision a throwaway database connected as superuser."""
    _drop_test_roles()
    db_name = f"confiture_bootstrap_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
        admin.execute(f'CREATE DATABASE "{db_name}"')
        admin.close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")

    db_url = f"postgresql://localhost/{db_name}"
    try:
        yield db_url
    finally:
        _drop_test_roles()
        try:
            admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            admin.close()
        except psycopg.OperationalError:
            pass


def _role_exists(conn: psycopg.Connection, role: str) -> bool:
    row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    return row is not None


@pytest.mark.integration
def test_apply_creates_missing_role(bootstrap_db: str) -> None:
    """Empty database → executor creates the role and the second plan is empty."""
    ownership = OwnershipExpectation(
        expected_owner="bootstrap_migrator_test",
        apply_to=[OwnershipApplyTo(schema="public")],
    )

    with psycopg.connect(bootstrap_db, autocommit=False) as conn:
        planner = BootstrapPlanner(ownership=ownership)
        plan = planner.plan(conn, all_schemas=True)
        labels = {s.label for s in plan.steps}
        assert "create_role" in labels

        executor = BootstrapExecutor()
        result = executor.apply(plan, conn)

    assert result.success
    assert "create_role" in result.applied_steps

    # Verify the role now exists.
    with psycopg.connect(bootstrap_db) as verify:
        assert _role_exists(verify, "bootstrap_migrator_test")


@pytest.mark.integration
def test_apply_twice_is_idempotent(bootstrap_db: str) -> None:
    """A second plan after a successful --apply is empty (role + reassign only)."""
    ownership = OwnershipExpectation(
        expected_owner="bootstrap_migrator_test",
        apply_to=[OwnershipApplyTo(schema="public")],
    )

    with psycopg.connect(bootstrap_db, autocommit=False) as conn:
        planner = BootstrapPlanner(ownership=ownership)
        executor = BootstrapExecutor()

        first = planner.plan(conn, all_schemas=True)
        executor.apply(first, conn)

        # Re-plan: role exists, no postgres-owned objects exist in the
        # fresh DB, so the second plan has nothing to do.
        second = planner.plan(conn, all_schemas=True)
        assert second.is_empty


@pytest.mark.integration
def test_apply_emits_default_privileges_statements(bootstrap_db: str) -> None:
    """`default_privileges` block → ALTER DEFAULT PRIVILEGES per schema/role pair."""
    # First create the grantee role via a dedicated bootstrap pass.
    with psycopg.connect(bootstrap_db, autocommit=True) as admin:
        admin.execute('CREATE ROLE "bootstrap_app_test" NOLOGIN')

    ownership = OwnershipExpectation(
        expected_owner="bootstrap_migrator_test",
        apply_to=[OwnershipApplyTo(schema="public")],
        default_privileges={"public": {"bootstrap_app_test": ["SELECT"]}},
    )

    with psycopg.connect(bootstrap_db, autocommit=False) as conn:
        planner = BootstrapPlanner(ownership=ownership)
        plan = planner.plan(conn, all_schemas=True)
        adp_steps = [s for s in plan.steps if s.label.startswith("default_privileges_")]
        assert len(adp_steps) == 1
        executor = BootstrapExecutor()
        result = executor.apply(plan, conn)

    assert result.success
    assert adp_steps[0].label in result.applied_steps

    # Verify the ALTER DEFAULT PRIVILEGES landed in pg_default_acl.
    with psycopg.connect(bootstrap_db) as verify:
        row = verify.execute(
            """
            SELECT defaclacl::text
            FROM pg_default_acl d
            JOIN pg_namespace n ON n.oid = d.defaclnamespace
            JOIN pg_roles r ON r.oid = d.defaclrole
            WHERE n.nspname = 'public'
              AND r.rolname = 'bootstrap_migrator_test'
            """
        ).fetchone()
        assert row is not None, "ALTER DEFAULT PRIVILEGES did not land"
        assert "bootstrap_app_test" in row[0]
