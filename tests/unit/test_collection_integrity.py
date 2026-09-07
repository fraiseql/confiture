"""The test count means what it says: no test is parametrized over local artefacts (TST-01).

A parity probe once parametrized over every ``*.sql`` under the repo root, so a
developer machine contributed ~1,600 gitignored ``db/schema_history/`` snapshots
(written by the suite itself) and the local run collected ~3,000 more tests
than CI — a gap carried for months as "cause unknown" (#207). That probe is
gone (pglast parses the raw file); what stays is the rule: a
test module builds its parametrizations from files the repository tracks —
paths under ``tests/`` — never from a filesystem walk of the repo root.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"


_CLIMBS_TO_REPO_ROOT = re.compile(r"parents\[[2-9]\]|(\.parent){3,}")
# Trees the repository tracks in full; a walk that descends into one of them
# sees the same files locally and in CI.
_TRACKED_TREES = frozenset({"python", "tests", "docs", ".github"})
_FIRST_SEGMENT = re.compile(r"/\s*['\"]([^'\"/]+)")


def _walks_untracked_ground(expr: str) -> bool:
    """A climb to the repo root that does not descend into a fully tracked tree."""
    m = _CLIMBS_TO_REPO_ROOT.search(expr)
    if not m:
        return False
    seg = _FIRST_SEGMENT.search(expr, m.end())
    return seg is None or seg.group(1) not in _TRACKED_TREES


def repo_root_walks(root: Path) -> list[str]:
    """Module-level ``.rglob``/``.glob`` calls over the repo root or an untracked tree.

    Walking tracked source (``ROOT / "python" / "confiture" / "cli"``) is fine —
    every file there is tracked. Walking the root itself, or ``ROOT / "db"``, is
    the #207 shape: whatever is on disk under the checkout, generated or not,
    becomes a test id.
    """
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name == Path(__file__).name or "fixtures" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # a fixture that is deliberately not valid Python
            continue
        assigned = {
            t.id: ast.unparse(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        for node in tree.body:  # module level only: that is what parametrizes collection
            for call in ast.walk(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("rglob", "glob")
                ):
                    continue
                receiver = ast.unparse(call.func.value)
                # Resolve one level of naming: `X.rglob(...)` where `X = <climb> / ...`.
                for name, value in assigned.items():
                    receiver = receiver.replace(name, f"({value})")
                if _walks_untracked_ground(receiver):
                    findings.append(
                        f"{path.relative_to(root.parent).as_posix()}:{call.lineno} {ast.unparse(call)}"
                    )
    return findings


def test_no_test_module_parametrizes_over_a_repo_root_walk() -> None:
    findings = repo_root_walks(TESTS_ROOT)
    assert findings == [], (
        "test collection depends on what happens to be on disk:\n  "
        + "\n  ".join(findings)
        + "\nBuild the parametrization from tracked fixtures under tests/."
    )


LAYER_DIRS = frozenset({"unit", "integration", "e2e", "performance", "contract"})


def test_every_test_directory_is_a_layer() -> None:
    """A test lives in one of the five layers; there is no sixth directory.

    ``tests/migration_testing`` was a parallel tree with its own database
    convention (``DATABASE_URL``), its own connection handling and 114 tests of
    PostgreSQL rather than of confiture; the collection clean-up folded what mattered
    into the layers (D2).
    """
    tests_root = REPO_ROOT / "tests"
    stray = sorted(
        d.name
        for d in tests_root.iterdir()
        if d.is_dir() and d.name not in LAYER_DIRS and any(d.rglob("test_*.py"))
    )
    assert stray == [], f"test directories outside the five layers: {stray}"
