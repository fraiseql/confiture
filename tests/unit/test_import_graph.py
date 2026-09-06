"""The import graph respects the layering (Phase 08, Cycle 5).

Three rules, checked on the runtime import graph built from the AST (imports
under ``if TYPE_CHECKING:`` do not count):

- ``cli`` imports only public ``core`` names: no ``confiture.core._*`` module
  and no underscore-prefixed name from a core module. The public spelling is
  the contract; the CLI is a consumer like any other.
- ``core.linting`` does not import ``cli``.
- ``core`` does not import ``cli`` at all.

``models`` and ``exceptions`` importing no ``core``/``testing`` is held by
``tests/unit/test_import_layering.py`` (with its documented migration-runtime
allow-list) and is not repeated here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

_PACKAGE_ROOT = Path(confiture.__file__).resolve().parent

Edge = tuple[str, str, tuple[str, ...]]  # (importer, imported module, names)


def _module_name(path: Path) -> str:
    parts = path.relative_to(_PACKAGE_ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("confiture", *parts))


def _collect(node: ast.AST, importer: str, edges: list[Edge]) -> None:
    """Runtime imports under ``node``; an ``if TYPE_CHECKING:`` body does not count."""
    if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
        for child in node.orelse:
            _collect(child, importer, edges)
        return
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        edges.append((importer, node.module, tuple(a.name for a in node.names)))
    elif isinstance(node, ast.Import):
        edges.extend((importer, a.name, ()) for a in node.names)
    for child in ast.iter_child_nodes(node):
        _collect(child, importer, edges)


def _runtime_edges() -> list[Edge]:
    edges: list[Edge] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        _collect(ast.parse(path.read_text(encoding="utf-8")), _module_name(path), edges)
    return edges


def _private_core_module(module: str) -> bool:
    return module.startswith("confiture.core.") and any(
        part.startswith("_") for part in module.split(".")[2:]
    )


def test_cli_imports_only_public_core_names() -> None:
    offenders = [
        f"{importer} -> {module} {list(names)}"
        for importer, module, names in _runtime_edges()
        if importer.startswith("confiture.cli")
        and module.startswith("confiture.core")
        and (_private_core_module(module) or any(n.startswith("_") for n in names))
    ]
    assert offenders == [], "cli reaches into private core:\n  " + "\n  ".join(offenders)


def test_core_linting_does_not_import_cli() -> None:
    offenders = [
        f"{importer} -> {module}"
        for importer, module, _ in _runtime_edges()
        if importer.startswith("confiture.core.linting") and module.startswith("confiture.cli")
    ]
    assert offenders == []


def test_core_does_not_import_cli() -> None:
    offenders = [
        f"{importer} -> {module}"
        for importer, module, _ in _runtime_edges()
        if importer.startswith("confiture.core") and module.startswith("confiture.cli")
    ]
    assert offenders == [], "core depends on the CLI:\n  " + "\n  ".join(offenders)
