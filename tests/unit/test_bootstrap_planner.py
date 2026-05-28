"""Unit tests for ``BootstrapPlanner`` (issue #137 part 1).

The planner is pure read-only logic — it queries pg_roles / pg_class /
pg_namespace and decides which bootstrap steps are needed.  These tests
mock the connection so they run without a real PostgreSQL.

Integration tests covering the executor against a real DB live in
``tests/integration/test_bootstrap_executor.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.bootstrap import (
    BootstrapPlan,
    BootstrapPlanner,
    BootstrapStep,
)
from confiture.exceptions import BootstrapScopeError


def _make_ownership(
    *,
    owner: str = "migrator",
    apply_to_schemas: list[str] | None = None,
    default_privileges: dict[str, dict[str, list[str]]] | None = None,
) -> OwnershipExpectation:
    schemas = apply_to_schemas if apply_to_schemas is not None else ["tenant"]
    return OwnershipExpectation(
        expected_owner=owner,
        apply_to=[OwnershipApplyTo(schema=s) for s in schemas],
        default_privileges=default_privileges,
    )


def _make_conn(
    *,
    role_exists: bool = True,
    postgres_owned_schemas: list[str] | None = None,
) -> MagicMock:
    """Mock a psycopg connection that answers planner queries."""
    conn = MagicMock()

    def execute_side_effect(query: str, params: tuple | None = None):
        result = MagicMock()
        if "pg_roles" in query and "rolname" in query and "%s" in query:
            result.fetchone.return_value = (1,) if role_exists else None
        elif "pg_class" in query and "DISTINCT" in query:
            owned = postgres_owned_schemas or []
            result.fetchall.return_value = [(s,) for s in owned]
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    conn.execute.side_effect = execute_side_effect
    return conn


# ---------------------------------------------------------------------------
# Cycle 1: empty-plan happy path
# ---------------------------------------------------------------------------


def test_empty_plan_when_role_exists_and_no_drift() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership())
    conn = _make_conn(role_exists=True, postgres_owned_schemas=[])
    plan = planner.plan(conn)
    assert plan.is_empty
    assert plan.observed_postgres_owned_schemas == ()


# ---------------------------------------------------------------------------
# Cycle 2: role creation step
# ---------------------------------------------------------------------------


def test_plan_includes_role_creation_when_missing() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership())
    conn = _make_conn(role_exists=False, postgres_owned_schemas=[])
    plan = planner.plan(conn)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.label == "create_role"
    assert "CREATE ROLE" in step.sql
    assert '"migrator"' in step.sql


# ---------------------------------------------------------------------------
# Cycle 3: REASSIGN OWNED step
# ---------------------------------------------------------------------------


def test_plan_includes_reassign_when_postgres_owns_in_scope_schemas() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership(apply_to_schemas=["tenant"]))
    conn = _make_conn(
        role_exists=True,
        postgres_owned_schemas=["tenant"],  # In scope
    )
    plan = planner.plan(conn)
    labels = [s.label for s in plan.steps]
    assert "reassign_owned" in labels
    reassign = next(s for s in plan.steps if s.label == "reassign_owned")
    assert "REASSIGN OWNED BY postgres TO" in reassign.sql
    assert '"migrator"' in reassign.sql


# ---------------------------------------------------------------------------
# Cycle 4: --all-schemas safety check
# ---------------------------------------------------------------------------


def test_plan_refuses_without_all_schemas_flag_when_outside_apply_to() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership(apply_to_schemas=["tenant"]))
    conn = _make_conn(
        role_exists=True,
        postgres_owned_schemas=["tenant", "public"],  # public is out of scope
    )
    with pytest.raises(BootstrapScopeError) as excinfo:
        planner.plan(conn, all_schemas=False)
    assert "public" in str(excinfo.value)


def test_plan_allows_reassign_with_all_schemas_flag() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership(apply_to_schemas=["tenant"]))
    conn = _make_conn(
        role_exists=True,
        postgres_owned_schemas=["tenant", "public"],
    )
    plan = planner.plan(conn, all_schemas=True)
    labels = [s.label for s in plan.steps]
    assert "reassign_owned" in labels


# ---------------------------------------------------------------------------
# Cycle 6: ALTER DEFAULT PRIVILEGES step
# ---------------------------------------------------------------------------


def test_plan_includes_alter_default_privileges_per_schema_role() -> None:
    planner = BootstrapPlanner(
        ownership=_make_ownership(
            apply_to_schemas=["tenant"],
            default_privileges={
                "tenant": {
                    "app": ["SELECT", "INSERT", "UPDATE", "DELETE"],
                    "readonly": ["SELECT"],
                }
            },
        )
    )
    conn = _make_conn(role_exists=True, postgres_owned_schemas=[])
    plan = planner.plan(conn)
    adp_steps = [s for s in plan.steps if s.label.startswith("default_privileges_")]
    assert len(adp_steps) == 2
    for s in adp_steps:
        assert "ALTER DEFAULT PRIVILEGES FOR ROLE" in s.sql
        assert "IN SCHEMA" in s.sql
        assert "GRANT" in s.sql
        assert "ON TABLES TO" in s.sql
    sqls = " | ".join(s.sql for s in adp_steps)
    assert "SELECT, INSERT, UPDATE, DELETE" in sqls
    assert '"app"' in sqls
    assert '"readonly"' in sqls


def test_plan_omits_default_privileges_when_unconfigured() -> None:
    planner = BootstrapPlanner(ownership=_make_ownership(default_privileges=None))
    conn = _make_conn(role_exists=True, postgres_owned_schemas=[])
    plan = planner.plan(conn)
    assert not any(
        s.label.startswith("default_privileges_") for s in plan.steps
    )


# ---------------------------------------------------------------------------
# Plan serialization
# ---------------------------------------------------------------------------


def test_plan_to_dict_round_trips_steps() -> None:
    step = BootstrapStep(
        label="dummy",
        sql="SELECT 1",
        description="noop",
    )
    plan = BootstrapPlan(steps=(step,))
    data = plan.to_dict()
    assert data["steps"] == [
        {"label": "dummy", "sql": "SELECT 1", "description": "noop"}
    ]
    assert data["is_empty"] is False
