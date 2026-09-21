"""Every module is reachable, and the two senses of "reachable" give different answers.

The graph is every import that runs — module level, inside a function, relative, a
module named as a string in a lazy table — plus the parent packages Python imports
first. Two root sets walk it:

- **exported**: ``confiture.cli.main``, ``confiture``'s ``_LAZY_IMPORTS`` table, and
  the ``pytest11`` entry point — what an installed confiture offers. A module no root
  reaches is dead code;
- **called**: ``confiture.cli.main`` and what the suites that run against a database
  import, walking *through* ``confiture/__init__.py``'s table not at all — a re-export
  is not a call. A module only this set misses is offered and never used.

Each ``*_EXEMPT`` table names a module the walk cannot see used, with the reason; an
entry that stops matching fails. The tests are a map while they are ``xfail``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[1]

EXPORTED_ROOTS = frozenset({"confiture.cli.main", "confiture", "confiture.testing.pytest_plugin"})
#: Reached from outside the package, where an import walk cannot follow.
CALLED_EXEMPT: dict[str, str] = {
    "confiture.core.schema_exporter": "scripts/gen_schemas.py publishes the JSON schemas from it in CI",
    "confiture.schemas": "the published JSON schemas' package, read by schema_exporter",
    "confiture.testing.pytest_plugin": "loaded by pytest through the pytest11 entry point",
}
EXPORTED_EXEMPT: dict[str, str] = {}


def _module(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


MODULES = {_module(path): path for path in PACKAGE.rglob("*.py")}


def _resolve(name: str) -> str | None:
    while name and name not in MODULES:
        name = name.rpartition(".")[0]
    return name or None


def _base(node: ast.ImportFrom, here: str | None, is_package: bool) -> str:
    if not node.level or here is None:
        return node.module or ""
    package = here if is_package else here.rpartition(".")[0]
    for _ in range(node.level - 1):
        package = package.rpartition(".")[0]
    return f"{package}.{node.module}" if node.module else package


def _targets(node: ast.AST, here: str | None, is_package: bool) -> set[str]:
    if isinstance(node, ast.ImportFrom) and (base := _base(node, here, is_package)):
        return {
            target
            for alias in node.names
            if (target := _resolve(f"{base}.{alias.name}") or _resolve(base))
        }
    if isinstance(node, ast.Import):
        return {target for alias in node.names if (target := _resolve(alias.name))}
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("confiture.")
        and _resolve(node.value) == node.value
    ):
        return {node.value}
    return set()


def imports(source: str, here: str | None = None, *, is_package: bool = False) -> set[str]:
    """The confiture modules *source* imports, with the packages Python imports first."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        found |= _targets(node, here, is_package)
    for target in list(found):
        parts = target.split(".")
        found |= {
            ".".join(parts[:i]) for i in range(2, len(parts)) if ".".join(parts[:i]) in MODULES
        }
    return found


GRAPH = {
    name: imports(path.read_text(encoding="utf-8"), name, is_package=path.name == "__init__.py")
    - {name}
    for name, path in MODULES.items()
}


def _reach(roots: set[str], *, not_through: frozenset[str] = frozenset()) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        if module not in not_through:
            stack.extend(GRAPH.get(module, ()))
    return seen


def _database_suites() -> set[str]:
    return {
        target
        for suite in ("integration", "e2e")
        for path in (REPO_ROOT / "tests" / suite).rglob("*.py")
        for target in imports(path.read_text(encoding="utf-8"))
    }


def test_the_walker_follows_a_relative_import() -> None:
    """The guard, seen red: ``from .registry import …`` inside a package is an edge."""
    found = imports("from .registry import HookRegistry\n", "confiture.core.hooks", is_package=True)
    assert "confiture.core.hooks.registry" in found


def test_exemptions_state_a_reason_and_name_a_module() -> None:
    for table in (CALLED_EXEMPT, EXPORTED_EXEMPT):
        assert all(reason.strip() for reason in table.values())
        assert set(table) <= set(MODULES), set(table) - set(MODULES)


@pytest.mark.xfail(strict=True, reason="a map of the modules nothing exports yet")
def test_nothing_is_dead() -> None:
    orphans = sorted(set(MODULES) - _reach(set(EXPORTED_ROOTS)) - set(EXPORTED_EXEMPT))
    assert orphans == [], "reached by no entry point:\n  " + "\n  ".join(orphans)


@pytest.mark.xfail(strict=True, reason="a map of the modules offered and never used yet")
def test_nothing_is_offered_and_never_used() -> None:
    called = _reach(
        {"confiture.cli.main"} | _database_suites(), not_through=frozenset({"confiture"})
    )
    unused = sorted(set(MODULES) - called - {"confiture"} - set(CALLED_EXEMPT))
    assert unused == [], "offered and never called:\n  " + "\n  ".join(unused)
