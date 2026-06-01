"""Pure rollback planner for `migrate down-to` (issue #142).

Given the applied sequence, the set of known migration versions, a target
revision, and the set of versions that have a usable ``.down.sql``, compute the
ordered rollback set (newest → oldest) and fully validate reversibility — all
*without touching the database*. Execution (Phase 2) consumes a validated plan.

This module imports nothing DB-related on purpose; correctness lives here and is
trivially unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# Typed reasons for an invalid plan (mirrors the issue's four edge cases).
REASON_TARGET_NEWER = "target_newer_than_current"
REASON_UNKNOWN = "unknown_revision"
REASON_IRREVERSIBLE = "irreversible"


@dataclass
class RollbackPlan:
    """The computed rollback plan.

    Attributes:
        target: The revision to roll back *to* (stays applied).
        to_rollback: Versions to roll back, newest → oldest. Populated even for
            an irreversible plan so the error can name the offending set.
        valid: Whether the plan can be executed.
        noop: True when ``target`` is already the current revision.
        reason: Why an invalid plan failed (one of the REASON_* constants).
        missing_down: Versions in ``to_rollback`` lacking a usable ``.down.sql``.
    """

    target: str
    to_rollback: list[str]
    valid: bool
    noop: bool = False
    reason: str | None = None
    missing_down: list[str] = field(default_factory=list)


def plan_down_to(
    applied: list[str],
    known: Iterable[str],
    target: str,
    down_available: Iterable[str],
) -> RollbackPlan:
    """Compute the rollback plan to reach ``target``.

    Args:
        applied: Applied versions in ascending ``applied_at`` order.
        known: All discoverable migration versions (applied or not).
        target: The revision to roll back to (kept applied).
        down_available: Versions with a present, constructible ``.down.sql``
            (or a reversible Python ``down()``).

    Returns:
        A ``RollbackPlan``. Invalid plans carry a typed ``reason`` and never a
        partial execution instruction — the caller refuses atomically.
    """
    known_set = set(known)
    down_set = set(down_available)

    if target not in applied:
        # Known-but-not-applied → a forward move; otherwise genuinely unknown.
        reason = REASON_TARGET_NEWER if target in known_set else REASON_UNKNOWN
        return RollbackPlan(target=target, to_rollback=[], valid=False, reason=reason)

    idx = applied.index(target)
    if idx == len(applied) - 1:
        return RollbackPlan(target=target, to_rollback=[], valid=True, noop=True)

    to_rollback = list(reversed(applied[idx + 1 :]))  # newest → oldest
    missing = [v for v in to_rollback if v not in down_set]
    if missing:
        return RollbackPlan(
            target=target,
            to_rollback=to_rollback,
            valid=False,
            reason=REASON_IRREVERSIBLE,
            missing_down=missing,
        )

    return RollbackPlan(target=target, to_rollback=to_rollback, valid=True)
