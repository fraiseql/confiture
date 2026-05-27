"""Tests for idempotency suggestion templates (Phase 04, issue #123).

The catalog of patterns is split into two disjoint frozensets:

- ``TEMPLATE_FILLABLE`` — captures-driven template available.
- ``TEMPLATE_NOT_AVAILABLE`` — generic suggestion only.

Every :class:`IdempotencyPattern` member must belong to exactly one of
these sets — neither both nor neither.
"""

from __future__ import annotations

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import (
    TEMPLATE_FILLABLE,
    TEMPLATE_NOT_AVAILABLE,
)


def test_each_pattern_classification() -> None:
    """Every pattern is in exactly one of the two classification sets."""
    for pattern in IdempotencyPattern:
        in_fillable = pattern in TEMPLATE_FILLABLE
        in_not_available = pattern in TEMPLATE_NOT_AVAILABLE
        assert in_fillable != in_not_available, (
            f"{pattern.name} must be in exactly one of "
            f"TEMPLATE_FILLABLE / TEMPLATE_NOT_AVAILABLE; got "
            f"fillable={in_fillable}, not_available={in_not_available}"
        )


def test_classification_sets_are_disjoint() -> None:
    """The two sets share no members."""
    assert frozenset() == TEMPLATE_FILLABLE & TEMPLATE_NOT_AVAILABLE


def test_classification_sets_cover_all_patterns() -> None:
    """Union of both sets equals the full IdempotencyPattern enum."""
    all_patterns = set(IdempotencyPattern)
    union = TEMPLATE_FILLABLE | TEMPLATE_NOT_AVAILABLE
    assert union == all_patterns, (
        f"Missing patterns: {all_patterns - union}; extra patterns: {union - all_patterns}"
    )
