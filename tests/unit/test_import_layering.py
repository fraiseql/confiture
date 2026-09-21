"""The exception hierarchy and the data models import nothing from ``core/`` or ``testing/``.

``confiture.exceptions`` re-exported classes defined in ``core.preconditions``
and ``testing.sandbox``, so importing the leaf pulled in the trunk and the
sandbox. Layering is one direction: ``core`` and ``testing`` import
``exceptions`` and ``models``, never the reverse. Type-only imports under
``if TYPE_CHECKING:`` are annotations, not dependencies, and are allowed.

Two modules under ``models/`` are the migration *runtime* — the ``Migration``
base class user migrations subclass and its SQL-file twin — and execute SQL
through core helpers; they keep the public import path and are listed here
explicitly so any growth of that exception is visible.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
LEAVES = [PACKAGE / "exceptions.py", *sorted((PACKAGE / "models").glob("*.py"))]
RUNTIME_UNDER_MODELS = {"models/migration.py", "models/sql_file_migration.py"}
FORBIDDEN_PREFIXES = ("confiture.core", "confiture.testing")


def _runtime_imports(path: Path) -> list[str]:
    """Imports of core/testing that run — everything outside ``if TYPE_CHECKING:``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    type_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(n) for n in ast.walk(node))
    findings: list[str] = []
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(FORBIDDEN_PREFIXES):
            findings.append(
                f"{path.relative_to(PACKAGE).as_posix()}:{node.lineno} from {node.module}"
            )
        elif isinstance(node, ast.Import):
            findings.extend(
                f"{path.relative_to(PACKAGE).as_posix()}:{node.lineno} import {alias.name}"
                for alias in node.names
                if alias.name.startswith(FORBIDDEN_PREFIXES)
            )
    return findings


def test_exceptions_and_models_import_nothing_from_core_or_testing() -> None:
    findings = [
        f
        for path in LEAVES
        if path.relative_to(PACKAGE).as_posix() not in RUNTIME_UNDER_MODELS
        for f in _runtime_imports(path)
    ]
    assert findings == [], "leaf modules reach into core/testing:\n  " + "\n  ".join(findings)


def test_the_runtime_exception_list_is_exact() -> None:
    """Both listed modules really do import core; a clean one must leave the list."""
    still_needed = {rel for rel in RUNTIME_UNDER_MODELS if _runtime_imports(PACKAGE / rel)}
    assert still_needed == RUNTIME_UNDER_MODELS, RUNTIME_UNDER_MODELS - still_needed


def _all_imports(path: Path) -> list[tuple[int, str]]:
    """Every ``from X import`` in *path*, ``TYPE_CHECKING`` blocks included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]


def test_the_result_models_do_not_even_name_core() -> None:
    """``models/results.py`` holds the result types every command returns.

    A ``TYPE_CHECKING`` import is an annotation, but it is also an edge a reader
    follows, and ``results`` → ``core.migration_verifier`` was the back-edge that
    put ``models/`` inside a 40-module strongly connected component.
    """
    path = PACKAGE / "models" / "results.py"
    reaching = [
        f"{line} {module}"
        for line, module in _all_imports(path)
        if module.startswith("confiture.core")
    ]
    assert reaching == [], f"models/results.py names core: {reaching}"


def test_models_import_one_another_in_one_direction() -> None:
    """No cycle inside ``models/``, annotations included.

    ``models/schema.py`` imported ``models/results`` for ``BuildWarning`` while
    ``models/results.py`` annotated with ``models/schema``: a 2-cycle inside the
    leaf package.
    """
    modules = {path.stem: path for path in (PACKAGE / "models").glob("*.py")}
    edges = {
        name: {
            module.rsplit(".", 1)[-1]
            for _line, module in _all_imports(path)
            if module.startswith("confiture.models.") and module.rsplit(".", 1)[-1] in modules
        }
        for name, path in modules.items()
    }
    cycles = sorted(
        f"{a} <-> {b}" for a, targets in edges.items() for b in targets if a < b and a in edges[b]
    )
    assert cycles == [], f"models/ modules import each other: {cycles}"
