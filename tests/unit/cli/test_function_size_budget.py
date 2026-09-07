"""No CLI function body exceeds 150 lines.

Options are declarations, not logic, so a command's *body* is measured from
its first statement after the docstring. The CLI declares and renders; the
session and core do the work.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[3] / "python" / "confiture" / "cli"
BUDGET = 150
FILES = sorted(CLI_ROOT.rglob("*.py"))


def _body_lines(fn: ast.FunctionDef) -> int:
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if not body:
        return 0
    return fn.end_lineno - body[0].lineno + 1  # type: ignore[operator]


def _oversized(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        f"{path.name}:{node.name} has {_body_lines(node)} body lines (budget {BUDGET})"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _body_lines(node) > BUDGET
    ]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CLI_ROOT)))
def test_functions_fit_the_budget(path: Path) -> None:
    assert _oversized(path) == []
