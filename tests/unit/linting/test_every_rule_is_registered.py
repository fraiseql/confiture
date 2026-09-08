"""Every rule that can emit a violation is in the registry.

A rule outside `LINT_RULES` is invisible to `--list-rules`, cannot be named by
`--select` or `--ignore`, and — because the registry is where `compute_gate`
reads declared severities — cannot be counted when `confiture lint` answers
"can this gate fire at all". Seven rules were in exactly that position
(`func_001`, `own_001`, `own_002` and the four file-tree rules), one of them at
`error`, which is why `--fail-on-error` could truthfully report that no
selected rule reaches `error` while an `error` rule sat in the tree.

This walks the AST of every module under `core/linting/` for the rule codes it
declares and fails on one the registry does not know. Two allow-lists, each
entry stating why the code is not a registry rule: the dormant compliance
catalogues, which are descriptions with no `check()` and no caller, and the
`UNPARSEABLE` notice, which is what a rule reports when it could not run.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from confiture.core.linting.rule_registry import LINT_RULES

LINTING_ROOT = Path(__file__).resolve().parents[3] / "python" / "confiture" / "core" / "linting"

#: What a rule code looks like: `doc_001`, `pci_dss_010`, and the pre-1.4.0
#: uppercase tree codes.
_CODE_SHAPE = re.compile(r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)*_\d{3}|GEN\d{3})$")

#: Rule catalogues that describe rules rather than implement them: a tuple of
#: descriptions built on `versioning.Rule`, with no `check()` anywhere and no
#: command that reaches them. Listing them in `LINT_RULES` would promise a lint
#: that does not exist, which is the failure this guard is here to prevent —
#: in the other direction.
DORMANT_CATALOGUES: dict[str, str] = {
    "libraries/gdpr.py": "18 GDPR descriptions on versioning.Rule; no check(), no caller",
    "libraries/hipaa.py": "15 HIPAA descriptions on versioning.Rule; no check(), no caller",
    "libraries/sox.py": "12 SOX descriptions on versioning.Rule; no check(), no caller",
    "libraries/pci_dss.py": "10 PCI-DSS descriptions on versioning.Rule; no check(), no caller",
    "libraries/general.py": "general best-practice descriptions; no check(), no caller",
}

#: Codes that are not rules at all.
NOT_A_RULE: dict[str, str] = {
    "UNPARSEABLE": (
        "the notice a rule emits when pglast rejected a file — it reports that a rule "
        "could not run, so it has no severity to declare and nothing to select"
    ),
}


def _declared_codes(tree: ast.AST) -> set[str]:
    """Every rule code one module declares.

    Three shapes, because the rules use three: a `rule_id=` keyword on a
    `LintViolation`, a `rule_id` / `RULE_ID` binding at class or module level,
    and a bare string in a table of codes (`documentation.py`'s kind map, the
    compliance catalogues' rows).
    """
    codes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "rule_id":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                codes.add(node.value.value)
        elif isinstance(node, ast.AnnAssign | ast.Assign):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if names & {"rule_id", "RULE_ID"} or any(n.endswith("RULE_ID") for n in names):
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    codes.add(value.value)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _CODE_SHAPE.match(node.value)
        ):
            codes.add(node.value)
    return codes


def _unregistered() -> dict[str, set[str]]:
    """Module path (relative to `core/linting/`) → codes the registry does not know."""
    registered = {rule.code for rule in LINT_RULES}
    found: dict[str, set[str]] = {}
    for module in sorted(LINTING_ROOT.rglob("*.py")):
        rel = module.relative_to(LINTING_ROOT).as_posix()
        if rel in DORMANT_CATALOGUES:
            continue
        codes = _declared_codes(ast.parse(module.read_text(encoding="utf-8")))
        unknown = {c for c in codes if c not in registered and c not in NOT_A_RULE}
        if unknown:
            found[rel] = unknown
    return found


def test_every_implemented_rule_has_a_registry_entry() -> None:
    """A code no registry entry declares cannot be selected, ignored or baselined."""
    unregistered = _unregistered()

    assert unregistered == {}, (
        "these rule codes emit violations but LINT_RULES does not know them: "
        f"{ {k: sorted(v) for k, v in unregistered.items()} }"
    )


def test_the_allow_lists_still_describe_something_real() -> None:
    """An allow-list entry for a module that no longer exists is stale permission."""
    missing = [rel for rel in DORMANT_CATALOGUES if not (LINTING_ROOT / rel).exists()]

    assert missing == [], f"allow-listed modules that no longer exist: {missing}"


def test_every_allow_list_entry_states_a_reason() -> None:
    """An allow-list is only honest while each entry says why the code is exempt."""
    unexplained = [
        key
        for key, reason in (*DORMANT_CATALOGUES.items(), *NOT_A_RULE.items())
        if len(reason.split()) < 5
    ]

    assert unexplained == [], f"allow-list entries with no stated reason: {unexplained}"
