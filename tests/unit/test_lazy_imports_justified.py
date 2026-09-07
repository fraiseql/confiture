"""A function-level import says why it is there.

An import inside a function is legitimate for three reasons — an optional
dependency that may be absent, a genuine import cycle, or a deliberate deferral
of a heavy module off the CLI's startup path (measured, the cost named) — and a
fourth that is not: it was easier than scrolling up. Every such import carries
a ``# Reason:`` comment on its line or the line above; there is no budget.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE_ROOT = Path(confiture.__file__).resolve().parent


def _unjustified(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    seen: set[int] = set()
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in seen:
                continue
            seen.add(id(node))
            own = lines[node.lineno - 1]
            above = lines[node.lineno - 2] if node.lineno >= 2 else ""
            if "# Reason:" in own or above.strip().startswith("# Reason:"):
                continue
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            found.append(f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}: {module}")
    return found


def _by_file() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        hits = _unjustified(path)
        if hits:
            result[path.relative_to(PACKAGE_ROOT).as_posix()] = hits
    return result


def test_every_function_level_import_states_its_reason() -> None:
    hits = _by_file()
    detail = "\n".join(
        f"  {rel}: {len(found)}\n    " + "\n    ".join(found[:5])
        for rel, found in sorted(hits.items())
    )
    assert hits == {}, f"function-level imports without a '# Reason:':\n{detail}"


@pytest.mark.parametrize("marker", ["# Reason:"])
def test_reasons_name_a_cause(marker: str) -> None:
    """A reason says which optional dependency, which cycle, or 'startup' — not just 'lazy'."""
    vague: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if marker in line:
                reason = line.split(marker, 1)[1].strip().lower()
                if len(reason) < 8 or reason in {"lazy", "lazy import", "perf", "performance"}:
                    vague.append(
                        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{lineno}: {reason!r}"
                    )
    assert vague == [], "reasons that explain nothing:\n" + "\n".join(vague)
