"""Check registry and composition runner for ``migrate validate`` (#187).

``migrate validate`` used to be a flat chain of ``if <flag>: … return`` blocks
evaluated in source order, so any two validation flags meant the second one was
silently skipped and the gate still exited 0. This module replaces the chain
with an ordered registry of descriptors: the command builds the enabled list,
the runner executes all of them, and the outcomes aggregate into one exit code
and one JSON document.

The registry's order deliberately reproduces the old source order, so a
single-flag invocation is byte-identical to 0.39.0 — that is what keeps the
blast radius of a 940-line refactor survivable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from confiture.core.error_codes import EXIT_CODE_SEMANTIC_CLASS

if TYPE_CHECKING:
    from confiture.core.validation.context import ValidationContext


@dataclass(frozen=True)
class CheckOutcome:
    """What one check reported.

    Attributes:
        check: Stable machine name, and the key this check's payload takes in a
            composed JSON envelope (``"acl_coverage"``, ``"imports"``, …).
        passed: False when the check found something the gate should fail on.
            Advisory findings that never failed the gate (an unpinned
            SECURITY DEFINER at warning severity, say) stay ``passed=True``.
        exit_code: The process exit code this check signals when it does not
            pass. Every check signals ``1`` today; the field exists so a check
            with a different semantic class composes rather than being coerced.
        payload: The JSON-mode document for this check, or ``None`` in text
            mode. Checks never write output themselves — the runner emits once.
    """

    check: str
    passed: bool
    exit_code: int = 1
    payload: dict[str, Any] | None = None

    @property
    def semantic_class(self) -> str:
        """This outcome's exit-code class per the 0.38.0 contract (#193)."""
        return EXIT_CODE_SEMANTIC_CLASS[0 if self.passed else self.exit_code]


@dataclass(frozen=True)
class ValidationCheck:
    """One registered check: what turns it on, and what it needs to run.

    Attributes:
        flag: The CLI flag that enables it, for error messages.
        name: Stable machine name, matching the :class:`CheckOutcome` it emits.
        enabled: Whether this run asked for it.
        run: Executes the check against the shared context.
        needs_db: Declares the shared live connection. Checks that declare it
            get one connection between them, not one each.
        needs_git: Declares a git working tree (validated once, before any
            git-backed check runs).
        report_only: A catalog/report mode with no gate semantics. These do not
            compose — see ``exclusive``.
        exclusive: Reject any other check alongside this one.
        requires: Flags that must also be enabled for this check to be legal.
    """

    flag: str
    name: str
    enabled: bool
    run: Callable[[ValidationContext], CheckOutcome]
    needs_db: bool = False
    needs_git: bool = False
    report_only: bool = False
    exclusive: bool = False
    requires: tuple[str, ...] = ()


def enabled_checks(checks: Sequence[ValidationCheck]) -> list[ValidationCheck]:
    """The subset this run asked for, in registry (= historical source) order."""
    return [c for c in checks if c.enabled]


def run_checks(checks: Sequence[ValidationCheck], ctx: ValidationContext) -> list[CheckOutcome]:
    """Run every enabled check in order and collect what each reported.

    Findings compose; genuine failures do not. A check that raises
    ``ConfiturError`` (bad config, unreachable database, missing git ref)
    propagates immediately to the command's ``fail()`` boundary, exactly as it
    did before composition existed — an infrastructure failure is not a finding
    to be aggregated, and continuing would emit an error envelope alongside
    unrelated check output.
    """
    return [check.run(ctx) for check in enabled_checks(checks)]


def aggregate_exit_code(outcomes: Sequence[CheckOutcome]) -> int:
    """The exit code for a whole run: the first failing check's, in order.

    Every check signals exit 1 today, so "first failing" and "worst" are the
    same integer and the ordering question does not arise. It is resolved this
    way rather than by a severity ladder because the exit-code taxonomy is not
    ordered by severity — 3 (``db_unreachable``) and 7 (``git_error``) are
    siblings, not degrees. A check introducing a second distinct code must
    revisit this function rather than inherit an accident.
    """
    for outcome in outcomes:
        if not outcome.passed:
            return outcome.exit_code
    return 0


def compose_payload(outcomes: Sequence[CheckOutcome]) -> dict[str, Any] | None:
    """Merge per-check JSON payloads into the one document the run emits.

    A single check emits its payload **verbatim**, so every documented
    single-check schema keeps its exact shape. Two or more emit a wrapper keyed
    by check name — a new shape for a combination that previously could not
    happen at all.

    Returns:
        The document to emit, or ``None`` when no check produced one (text mode).
    """
    with_payload = [o for o in outcomes if o.payload is not None]
    if not with_payload:
        return None
    if len(with_payload) == 1:
        return with_payload[0].payload

    return {
        "version": "1",
        "status": "passed" if all(o.passed for o in outcomes) else "failed",
        "checks": {o.check: o.payload for o in with_payload},
        "hints": [],
    }
