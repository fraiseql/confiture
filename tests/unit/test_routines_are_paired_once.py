"""Two sides' routines are paired by one engine, never by a module of its own.

The signature checks — ``migrate validate --check-signatures``, the git accompaniment
check for a changed parameter type, ``migrate fix-signatures`` — grouped routines by
``schema.name`` and matched them argument by argument themselves (``by_function``,
``matching``, ``paired``), beside the differ that pairs every routine a tree defines
(``ddl_objects.pair_definitions``, inside ``SchemaDiffer.compare_sides``). Now each
asks :func:`~confiture.core.function_signature_drift.unpaired_routines` or
:func:`~confiture.core.function_body_drift.changed_bodies`, both the engine's answer.
This fails on a pairing helper coming back, or on a module matching two routines'
signatures to each other.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent

#: The helpers each module had for pairing two sides' routines.
RETIRED = frozenset({"by_function", "matching", "paired"})

#: The modules that compare two sides' routines, each through the engine.
SIGNATURE_CHECKS = (
    "core/function_signature_drift.py",
    "core/function_signature_checker.py",
    "cli/commands/migrate/fix_signatures.py",
)


def _defined(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _matches_two_routines(tree: ast.AST) -> list[int]:
    """``signatures_match(a.signature_key, b.signature_key)``: two routines matched."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "signatures_match"
        and len(node.args) == 2
        and all(isinstance(a, ast.Attribute) and a.attr == "signature_key" for a in node.args)
    ]


def test_no_module_defines_a_pairing_of_its_own() -> None:
    found = {
        f"{path.relative_to(PACKAGE)}:{name}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for name in _defined(ast.parse(path.read_text(encoding="utf-8"))) & RETIRED
    }
    assert found == set()


@pytest.mark.parametrize("module", SIGNATURE_CHECKS)
def test_a_signature_check_matches_no_two_routines_itself(module: str) -> None:
    tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
    assert _matches_two_routines(tree) == []
