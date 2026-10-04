"""A body check is the one comparison, restricted to one slot.

``migrate validate --check-body-views``, ``--check-body``, ``--check-body-replay`` and
the git accompaniment check (``--require-migration-bodies``) each paired two sides and
compared a definition, a hash or a body themselves, beside
the differ that pairs and compares every object a tree defines. Now each builds two
sides whose statements carry only the slot it asks about — a view's deparsed query, a
routine's normalised body — and asks ``SchemaDiffer.compare_sides``: the pairing of
overloads and the verdict are the engine's, and the module renders the answer. This
fails on one of them comparing two values itself, or not asking the engine.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

CORE = Path(confiture.__file__).resolve().parent / "core"

#: The body checks, each rendering the engine's answer for one slot.
RENDERERS = ("view_body_drift.py", "function_body_drift.py", "function_body_checker.py")


def _comparisons(tree: ast.AST) -> list[int]:
    """Lines comparing two values with ``==``/``!=``, neither a constant."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        and not any(isinstance(o, ast.Constant) for o in (node.left, *node.comparators))
    ]


@pytest.mark.parametrize("module", RENDERERS)
def test_a_body_check_compares_nothing_itself(module: str) -> None:
    tree = ast.parse((CORE / module).read_text(encoding="utf-8"))
    assert _comparisons(tree) == []


@pytest.mark.parametrize("module", RENDERERS)
def test_a_body_check_asks_the_engine(module: str) -> None:
    """Directly, or through ``function_body_drift.changed_bodies``, which does."""
    text = (CORE / module).read_text(encoding="utf-8")
    assert "compare_sides" in text or "changed_bodies(" in text  # either reaches the engine
