"""Unit tests for the pure rollback planner (issue #142, Phase 1).

The planner computes the rollback set and validates reversibility up front,
without touching the database. The four edge cases are typed outcomes.
"""

from __future__ import annotations

from confiture.core._migrator.rollback_planner import RollbackPlan, plan_down_to

APPLIED = ["20260101_a", "20260102_b", "20260103_c", "20260104_d"]  # ASC
KNOWN = set(APPLIED)
ALL_DOWN = set(APPLIED)


def test_rolls_back_newer_than_target() -> None:
    plan = plan_down_to(APPLIED, KNOWN, target="20260102_b", down_available=ALL_DOWN)
    assert plan.valid
    assert plan.to_rollback == ["20260104_d", "20260103_c"]  # newest → oldest
    assert plan.target == "20260102_b"
    assert not plan.noop


def test_target_is_current_is_noop() -> None:
    plan = plan_down_to(APPLIED, KNOWN, target="20260104_d", down_available=ALL_DOWN)
    assert plan.valid
    assert plan.to_rollback == []
    assert plan.noop


def test_target_newer_than_current_rejected() -> None:
    # Known migration file that is not yet applied → forward move.
    plan = plan_down_to(
        APPLIED, KNOWN | {"20260105_e"}, target="20260105_e", down_available=ALL_DOWN
    )
    assert not plan.valid
    assert plan.reason == "target_newer_than_current"


def test_unknown_target_rejected() -> None:
    plan = plan_down_to(APPLIED, KNOWN, target="nope", down_available=ALL_DOWN)
    assert not plan.valid
    assert plan.reason == "unknown_revision"


def test_missing_down_aborts_whole_plan() -> None:
    plan = plan_down_to(
        APPLIED, KNOWN, target="20260101_a", down_available=ALL_DOWN - {"20260103_c"}
    )
    assert not plan.valid
    assert plan.reason == "irreversible"
    assert plan.missing_down == ["20260103_c"]
    # to_rollback still computed (newest→oldest) so the error can name the set.
    assert plan.to_rollback == ["20260104_d", "20260103_c", "20260102_b"]


def test_rollback_to_oldest_keeps_first() -> None:
    plan = plan_down_to(APPLIED, KNOWN, target="20260101_a", down_available=ALL_DOWN)
    assert plan.valid
    assert plan.to_rollback == ["20260104_d", "20260103_c", "20260102_b"]


def test_empty_applied_unknown_target() -> None:
    plan = plan_down_to([], set(), target="anything", down_available=set())
    assert not plan.valid
    assert plan.reason == "unknown_revision"


def test_plan_is_a_dataclass_with_defaults() -> None:
    plan = RollbackPlan(target="x", to_rollback=[], valid=True)
    assert plan.noop is False
    assert plan.reason is None
    assert plan.missing_down == []


def test_planner_imports_nothing_db_related() -> None:
    """Purity guard: the planner module must not import psycopg / DB machinery."""
    from pathlib import Path

    import confiture.core._migrator.rollback_planner as mod

    text = Path(mod.__file__).read_text()
    assert "psycopg" not in text
    assert "import" in text  # sanity: the file does have imports (dataclasses)
