"""Every test asserts something (TST-04).

A test function with no assertion passes whenever the code under test does
not raise. That is a smoke test at best and, more often, a test that once
asserted and lost it in a refactor. Every ``test_*`` function must contain an
``assert``, a ``pytest.raises`` / ``pytest.fail`` / ``pytest.warns``, a
``unittest``-style ``self.assert*`` or ``mock.assert_*`` call, or a call to a
helper whose name says it asserts (``assert_…``, ``check_…``, ``verify_…``,
``expect_…``).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
_ASSERTING_CALL = re.compile(r"^(assert|check|verify|expect|_assert|_check|_verify|_expect)\w*$")
_PYTEST_ASSERTING = {"raises", "fail", "warns", "deprecated_call", "approx", "xfail", "skip"}


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _asserts_something(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if (
                    isinstance(item.context_expr, ast.Call)
                    and _call_name(item.context_expr) in _PYTEST_ASSERTING
                ):
                    return True
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if (
                name in _PYTEST_ASSERTING
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pytest"
            ):
                return True
            if name.startswith("assert_") or (name.startswith("assert") and name[6:7].isupper()):
                return True  # mock.assert_called_with, self.assertEqual
            if _ASSERTING_CALL.match(name):
                return True
    return False


def _asserting_helpers(tree: ast.Module) -> set[str]:
    """Names of functions defined in this module whose body asserts (one level deep)."""
    helpers: set[str] = set()
    for node in ast.walk(tree):
        is_helper = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
            node.name.startswith("test_")
        )
        if is_helper and _asserts_something(node):
            helpers.add(node.name)
    return helpers


def _calls_any(fn: ast.AST, names: set[str]) -> bool:
    return any(isinstance(node, ast.Call) and _call_name(node) in names for node in ast.walk(fn))


def find_assertion_less_tests(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if "fixtures" in path.parts or path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        helpers = _asserting_helpers(tree)
        for node in ast.walk(tree):
            is_test = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name.startswith("test_")
            )
            if is_test and not (_asserts_something(node) or _calls_any(node, helpers)):
                rel = path.relative_to(root.parent).as_posix()
                findings.append(f"{rel}:{node.lineno}: {node.name}")
    return findings


def test_every_test_function_asserts_something() -> None:
    findings = find_assertion_less_tests(TESTS_ROOT)
    assert findings == [], f"{len(findings)} tests without an assertion:\n  " + "\n  ".join(
        findings
    )


def _scan(src: str) -> int:
    tree = ast.parse(src)
    return sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name.startswith("test_")
        and not _asserts_something(n)
    )


def test_detector_shapes() -> None:
    assert _scan("def test_a():\n    x = f()\n") == 1
    assert _scan("def test_a():\n    assert f()\n") == 0
    assert _scan("def test_a():\n    with pytest.raises(ValueError):\n        f()\n") == 0
    assert _scan("def test_a():\n    m.assert_called_once()\n") == 0
    assert _scan("def test_a():\n    self.assertEqual(1, 1)\n") == 0
    assert _scan("def test_a():\n    _assert_clean(report)\n") == 0
    assert _scan("def test_a():\n    verify_envelope(payload)\n") == 0
    assert _scan("def test_a():\n    pytest.fail('x')\n") == 0
