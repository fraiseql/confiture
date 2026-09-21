"""No function-local import under the migrator or the models defers an import cycle.

A ``# Reason: import cycle`` on an import inside a function is an escape hatch: the
cycle is still there, and the import runs late so that it does not fail at start-up.
Under ``core/_migrator/`` and ``models/`` every such hatch is a place where the
layering is a convention rather than a fact — ``session → apply_loop → migrator →
session`` — and ``test_import_graph_has_no_scc.py`` is the graph they keep from
failing. This test names each by ``file:line``; a start-up deferral (``reporting.py``'s
``core.preflight``) or a user-code guard says something else and is not counted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
SCOPE = (PACKAGE / "core" / "_migrator", PACKAGE / "models")


def _deferrals(source: str, label: str) -> list[str]:
    lines = source.splitlines()
    found: list[str] = []
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            around = " ".join(lines[max(node.lineno - 2, 0) : node.lineno]).lower()
            if "reason:" in around and "cycle" in around.split("reason:", 1)[1]:
                found.append(f"{label}:{node.lineno}")
    return found


def _all_deferrals() -> list[str]:
    return sorted(
        hit
        for root in SCOPE
        for path in root.rglob("*.py")
        for hit in _deferrals(
            path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix()
        )
    )


def test_the_reader_sees_a_deferral_and_nothing_else() -> None:
    """The guard, seen red: a cycle deferral counts, a start-up deferral does not."""
    source = (
        "def f():\n"
        "    # Reason: import cycle — a → b → a\n"
        "    from b import g\n"
        "\n"
        "def h():\n"
        "    # Reason: CLI start-up: importing c costs 29 ms\n"
        "    import c\n"
    )
    assert _deferrals(source, "m.py") == ["m.py:3"]


@pytest.mark.xfail(
    strict=True, reason="a map of the cycles still to remove; the mark goes with the last one"
)
def test_no_import_cycle_is_deferred_in_the_migrator_or_the_models() -> None:
    deferrals = _all_deferrals()
    assert deferrals == [], "function-local imports that defer a cycle:\n  " + "\n  ".join(
        deferrals
    )
