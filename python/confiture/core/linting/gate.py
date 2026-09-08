"""What makes ``confiture lint`` fail, and whether the threshold it was given can be reached.

``--fail-on-error`` is on by default and, before 1.4.0, no rule in the registry
emitted at ``error`` — so the flag a CI pipeline reaches for to make lint block
was a flag that could not block, and four real ``build_001`` findings sat in a
green pipeline for months (#247). Two booleans could express three of the four
useful settings and not the fourth ("report, never fail"), and neither of them
could say *whether the setting was reachable at all*.

One threshold decides the exit code, and :func:`compute_gate` answers the second
question from the registry's declared severities plus the configuration
escalations a project has made — so a project that *has* escalated is told the
truth rather than a generic warning.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from confiture.core.linting.rule_registry import LINT_RULES
from confiture.exceptions import ConfigurationError

#: How severe each severity is. ``never`` is above every finding, which is what
#: makes "report, never fail" a threshold rather than a special case.
_RANK: dict[str, int] = {"info": 1, "warning": 2, "error": 3, "never": 4}


class Threshold(str, Enum):
    """The severity at which a run starts failing."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    NEVER = "never"

    @property
    def rank(self) -> int:
        return _RANK[self.value]


def parse_threshold(value: str) -> Threshold:
    """``--fail-on``'s value as a :class:`Threshold`.

    Raises:
        ConfigurationError: The value is not one of the four. Picking a
            plausible default for a misspelled gate is how a gate goes quiet.
    """
    try:
        return Threshold(value.strip().lower())
    except ValueError:
        raise ConfigurationError(
            f"Unknown severity in --fail-on: {value!r}",
            error_code="CONFIG_010",
            resolution_hint=(
                "Valid values: error, warning, info, never. "
                "`--fail-on-error` and `--fail-on-warning` are aliases for the first two."
            ),
        ) from None


def threshold_from_aliases(*, fail_on_error: bool, fail_on_warning: bool) -> Threshold:
    """The threshold the two pre-1.4.0 booleans express between them."""
    if fail_on_warning:
        return Threshold.WARNING
    return Threshold.ERROR if fail_on_error else Threshold.NEVER


def should_fail(severities: Iterable[str], threshold: Threshold) -> bool:
    """Whether any finding reaches the threshold.

    ``never`` outranks every severity, so nothing reaches it — which is the
    point of the value.
    """
    return any(_RANK.get(severity, 0) >= threshold.rank for severity in severities)


@dataclass(frozen=True)
class Gate:
    """What decides this run's exit code, and whether anything can reach it.

    Attributes:
        threshold: The severity at which the run fails.
        reachable: Whether any selected rule can emit at or above it.
        reason: Why not, in the words the summary line uses; ``None`` when
            reachable.
        max_selectable_severity: The most severe finding the selection can
            produce, escalations applied; ``None`` when no rule is selected.
    """

    threshold: Threshold
    reachable: bool
    reason: str | None
    max_selectable_severity: str | None

    def to_dict(self) -> dict[str, Any]:
        """The ``gate`` block of ``lint --format json``."""
        return {
            "threshold": self.threshold.value,
            "reachable": self.reachable,
            "reason": self.reason,
            "max_selectable_severity": self.max_selectable_severity,
        }


def _ceiling(selected: Iterable[str], escalations: Mapping[str, str]) -> str | None:
    """The most severe thing the selection can emit, escalations applied."""
    by_code = {rule.code: rule for rule in LINT_RULES}
    severities = [
        escalations.get(code, by_code[code].severity) for code in selected if code in by_code
    ]
    return max(severities, key=lambda s: _RANK[s], default=None)


def compute_gate(
    *,
    threshold: Threshold,
    selected: Iterable[str],
    escalations: Mapping[str, str] | None = None,
    baseline_active: bool = False,
) -> Gate:
    """Whether this run can fail, and why not when it cannot.

    Args:
        threshold: The severity ``--fail-on`` set.
        selected: The rule codes the run applies.
        escalations: Codes whose configured severity is above the registry's
            declaration — ``security_lint.severity`` for ``sec_002``, declared
            replicas for ``replica_001``.
        baseline_active: A ``--baseline`` run fails on any new finding whatever
            its severity, so the threshold is not the only way out.
    """
    ceiling = _ceiling(selected, escalations or {})
    if threshold is Threshold.NEVER:
        return Gate(threshold, False, "--fail-on never: no finding can fail this run", ceiling)
    if baseline_active:
        return Gate(threshold, True, None, ceiling)
    if ceiling is None:
        return Gate(threshold, False, "no rule is selected; this run cannot fail", None)
    if _RANK[ceiling] >= threshold.rank:
        return Gate(threshold, True, None, ceiling)
    return Gate(
        threshold,
        False,
        f"no selected rule emits at '{threshold.value}'; this gate cannot fail "
        "— see --fail-on and --baseline",
        ceiling,
    )
