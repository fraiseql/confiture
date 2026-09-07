"""Validation and introspection each live in one package.

``core/validators/`` sat beside ``core/validation/``, ``core/config_validator.py``
beside both, ``core/introspector.py`` beside ``core/introspection/``, and
``introspection/differ_sql.py`` was a differ helper filed under introspection.
Each module has one home now; the old paths are thin shims for one release
(removed at 1.0.0) and nothing inside the package uses them.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

import confiture

_PACKAGE_ROOT = Path(confiture.__file__).resolve().parent
_OLD_TO_NEW = {
    "confiture.core.validators": "confiture.core.validation.comment_validator",
    "confiture.core.validators.comment_validator": "confiture.core.validation.comment_validator",
    "confiture.core.config_validator": "confiture.core.validation.config_validator",
    "confiture.core.introspector": "confiture.core.introspection.tables",
    "confiture.core.introspection.differ_sql": "confiture.core.differ_sql",
}
_SHIM_FILES = {
    "core/validators/__init__.py",
    "core/validators/comment_validator.py",
    "core/config_validator.py",
    "core/introspector.py",
    "core/introspection/differ_sql.py",
}


def test_each_module_has_its_one_home() -> None:
    from confiture.core.differ_sql import __name__ as differ_sql
    from confiture.core.introspection.tables import SchemaIntrospector
    from confiture.core.validation.comment_validator import __name__ as comment_validator
    from confiture.core.validation.config_validator import __name__ as config_validator

    assert SchemaIntrospector and differ_sql and comment_validator and config_validator


def _public(module: object) -> list[str]:
    declared = list(getattr(module, "__all__", None) or [])
    if declared:
        return declared
    return [
        n for n in dir(module) if not n.startswith("_") and not inspect.ismodule(getattr(module, n))
    ]


@pytest.mark.parametrize("old", sorted(_OLD_TO_NEW))
def test_the_old_path_is_gone(old: str) -> None:
    """The one-release shims left with 1.0.0; the old import paths no longer resolve."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(old)


def test_no_shim_file_remains() -> None:
    present = [rel for rel in sorted(_SHIM_FILES) if (_PACKAGE_ROOT / rel).exists()]
    assert present == [], f"shim files still present: {present}"


def test_nothing_in_the_package_imports_the_old_paths() -> None:
    offenders: list[str] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            offenders.extend(
                f"{rel}:{node.lineno}: {module}"
                for module in modules
                if any(module == old or module.startswith(old + ".") for old in _OLD_TO_NEW)
            )
    assert offenders == [], "old paths still imported inside the package:\n" + "\n".join(offenders)


def test_the_lazy_public_api_points_at_the_new_homes() -> None:
    from confiture import _LAZY_IMPORTS

    homes = {module for module, _ in _LAZY_IMPORTS.values()}
    assert not homes & set(_OLD_TO_NEW), sorted(homes & set(_OLD_TO_NEW))
