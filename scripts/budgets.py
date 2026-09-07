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
THRESHOLDS = {
    "complexity": 15,
    "function_length": 150,
    "max_args": 8,
    "max_branches": 15,
    "max_statements": 60,
    "max_returns": 8,
}
# Dimensions ruff can enforce, and the rule each one is measured with. The files that
# violate one today are listed in pyproject's generated per-file-ignores block so ruff
# passes on them and fails on every new file; the block is rendered from budgets.json.
RUFF_DIMENSIONS = {
    "complexity": "C901",
    "too_many_args": "PLR0913",
    "too_many_branches": "PLR0912",
    "too_many_statements": "PLR0915",
    "too_many_returns": "PLR0911",
    "magic_values": "PLR2004",
}
DIMENSIONS = (*RUFF_DIMENSIONS, "function_length", "broad_except")
PYPROJECT = REPO_ROOT / "pyproject.toml"
BLOCK_BEGIN = "# BEGIN GENERATED: budget-ignores (scripts/budgets.py --update; do not edit)"
BLOCK_END = "# END GENERATED: budget-ignores"
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


def _ruff_config(thresholds: dict[str, int]) -> list[str]:
    return [
        "--config",
        f"lint.mccabe.max-complexity={thresholds['complexity']}",
        "--config",
        f"lint.pylint.max-args={thresholds['max_args']}",
        "--config",
        f"lint.pylint.max-branches={thresholds['max_branches']}",
        "--config",
        f"lint.pylint.max-statements={thresholds['max_statements']}",
        "--config",
        f"lint.pylint.max-returns={thresholds['max_returns']}",
    ]


def measure_ruff(thresholds: dict[str, int]) -> dict[str, dict[str, int]]:
    """Per dimension, findings per file for its ruff rule at the given thresholds.

    Runs ruff ``--isolated`` (no pyproject, so the generated ignores do not hide the
    very files they list) over the package.
    """
    proc = subprocess.run(
        [
            _ruff(),
            "check",
            str(PACKAGE),
            "--isolated",
            "--select",
            ",".join(RUFF_DIMENSIONS.values()),
            *_ruff_config(thresholds),
            "--output-format",
            "json",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    by_rule = {rule: name for name, rule in RUFF_DIMENSIONS.items()}
    counts: dict[str, dict[str, int]] = {name: {} for name in RUFF_DIMENSIONS}
    for finding in json.loads(proc.stdout or "[]"):
        name = by_rule.get(finding["code"])
        if name is None:
            continue
        rel = _rel(finding["filename"])
        counts[name][rel] = counts[name].get(rel, 0) + 1
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
        **measure_ruff(t),
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


def render_ignores(budgets: dict) -> str:
    """The per-file-ignores block: every package file over budget, with the rules it may break."""
    rules_by_file: dict[str, set[str]] = {}
    for name, rule in RUFF_DIMENSIONS.items():
        for rel, count in budgets.get(name, {}).items():
            if count:
                rules_by_file.setdefault(rel, set()).add(rule)
    lines = [BLOCK_BEGIN]
    for rel in sorted(rules_by_file):
        rules = ", ".join(f'"{r}"' for r in sorted(rules_by_file[rel]))
        lines.append(f'"{rel}" = [{rules}]')
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def _split_pyproject(text: str) -> tuple[str, str, str]:
    start = text.index(BLOCK_BEGIN)
    end = text.index(BLOCK_END) + len(BLOCK_END) + 1
    return text[:start], text[start:end], text[end:]


def pyproject_block_is_current(budgets: dict) -> bool:
    _head, current, _tail = _split_pyproject(PYPROJECT.read_text(encoding="utf-8"))
    return current == render_ignores(budgets)


def write_pyproject_block(budgets: dict) -> None:
    head, _current, tail = _split_pyproject(PYPROJECT.read_text(encoding="utf-8"))
    PYPROJECT.write_text(head + render_ignores(budgets) + tail, encoding="utf-8")


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
        budgets = {"thresholds": THRESHOLDS, **actual}
        BUDGETS.write_text(_render(budgets), encoding="utf-8")
        write_pyproject_block(budgets)
        print(f"wrote {BUDGETS.relative_to(REPO_ROOT)} and the pyproject ignores block")
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
        updated = {"thresholds": budgets["thresholds"], **actual}
        BUDGETS.write_text(_render(updated), encoding="utf-8")
        write_pyproject_block(updated)
        print(f"lowered {len(stale)} entries" if stale else "budgets already current")
        return 0
    if "--check" in argv:
        for line in regressions:
            print("REGRESSION " + line)
        for line in stale:
            print("STALE " + line)
        block_current = pyproject_block_is_current(budgets)
        if not block_current:
            print("STALE pyproject per-file-ignores block differs from budgets.json")
        if regressions or stale or not block_current:
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
