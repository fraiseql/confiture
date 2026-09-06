"""``assert A or B`` without a reason is a budget that may only shrink (TST-04).

A disjunctive assertion passes when *either* side holds, so it pins less than it
looks like it does. Some are legitimate — two spellings of the same message, two
exit codes that are both real verdicts — and those carry a comment saying why.
The uncommented ones are counted here against a baseline that may only go down:
review one, either pin it or explain it, and lower the number.

Phase 02 Cycle 7 reviewed and resolved every disjunction over an exit code (the
class that hides a wrong verdict); the rest are frozen at this baseline.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

# Lower this number when you pin or explain a disjunctive assertion. Never raise it.
BASELINE = 183


def find_uncommented_disjunctions(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if "fixtures" in path.parts or path.name == Path(__file__).name:
            continue
        src = path.read_text(encoding="utf-8")
        lines = src.split("\n")
        for node in ast.walk(ast.parse(src)):
            if not (
                isinstance(node, ast.Assert)
                and isinstance(node.test, ast.BoolOp)
                and isinstance(node.test.op, ast.Or)
            ):
                continue
            if "#" not in "\n".join(lines[node.lineno - 1 : node.end_lineno]):
                findings.append(f"{path.relative_to(root.parent).as_posix()}:{node.lineno}")
    return findings


def test_uncommented_disjunctions_do_not_grow() -> None:
    findings = find_uncommented_disjunctions(TESTS_ROOT)
    assert len(findings) <= BASELINE, (
        f"{len(findings)} uncommented `assert A or B` (baseline {BASELINE}); new ones:\n  "
        + "\n  ".join(findings[-10:])
        + "\nPin the assertion, or add a comment saying why either side is acceptable."
    )


def test_baseline_is_current() -> None:
    """The baseline records the real count: lower it when the count drops."""
    findings = find_uncommented_disjunctions(TESTS_ROOT)
    assert len(findings) == BASELINE, (
        f"count is {len(findings)}; set BASELINE = {len(findings)} in this file"
    )


def test_no_exit_code_disjunction_without_a_reason() -> None:
    """A disjunction over an exit code hides a wrong verdict; each one says why."""
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if "fixtures" in path.parts or path.name == Path(__file__).name:
            continue
        src = path.read_text(encoding="utf-8")
        lines = src.split("\n")
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Assert):
                continue
            text = ast.unparse(node.test)
            disjunctive = isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.Or)
            multi_code = (
                isinstance(node.test, ast.Compare)
                and any(isinstance(op, ast.In) for op in node.test.ops)
                and ast.unparse(node.test.left).endswith("exit_code")
            )
            if (disjunctive and "exit_code" in text) or multi_code:
                # a reason may sit on the assert itself or on the line just above
                window = "\n".join(lines[max(0, node.lineno - 2) : node.end_lineno])
                if "#" not in window:
                    offenders.append(
                        f"{path.relative_to(TESTS_ROOT.parent).as_posix()}:{node.lineno}: {text}"
                    )
    assert offenders == [], "\n  ".join(offenders)
