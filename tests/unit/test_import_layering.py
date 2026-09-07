"""The exception hierarchy and the data models import nothing from ``core/`` or ``testing/`` (Phase 06).

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
