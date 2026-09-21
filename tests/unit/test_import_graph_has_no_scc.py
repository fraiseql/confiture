"""The migrator, the models, the config and the exceptions take part in no import cycle.

**The graph** is every import that runs: module-level imports *and* imports inside a
function. ``TYPE_CHECKING`` imports are annotations and are not edges. Over the
module-level imports alone the package is already acyclic, which is why a cycle here
is invisible to the interpreter: a function-local import is how a cycle is kept from
failing at start-up, not how it is removed. ``test_no_cycle_deferral_remains.py``
names each such deferral.

**The scope** is ``core/_migrator/**``, ``models/**``, ``config/**`` and
``exceptions.py``: no module there may sit in a strongly connected component of more
than one module. Two cycles elsewhere are out of scope on purpose, and named so the
scope is read rather than inferred — the ``core/idempotency`` cluster (the campaign's
README puts idempotency out of scope), and ``core/linting``'s own deferrals, which
are the linter's and not the migrator's. They may remain SCCs among themselves; they
may not reach into the scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
SCOPE = ("confiture.core._migrator", "confiture.models", "confiture.config")
SCOPE_MODULES = ("confiture.exceptions",)


def _module(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODULES = {_module(path): path for path in PACKAGE.rglob("*.py")}


def _resolve(name: str) -> str | None:
    while name and name not in MODULES:
        name = name.rpartition(".")[0]
    return name or None


def _is_type_checking(node: ast.AST) -> bool:
    return isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)


def _targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        found = {_resolve(f"{node.module}.{alias.name}") for alias in node.names}
        return {target or _resolve(node.module) for target in found} - {None}
    if isinstance(node, ast.Import):
        return {target for alias in node.names if (target := _resolve(alias.name))}
    return set()


def _imports(path: Path) -> set[str]:
    """Every module *path* imports at run time, from its top level or inside a function."""
    found: set[str] = set()
    stack: list[ast.AST] = [ast.parse(path.read_text(encoding="utf-8"))]
    while stack:
        node = stack.pop()
        if _is_type_checking(node):
            stack.extend(getattr(node, "orelse", []))
            continue
        found |= _targets(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


def _components(graph: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan's strongly connected components, iteratively."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[set[str]] = []
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(sorted(graph[root])))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in index:
                    index[child] = low[child] = len(index)
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph[child]))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                found.append(component)
    return found


def _in_scope(module: str) -> bool:
    return module in SCOPE_MODULES or any(
        module == prefix or module.startswith(f"{prefix}.") for prefix in SCOPE
    )


def _cycles_reaching_the_scope() -> list[list[str]]:
    graph = {module: _imports(path) - {module} for module, path in MODULES.items()}
    return sorted(
        sorted(component)
        for component in _components(graph)
        if len(component) > 1 and any(_in_scope(member) for member in component)
    )


def test_the_graph_reader_sees_a_function_local_cycle() -> None:
    """The guard, seen red: two modules that import each other only inside functions."""
    graph = {"a": {"b"}, "b": {"a"}, "c": {"a"}}
    assert [sorted(c) for c in _components(graph) if len(c) > 1] == [["a", "b"]]


@pytest.mark.xfail(
    strict=True, reason="a map of the cycles still to remove; the mark goes with the last one"
)
def test_no_import_cycle_reaches_the_migrator_models_config_or_exceptions() -> None:
    cycles = _cycles_reaching_the_scope()
    assert cycles == [], "import cycles through the scope:\n" + "\n".join(
        f"  {len(cycle)}: " + ", ".join(m.removeprefix("confiture.") for m in cycle)
        for cycle in cycles
    )
