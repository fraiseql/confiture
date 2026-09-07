"""Quality budgets only shrink: complexity, function length and broad excepts per file.

``tests/budgets.json`` records what each file is allowed today; ``scripts/budgets.py``
measures the package. A file over its budget fails; an entry above the real count is
stale and fails (the file must state the truth); ``--update`` only ever lowers numbers.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUDGETS = REPO_ROOT / "tests" / "budgets.json"


@pytest.fixture(scope="module")
def budgets_module():
    script = REPO_ROOT / "scripts" / "budgets.py"
    spec = importlib.util.spec_from_file_location("budgets", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def measured(budgets_module):
    assert BUDGETS.exists(), "tests/budgets.json is missing; run scripts/budgets.py --init"
    budgets = json.loads(BUDGETS.read_text(encoding="utf-8"))
    return budgets, budgets_module.measure(budgets["thresholds"])


def test_no_file_exceeds_its_budget(budgets_module, measured) -> None:
    budgets, actual = measured
    regressions, _stale = budgets_module.compare(actual, budgets)
    assert regressions == [], (
        "over budget (narrow the handler / split the function, or lower another entry first):\n"
        + "\n".join(regressions)
    )


def test_budget_file_is_current(budgets_module, measured) -> None:
    budgets, actual = measured
    _regressions, stale = budgets_module.compare(actual, budgets)
    assert stale == [], "budgets.json is stale — run scripts/budgets.py --update:\n" + "\n".join(
        stale
    )


def test_budget_thresholds_are_the_plan_thresholds(measured) -> None:
    budgets, _actual = measured
    assert budgets["thresholds"] == {
        "complexity": 15,
        "function_length": 150,
        "max_args": 8,
        "max_branches": 15,
        "max_statements": 60,
        "max_returns": 8,
    }


def test_broad_except_total_is_under_the_phase_ceiling(measured) -> None:
    """The whole-package count came down in steps (207 → 137 → 94) and may only fall further."""
    _budgets, actual = measured
    total = sum(actual["broad_except"].values())
    assert total <= 210, f"{total} broad handlers in python/confiture"


def test_every_remaining_broad_handler_states_its_reason(budgets_module) -> None:
    """A handler that must stay broad says why, on its header or the line above it."""
    import ast

    package = REPO_ROOT / "python" / "confiture"
    missing: list[str] = []
    for path in sorted(package.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        broad_lines = set(budgets_module.broad_handlers(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.lineno not in broad_lines:
                continue
            first_body = node.body[0].lineno if node.body else node.lineno + 1
            span = lines[max(node.lineno - 2, 0) : first_body - 1]
            if not any("# Reason:" in line for line in span):
                missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert missing == [], "broad handlers without a `# Reason:`:\n" + "\n".join(missing)
