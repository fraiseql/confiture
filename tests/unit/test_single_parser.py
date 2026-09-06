"""One parser: pglast, with no switch to anything else (Phase 05, D13).

Two backends and fifty-odd switches meant every DDL question had two answers
and a third state — "which one ran?" — that nothing reported (#210, #216). The
regex detector, the regex replica classifier, the regex change-set walker and
the sqlparse paths are gone; so are the env vars, module flags and test markers
that selected them. This test keeps them gone.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import confiture

REPO = Path(__file__).resolve().parents[2]
PACKAGE = Path(confiture.__file__).resolve().parent
TESTS = REPO / "tests"

SWITCH_TOKENS = (
    "CONFITURE_IDEMPOTENCY_FORCE_REGEX",
    "CONFITURE_REPLICA_FORCE_REGEX",
    "_use_ast",
    "regex_only",
    "xfail_under_ast",
    "ast_only",
    "_HAS_PGLAST",
    "is_pglast_available",
    "_force_regex",
    "_detect_via_regex",
    "_classify_regex",
    "_regex_entries",
    "_mask_for_regex",
    "_parse_regex",
    "_analyze_regex",
    "_parse_create_tables_sqlparse",
    "idempotency_backend",
)
_TOKEN_RE = re.compile("|".join(re.escape(t) for t in SWITCH_TOKENS))


def find_switch_tokens(*roots: Path) -> list[str]:
    findings: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name == Path(__file__).name or "fixtures" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _TOKEN_RE.search(line):
                    findings.append(
                        f"{path.relative_to(REPO).as_posix()}:{lineno}: {line.strip()[:80]}"
                    )
    return findings


def test_no_backend_switch_survives() -> None:
    findings = find_switch_tokens(PACKAGE, TESTS)
    assert findings == [], f"{len(findings)} backend switches remain:\n  " + "\n  ".join(
        findings[:40]
    )


def _top_level_functions(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.update(
                f"{node.name}.{n.name}" for n in node.body if isinstance(n, ast.FunctionDef)
            )
    return names


def test_patterns_exports_only_the_ast_detector() -> None:
    names = _top_level_functions(PACKAGE / "core" / "idempotency" / "patterns.py")
    assert not {n for n in names if "regex" in n.lower()}, names
    source = (PACKAGE / "core" / "idempotency" / "patterns.py").read_text(encoding="utf-8")
    assert "PatternDefinition(" not in source, (
        "the regex pattern table is gone; the catalog is data"
    )


def test_classifier_and_change_set_have_one_path_each() -> None:
    classifier = _top_level_functions(PACKAGE / "core" / "replica" / "classifier.py")
    change_set = _top_level_functions(PACKAGE / "core" / "change_set.py")
    assert not {n for n in classifier if "regex" in n.lower()}, classifier
    assert not {n for n in change_set if "regex" in n.lower()}, change_set
