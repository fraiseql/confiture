"""Every switch `SchemaLinter` dispatches on belongs to a rule the catalogue knows.

`test_every_rule_is_registered` holds one direction: a rule that emits without a
registry entry is invisible to `--list-rules`, `--select` and `--baseline`. This
holds the other: a `LintConfig` switch with no registered rule behind it is a
knob that promises a check, and `check_indexes` was exactly that — on by
default, dispatched on every lint, running two schema-wide regexes and
discarding the result.

The pair is what makes the campaign's first constraint real in both directions:
the registry is the single source of truth for a rule's existence, so a switch
is a rule's switch or it is nothing.

Why the dispatch is keyed on switches and not on rule codes, which is the
question a reader arrives with: one method serves several codes
(`_check_documentation` emits `doc_001` through `doc_004`), two switches share
one method (`qual_001` and `qual_002`), and `LintConfig` is the library API — a
caller sets `check_documentation=True`, not a set of codes. Per-code selection
happens where it belongs, on the findings, in `_keep_selected_rules`. The two
tables are keyed differently on purpose; this test is what keeps them agreeing.
"""

from __future__ import annotations

import inspect

from confiture.cli.commands.schema import _linter_config
from confiture.core.linting.gate import Threshold
from confiture.core.linting.rule_registry import LINT_RULES
from confiture.core.linting.schema_linter import LintConfig


def _switches() -> list[str]:
    """Every `check_*` parameter `LintConfig` accepts."""
    return [
        name
        for name in inspect.signature(LintConfig.__init__).parameters
        if name.startswith("check_")
    ]


def _on(selected: frozenset[str]) -> set[str]:
    """The switches this selection turns on."""
    config = _linter_config(selected, Threshold.NEVER)
    return {name for name in _switches() if getattr(config, name)}


def _switches_for(code: str) -> set[str]:
    """The switches selecting exactly *code* turns on that nothing else does."""
    return _on(frozenset({code})) - _on(frozenset())


def test_selecting_no_rule_turns_on_no_check() -> None:
    """`--ignore default` selects nothing, so nothing should run.

    A switch on for the empty selection is on unconditionally — no `--ignore`
    reaches it, because no rule code controls it.
    """
    assert sorted(_on(frozenset())) == []


def test_every_switch_is_turned_on_by_some_registered_rule() -> None:
    """A switch no rule reaches is a check the catalogue does not offer."""
    reachable: set[str] = set()
    for rule in LINT_RULES:
        reachable |= _switches_for(rule.code)

    assert sorted(set(_switches()) - reachable) == []


def test_every_rule_that_runs_through_the_linter_turns_on_a_switch() -> None:
    """And the converse, so a registered rule cannot be one nothing dispatches.

    The rules whose subject is a *tree of files* are dispatched by code in
    `_tree_rule_findings`, after the linter has run, so they legitimately turn
    on no switch.
    """
    from confiture.cli.commands.schema import TREE_RULE_CODES

    by_tree = {"replica_001", "sec_002", "func_001", "own_001", "own_002", *TREE_RULE_CODES}
    orphans = [
        rule.code
        for rule in LINT_RULES
        if rule.code not in by_tree and not _switches_for(rule.code)
    ]

    assert orphans == []
