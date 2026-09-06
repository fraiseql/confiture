"""Every configuration field is read somewhere (Phase 06, ARC-03).

A field on a Pydantic config model that nothing reads is a promise the YAML
makes and the code never keeps — `auto_backup: true` did nothing, and the
documentation described behaviour that did not exist. For each model in
``config/environment.py`` every field must appear as an attribute access
(``.field``) under ``python/confiture`` outside that file; a field with no
consumer is wired or deleted, together with its documentation section.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from pydantic import BaseModel

import confiture
import confiture.config.environment as environment

PACKAGE = Path(confiture.__file__).resolve().parent


def _reads_outside_environment() -> set[str]:
    """Every attribute name accessed and every string literal under the package, except in environment.py.

    A field is read as ``env.field`` (an ``Attribute`` node) or, by the config
    loaders, as ``config["field"]`` / ``config.get("field")`` (a string constant
    equal to the field name). Dotted module paths in imports are neither.
    """
    names: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if path.name == "environment.py":
            # The models' own methods count (``self.profiles`` in ``get_profile``);
            # a field's declaration and docstring do not.
            nodes = [
                n
                for cls in tree.body
                if isinstance(cls, ast.ClassDef)
                for m in cls.body
                if isinstance(m, ast.FunctionDef)
                for n in ast.walk(m)
            ]
        else:
            nodes = list(ast.walk(tree))
        for node in nodes:
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and path.name != "environment.py"
            ):
                names.add(node.value)
    return names


def _config_models() -> list[type[BaseModel]]:
    return [
        cls
        for _, cls in inspect.getmembers(environment, inspect.isclass)
        if issubclass(cls, BaseModel) and cls.__module__ == environment.__name__
    ]


def find_unread_fields() -> list[str]:
    reads = _reads_outside_environment()
    return sorted(
        f"{model.__name__}.{field}"
        for model in _config_models()
        for field in model.model_fields
        if field not in reads
    )


def test_every_config_field_is_read() -> None:
    unread = find_unread_fields()
    assert unread == [], (
        "config fields nothing reads (wire them or delete them with their docs):\n  "
        + "\n  ".join(unread)
    )
