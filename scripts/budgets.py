#!/usr/bin/env python3
"""Per-file quality budgets that can only shrink.

Three measurements over ``python/confiture``:

- ``complexity``: functions whose McCabe complexity exceeds ``thresholds.complexity``
  (ruff's ``C901``, so the number is the one ruff will enforce when the rule is on);
- ``function_length``: functions longer than ``thresholds.function_length`` lines;
- ``broad_except``: ``except Exception``, ``except BaseException`` and bare ``except:``
  handlers (``tests/unit/test_budgets.py`` is the one place this is counted).

``tests/budgets.json`` records, per file, how many of each the file is allowed to have.
A file over its recorded number fails; a file not listed has a budget of zero; an entry
higher than the real count is stale and fails too, so the file always states the truth.
``--update`` rewrites the file with the current counts and refuses to raise any number.

Usage:
    uv run python scripts/budgets.py            # print the current counts
    uv run python scripts/budgets.py --check    # exit 1 on a regression or a stale entry
    uv run python scripts/budgets.py --update   # lower the recorded numbers to the real ones
    uv run python scripts/budgets.py --init     # write the first baseline (file must not exist)
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "python" / "confiture"
BUDGETS = REPO_ROOT / "tests" / "budgets.json"
THRESHOLDS = {"complexity": 15, "function_length": 150}
DIMENSIONS = ("complexity", "function_length", "broad_except")
Counts = dict[str, dict[str, int]]


def _ruff() -> str:
    candidate = Path(sys.executable).with_name("ruff")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("ruff")
    if found is None:
        raise SystemExit("budgets: ruff is not installed (uv sync --extra dev)")
    return found


def _rel(path: str | Path) -> str:
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


def measure_complexity(threshold: int) -> dict[str, int]:
    """Functions per file whose McCabe complexity exceeds ``threshold`` (ruff C901)."""
    proc = subprocess.run(
        [
            _ruff(),
            "check",
            str(PACKAGE),
            "--select",
            "C901",
            "--config",
            f"lint.mccabe.max-complexity={threshold}",
            "--output-format",
            "json",
            "--no-cache",
            "--isolated",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    counts: dict[str, int] = {}
    for finding in json.loads(proc.stdout or "[]"):
        rel = _rel(finding["filename"])
        counts[rel] = counts.get(rel, 0) + 1
    return counts


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def measure_function_length(threshold: int) -> dict[str, int]:
    """Functions per file longer than ``threshold`` lines."""
    counts: dict[str, int] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        over = sum(
            1
            for fn in _functions(tree)
            if fn.end_lineno is not None and fn.end_lineno - fn.lineno + 1 > threshold
        )
        if over:
            counts[_rel(path)] = over
    return counts


def broad_handlers(path: Path) -> list[int]:
    """Line numbers of ``except Exception``, ``except BaseException`` and bare ``except:``."""
    found: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            found.append(node.lineno)
            continue
        names = list(node.type.elts) if isinstance(node.type, ast.Tuple) else [node.type]
        if any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names):
            found.append(node.lineno)
    return found


def measure_broad_except() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        lines = broad_handlers(path)
        if lines:
            counts[_rel(path)] = len(lines)
    return counts


def measure(thresholds: dict[str, int] | None = None) -> Counts:
    t = {**THRESHOLDS, **(thresholds or {})}
    return {
        "complexity": measure_complexity(t["complexity"]),
        "function_length": measure_function_length(t["function_length"]),
        "broad_except": measure_broad_except(),
    }


def load_budgets() -> dict:
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def compare(actual: Counts, budgets: dict) -> tuple[list[str], list[str]]:
    """(regressions, stale entries) between the measured counts and the recorded budgets."""
    regressions: list[str] = []
    stale: list[str] = []
    for dimension in DIMENSIONS:
        recorded: dict[str, int] = budgets.get(dimension, {})
        measured = actual[dimension]
        for rel, count in sorted(measured.items()):
            allowed = recorded.get(rel, 0)
            if count > allowed:
                regressions.append(f"{dimension}: {rel} has {count}, budget {allowed}")
        for rel, allowed in sorted(recorded.items()):
            count = measured.get(rel, 0)
            if count < allowed:
                stale.append(f"{dimension}: {rel} records {allowed}, real count {count}")
    return regressions, stale


def _render(budgets: dict) -> str:
    ordered = {"thresholds": budgets["thresholds"]}
    for dimension in DIMENSIONS:
        ordered[dimension] = dict(sorted(budgets.get(dimension, {}).items()))
    return json.dumps(ordered, indent=2) + "\n"


def main(argv: list[str]) -> int:
    if "--init" in argv:
        if BUDGETS.exists():
            print(f"{BUDGETS} exists; use --update", file=sys.stderr)
            return 1
        actual = measure()
        BUDGETS.write_text(_render({"thresholds": THRESHOLDS, **actual}), encoding="utf-8")
        print(f"wrote {BUDGETS.relative_to(REPO_ROOT)}")
        return 0
    if not BUDGETS.exists():
        print(
            f"{BUDGETS.relative_to(REPO_ROOT)} missing; run scripts/budgets.py --init",
            file=sys.stderr,
        )
        return 1
    budgets = load_budgets()
    actual = measure(budgets["thresholds"])
    regressions, stale = compare(actual, budgets)
    if "--update" in argv:
        if regressions:
            print(
                "budgets only shrink; fix these first:\n  " + "\n  ".join(regressions),
                file=sys.stderr,
            )
            return 1
        BUDGETS.write_text(
            _render({"thresholds": budgets["thresholds"], **actual}), encoding="utf-8"
        )
        print(f"lowered {len(stale)} entries" if stale else "budgets already current")
        return 0
    if "--check" in argv:
        for line in regressions:
            print("REGRESSION " + line)
        for line in stale:
            print("STALE " + line)
        if regressions or stale:
            print("run scripts/budgets.py --update after fixing regressions", file=sys.stderr)
            return 1
        print("budgets: within budget and current")
        return 0
    for dimension in DIMENSIONS:
        total = sum(actual[dimension].values())
        print(f"{dimension}: {total} over threshold in {len(actual[dimension])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
