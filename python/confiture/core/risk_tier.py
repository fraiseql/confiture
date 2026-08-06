"""Risk-tier taxonomy for the migration-adapter seam (issue #197).

One tier per schema change, crossing the seam as typed data beside the
``window_safe`` boolean rather than being recovered by string-matching issue
codes. The five values, their ``snake_case`` wire form and their severity
ordering are ratified in fraisier-core's
``docs/proposals/migration-risk-contract.md`` (contract version 1) and pinned
from this side by ``tests/unit/test_risk_tier.py``.

Two properties are deliberate and load-bearing:

* **Five tiers, no ``unknown``.** A change confiture cannot classify carries *no*
  tier at all — the consumer reads that as unclassified and denies. An
  ``unknown`` member would be a sixth wire value, which the contract makes a
  ``contract_version`` conversation rather than a silent addition.
* **The ordering is for picking the worst of a set, not for deciding policy.**
  Consumers map each tier to an action independently.

This module is pure: no I/O, no database, no parser. That is what the deleted
``core/risk/`` package (a never-wired DowntimePredictor, removed at ``2bf38f1``)
was not.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

__all__ = ["RiskTier", "worst_tier"]


class RiskTier(Enum):
    """What kind of risk a single schema change carries.

    Declared least- to most-severe; :attr:`severity` is the declaration index.
    """

    ADDITIVE = "additive"
    """Adds a new object. No existing reader or writer can break."""

    REVERSIBLE = "reversible"
    """Changes existing state, with a down path that restores it."""

    LOCK_RISKY = "lock_risky"
    """Semantically safe, but takes a lock that can stall a hot table."""

    DESTRUCTIVE = "destructive"
    """Destroys data or an object; the loss is bounded and restorable from backup."""

    IRREVERSIBLE = "irreversible"
    """Destroys data with no down path that can restore it."""

    @property
    def severity(self) -> int:
        """Position in ``additive < reversible < lock_risky < destructive < irreversible``.

        Used to pick the worst tier in a change set and to sort a plan render
        worst-first. It is **not** how policy decisions are made.
        """
        return _SEVERITY[self]


# Declaration order is the severity order; derived once so the two cannot drift.
_SEVERITY: dict[RiskTier, int] = {tier: index for index, tier in enumerate(RiskTier)}


def worst_tier(tiers: Iterable[RiskTier | None]) -> RiskTier | None:
    """The most severe tier in ``tiers``, ignoring unclassified (``None``) entries.

    Returns ``None`` when nothing was classifiable. Unclassified entries are
    skipped rather than dominating: a change set holding one unreadable ``.py``
    migration *and* a ``DROP TABLE`` must still report the drop, or the more
    dangerous change hides behind the less informative one.
    """
    classified = [tier for tier in tiers if tier is not None]
    if not classified:
        return None
    return max(classified, key=lambda tier: tier.severity)
