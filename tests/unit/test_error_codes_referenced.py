"""Every registered error code is one the package can actually emit (Phase 06, D9).

The registry and the published codebook promised 80 symbolic codes, but a
consumer matching on `SYNC_300` or `HOOK_1100` would wait forever: nothing in
`python/confiture` ever names them. A code is *referenced* when its string
appears somewhere in the package outside the registry module itself — as an
exception class default, a `fail(...)`/`ConfiturError(..., error_code=...)`
argument, a translation table, or a finding constructor. Docstrings and
comments do not count: a code that only appears in prose is still dead.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

import confiture
from confiture.error_codes import ERROR_CODE_REGISTRY

_PACKAGE_ROOT = Path(confiture.__file__).resolve().parent
_REGISTRY_MODULE = _PACKAGE_ROOT / "error_codes.py"


def _is_docstring(node: ast.Constant, parents: dict[int, ast.AST]) -> bool:
    expr = parents.get(id(node))
    if not isinstance(expr, ast.Expr):
        return False
    owner = parents.get(id(expr))
    body = getattr(owner, "body", None)
    return bool(body) and body[0] is expr


def _code_literals(source: str) -> set[str]:
    """Every string constant in ``source`` that is not a docstring."""
    tree = ast.parse(source)
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and not _is_docstring(node, parents)
    }


@lru_cache(maxsize=1)
def _referenced_strings() -> frozenset[str]:
    found: set[str] = set()
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if path == _REGISTRY_MODULE:
            continue
        found |= _code_literals(path.read_text(encoding="utf-8"))
    return frozenset(found)


def _registered_codes() -> list[str]:
    return sorted(d.code for d in ERROR_CODE_REGISTRY.all_codes())


@pytest.mark.parametrize("code", _registered_codes())
def test_registered_code_is_referenced_by_the_package(code: str) -> None:
    assert code in _referenced_strings(), (
        f"{code} is registered but nothing under python/confiture ever emits it — "
        "prune it from ERROR_CODE_REGISTRY and CANONICAL_EXIT_CODES, or wire the "
        "raise site that should carry it"
    )


def test_no_registered_code_is_unreferenced() -> None:
    """The aggregate view: one failure naming every dead code at once."""
    dead = [code for code in _registered_codes() if code not in _referenced_strings()]
    assert dead == [], f"{len(dead)} registered codes are never emitted: {dead}"
