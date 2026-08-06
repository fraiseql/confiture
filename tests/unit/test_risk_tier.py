"""The risk-tier taxonomy that crosses the migration-adapter seam (#197).

The five tiers, their ``snake_case`` wire values and their severity ordering are
a ratified cross-repo contract (fraisier-core#44,
``docs/proposals/migration-risk-contract.md``). These tests pin them from
confiture's side so a rename fails here rather than silently in the consumer.
"""

from __future__ import annotations

import pytest

from confiture.core.risk_tier import RiskTier, worst_tier


def test_the_wire_values_are_exactly_the_five_contract_tiers():
    assert [t.value for t in RiskTier] == [
        "additive",
        "reversible",
        "lock_risky",
        "destructive",
        "irreversible",
    ]


def test_the_declaration_order_is_least_to_most_severe():
    """`additive < reversible < lock_risky < destructive < irreversible`."""
    ordered = list(RiskTier)
    assert sorted(ordered, key=lambda t: t.severity) == ordered


@pytest.mark.parametrize(
    ("tiers", "expected"),
    [
        ([RiskTier.ADDITIVE, RiskTier.IRREVERSIBLE], RiskTier.IRREVERSIBLE),
        ([RiskTier.DESTRUCTIVE, RiskTier.LOCK_RISKY], RiskTier.DESTRUCTIVE),
        ([RiskTier.ADDITIVE], RiskTier.ADDITIVE),
    ],
)
def test_worst_tier_picks_the_most_severe(tiers, expected):
    assert worst_tier(tiers) is expected


def test_worst_tier_of_nothing_is_none():
    assert worst_tier([]) is None


def test_worst_tier_skips_unclassified_entries():
    """An unclassifiable change must not mask a classified one.

    Per the plan's D4 ruling: `unknown` never dominates the aggregate, or one
    unreadable `.py` migration would conceal a `DROP TABLE`.
    """
    assert worst_tier([None, RiskTier.IRREVERSIBLE, None]) is RiskTier.IRREVERSIBLE


def test_worst_tier_of_only_unclassified_is_none():
    assert worst_tier([None, None]) is None
