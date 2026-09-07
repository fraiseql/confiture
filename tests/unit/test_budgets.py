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
    assert budgets["thresholds"] == {"complexity": 15, "function_length": 150}


def test_broad_except_total_is_under_the_phase_ceiling(measured) -> None:
    """Phase 11 lowers the whole-package count in steps (200 → 160 → 120)."""
    _budgets, actual = measured
    total = sum(actual["broad_except"].values())
    assert total <= 210, f"{total} broad handlers in python/confiture"
