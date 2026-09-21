"""What an ``--idempotent`` run concludes from its report: a status, a pass, an exit.

The status says what was found — ``issues_found`` when any violation exists,
``unverified`` when none does but a call could not be read, ``ok`` only when every
call was read and nothing was found (#213). The flags change whether that fails the
gate, never the status: ``--strict-cor`` makes an info-severity finding blocking,
``--fail-on-unanalyzable`` makes *unverified* fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from confiture.error_codes import FINDINGS


@dataclass(frozen=True)
class Verdict:
    """``status`` for the payload, ``passed`` for the gate, ``exit_code`` when it fails."""

    status: str
    passed: bool
    exit_code: int = FINDINGS


def judge(report: Any, *, strict_cor: bool, fail_on_unanalyzable: bool) -> Verdict:
    """The verdict on *report* (an ``IdempotencyReport``) under the run's two flags."""
    violation_fail = report.has_violations if strict_cor else report.has_blocking_violations
    unverified_fail = fail_on_unanalyzable and not report.analysis_complete
    if report.has_violations:
        status = "issues_found"
    elif report.analysis_complete:
        status = "ok"
    else:
        status = "unverified"
    return Verdict(status, not (violation_fail or unverified_fail))
