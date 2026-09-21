"""What an ``--idempotent`` run concludes from its report: status, pass/fail, exit.

The status says what was found; the flags change whether that fails the gate,
never the status (#213): ``unverified`` is its own answer, distinct from
``checked and clean``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from confiture.core.idempotency.verdict import judge
from confiture.error_codes import FINDINGS


@dataclass
class _Report:
    has_violations: bool = False
    has_blocking_violations: bool = False
    analysis_complete: bool = True
    violations: list = field(default_factory=list)


@pytest.mark.parametrize(
    ("report", "strict_cor", "fail_on_unanalyzable", "expected"),
    [
        (_Report(), False, False, ("ok", True)),
        (
            _Report(has_violations=True, has_blocking_violations=True),
            False,
            False,
            ("issues_found", False),
        ),
        (_Report(has_violations=True), False, False, ("issues_found", True)),
        (_Report(has_violations=True), True, False, ("issues_found", False)),
        (_Report(analysis_complete=False), False, False, ("unverified", True)),
        (_Report(analysis_complete=False), False, True, ("unverified", False)),
    ],
)
def test_the_verdict(report, strict_cor, fail_on_unanalyzable, expected) -> None:
    verdict = judge(report, strict_cor=strict_cor, fail_on_unanalyzable=fail_on_unanalyzable)
    assert (verdict.status, verdict.passed) == expected
    assert verdict.exit_code == FINDINGS
