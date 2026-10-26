"""Whether a Python migration's ``down()`` does anything, read from its source, never imported.

``migrate down`` runs whatever ``down()`` holds. One that is only a docstring, ``pass``,
``...``, a bare ``return`` or ``raise NotImplementedError`` undoes nothing, and a class
that does not define one inherits :class:`~confiture.models.migration.Migration`'s
abstract ``down()``. Both are :attr:`DownBody.EMPTY`. A ``down()`` with any other
statement is :attr:`DownBody.PRESENT` — what it does is not judged.

Only a class written directly on ``Migration`` is read, and only when it is the one
migration class in the file: a ``down()`` another base may supply (``SQLMigration``, a
project's own base, a mixin), a decorated or assigned ``down``, and a file :mod:`ast`
cannot parse are :attr:`DownBody.UNKNOWN`, never assumed either way.

The source is parsed with :mod:`ast` and nothing else: no import, no execution.
"""

import ast
from enum import Enum
from pathlib import Path

_BASE = "Migration"


class DownBody(Enum):
    """What a Python migration's ``down()`` is, as far as its source says."""

    EMPTY = "empty"
    PRESENT = "present"
    UNKNOWN = "unknown"


def has_usable_down(migration: Path) -> bool:
    """Whether ``migrate down`` has a down to run for *migration*.

    An ``.up.sql`` has one when its ``.down.sql`` twin exists; a ``.py`` has one unless
    its ``down()`` is :attr:`DownBody.EMPTY` — an :attr:`DownBody.UNKNOWN` one is never
    refused.
    """
    if migration.name.endswith(".up.sql"):
        return migration.with_name(migration.name.removesuffix(".up.sql") + ".down.sql").exists()
    return read_python_down(migration) is not DownBody.EMPTY


def read_python_down(path: Path) -> DownBody:
    """:func:`read_down` over the migration file at *path*; text that is not UTF-8 is unknown."""
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return DownBody.UNKNOWN
    return read_down(source)


def read_down(source: str) -> DownBody:
    """What the one migration class in *source* holds as its ``down()``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return DownBody.UNKNOWN
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    local = {node.name for node in classes}
    direct = [node for node in classes if any(_base_name(b) == _BASE for b in node.bases)]
    derived = [node for node in classes if any(_base_name(b) in local for b in node.bases)]
    if len(direct) != 1 or derived:
        return DownBody.UNKNOWN
    return _down_of(direct[0])


def _down_of(cls: ast.ClassDef) -> DownBody:
    bindings = [stmt for stmt in cls.body if "down" in _bound_names(stmt)]
    if not bindings:
        # The abstract ``down()`` — unless another base supplies one first.
        return DownBody.EMPTY if len(cls.bases) == 1 else DownBody.UNKNOWN
    last = bindings[-1]
    if not isinstance(last, ast.FunctionDef) or last.decorator_list:
        return DownBody.UNKNOWN
    return (
        DownBody.EMPTY
        if all(map(_does_nothing, _without_docstring(last.body)))
        else DownBody.PRESENT
    )


def _bound_names(stmt: ast.stmt) -> set[str]:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}
    return {
        node.id
        for node in ast.walk(stmt)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    }


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    match body[0]:
        case ast.Expr(value=ast.Constant(value=str())):
            return body[1:]
    return body


def _does_nothing(stmt: ast.stmt) -> bool:
    match stmt:
        case ast.Pass() | ast.Return(value=None):
            return True
        case ast.Expr(value=ast.Constant(value=value)):
            return value is Ellipsis
        case ast.Raise(exc=ast.Name(id="NotImplementedError"), cause=None):
            return True
        case ast.Raise(exc=ast.Call(func=ast.Name(id="NotImplementedError")), cause=None):
            return True
    return False


def _base_name(base: ast.expr) -> str | None:
    match base:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
    return None
