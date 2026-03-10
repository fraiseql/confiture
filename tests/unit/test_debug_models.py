"""Unit tests for CTE debug models."""

from __future__ import annotations

import pytest

from confiture.models.debug_models import CTEDebugSession, CTEStepResult


def _make_step(name: str = "base", error: str | None = None) -> CTEStepResult:
    return CTEStepResult(
        cte_name=name,
        row_count=0 if error else 3,
        columns=[] if error else ["id", "name"],
        rows=[] if error else [(1, "Alice"), (2, "Bob"), (3, "Carol")],
        execution_time_ms=5.0,
        error=error,
    )


def test_cte_step_result_success():
    step = _make_step("users")
    assert step.success is True
    assert step.row_count == 3


def test_cte_step_result_failure():
    step = _make_step("bad_cte", error="relation 'missing_table' does not exist")
    assert step.success is False
    assert step.error is not None


def test_cte_step_result_to_dict():
    step = _make_step("users")
    d = step.to_dict()
    assert d["cte_name"] == "users"
    assert d["row_count"] == 3
    assert "columns" in d
    assert "rows" in d
    assert d["error"] is None


def test_cte_debug_session_all_succeeded():
    session = CTEDebugSession(
        original_query="WITH a AS (SELECT 1) SELECT * FROM a",
        steps=[_make_step("a"), _make_step("b")],
        total_ctes=2,
    )
    assert session.all_succeeded is True
    assert session.failed_at is None


def test_cte_debug_session_failed_at():
    session = CTEDebugSession(
        original_query="WITH a AS (SELECT 1), b AS (SELECT * FROM missing) SELECT * FROM b",
        steps=[_make_step("a"), _make_step("b", error="table missing does not exist")],
        total_ctes=2,
    )
    assert session.all_succeeded is False
    assert session.failed_at == "b"


def test_cte_debug_session_to_dict():
    session = CTEDebugSession(
        original_query="WITH a AS (SELECT 1) SELECT * FROM a",
        steps=[_make_step("a")],
        total_ctes=1,
    )
    d = session.to_dict()
    assert d["total_ctes"] == 1
    assert d["all_succeeded"] is True
    assert d["failed_at"] is None
    assert len(d["steps"]) == 1
