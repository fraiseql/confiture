"""Help text states what the code does, from the table that decides it (#423, #430).

A consumer reads the help and wires its handling to it: a sentence that says a
finding cannot happen is a finding nobody handles. So the help is checked against
the source of truth — the drift kinds ``DriftType`` can report, the rule catalogue
``--list-rules`` prints — and cannot drift from it again.
"""

from __future__ import annotations

import re

from confiture.cli.commands.lint import lint
from confiture.cli.commands.migrate.validate import CheckLiveDriftOpt
from confiture.core.drift import DriftType
from confiture.core.linting.rule_registry import LINT_RULES, UNPARSEABLE_RULE_ID

#: Reported by the separate grant and ownership checks, not by --check-live-drift.
_OTHER_CHECKS = {DriftType.MISSING_GRANT, DriftType.EXTRA_GRANT, DriftType.WRONG_OWNER}


def _live_drift_help() -> str:
    (option,) = CheckLiveDriftOpt.__metadata__
    return " ".join(option.help.split())


def _codes(text: str) -> set[str]:
    """Every rule code a paragraph names, ranges (``doc_001–doc_004``) expanded."""
    found: set[str] = set()
    for first, last in re.findall(r"\b([a-z]+_\d{3})(?:–([a-z]+_\d{3}))?", text):
        if not last:
            found.add(first)
            continue
        family, start = first.rsplit("_", 1)
        end = int(last.rsplit("_", 1)[1])
        found.update(f"{family}_{n:03d}" for n in range(int(start), end + 1))
    return found


def _paragraph(doc: str, opening: str) -> str:
    """The help paragraph that starts with ``opening``, whitespace collapsed."""
    for block in re.split(r"\n\s*\n", doc):
        text = " ".join(block.split())
        if text.startswith(opening):
            return text
    raise AssertionError(f"lint --help has no paragraph starting {opening!r}")


def test_live_drift_help_names_every_finding_it_reports() -> None:
    text = _live_drift_help()

    missing = [kind.value for kind in DriftType if kind not in _OTHER_CHECKS]
    missing = [kind for kind in missing if kind not in text]
    assert missing == []


def test_live_drift_help_does_not_deny_what_it_compares() -> None:
    assert "NOT compared" not in _live_drift_help()


def test_lint_help_lists_exactly_the_rules_on_by_default() -> None:
    expected = {r.code for r in LINT_RULES if r.default_on and r.code != UNPARSEABLE_RULE_ID}

    assert _codes(_paragraph(lint.__doc__ or "", "On by default:")) == expected


def test_lint_help_lists_exactly_the_opt_in_rules() -> None:
    expected = {r.code for r in LINT_RULES if not r.default_on}

    assert _codes(_paragraph(lint.__doc__ or "", "Opt-in")) == expected


def test_lint_help_names_every_default_rule_that_fails_a_plain_lint() -> None:
    failing = {r.code for r in LINT_RULES if r.default_on and r.severity == "error"}
    failing.discard(UNPARSEABLE_RULE_ID)

    assert _codes(_paragraph(lint.__doc__ or "", "Of those,")) == failing
