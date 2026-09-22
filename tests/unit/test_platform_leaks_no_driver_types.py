"""Nothing ``confiture.platform`` hands out names a pglast or psycopg type.

The seam is what a seed generator — and later a crate — is written against, and
both sides of it change on their own clocks: pglast renumbers its enums between
majors (#192), psycopg is one driver among several a caller may hold. A signature
that says ``pglast.ast.CreateStmt`` or ``psycopg.Connection`` makes that clock the
caller's. So every annotation the seam exposes — each function's parameters and
return, each dataclass's fields, followed through every dataclass they reach — is
resolved and walked, and a value any of them returns is walked too.

Annotations are resolved with the names a module imports under ``TYPE_CHECKING``,
read from its own source: an annotation-only import is still a type the caller
sees.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sys
import types
import typing
from collections.abc import Mapping
from typing import Any

import pglast.ast
import psycopg
import pytest

from confiture import platform

DRIVERS = ("pglast", "psycopg")


def _namespace(obj: Any) -> dict[str, Any]:
    """*obj*'s module globals plus what the module imports under ``TYPE_CHECKING``."""
    module = sys.modules[obj.__module__]
    namespace = dict(vars(module))
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            imports = [n for n in node.body if isinstance(n, ast.Import | ast.ImportFrom)]
            code = compile(ast.Module(body=imports, type_ignores=[]), str(module.__file__), "exec")
            exec(code, namespace)
    return namespace


def _hints(obj: Any) -> dict[str, Any]:
    return typing.get_type_hints(obj, globalns=_namespace(obj))


def _is_driver(tp: Any) -> bool:
    return isinstance(tp, type) and tp.__module__.split(".")[0] in DRIVERS


def driver_types(hint: Any, seen: set[Any] | None = None) -> set[str]:
    """Every pglast/psycopg class *hint* names, through unions, generics and dataclasses."""
    seen = set() if seen is None else seen
    if id(hint) in seen:
        return set()
    seen.add(id(hint))
    if typing.get_origin(hint) is typing.Literal:
        return set()
    found: set[str] = set()
    if _is_driver(hint):
        found.add(f"{hint.__module__}.{hint.__qualname__}")
    for arg in typing.get_args(hint):
        found |= driver_types(arg, seen)
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        for field_hint in _hints(hint).values():
            found |= driver_types(field_hint, seen)
    if isinstance(hint, type) and getattr(hint, "_is_protocol", False):
        for member in vars(hint).values():
            if inspect.isfunction(member):
                for member_hint in _hints(member).values():
                    found |= driver_types(member_hint, seen)
    return found


def driver_objects(value: Any, seen: set[int] | None = None) -> set[str]:
    """Every pglast/psycopg object reachable from *value* through fields and collections."""
    seen = set() if seen is None else seen
    if id(value) in seen or isinstance(value, str | bytes | int | float | bool | types.NoneType):
        return set()
    seen.add(id(value))
    found = (
        {f"{type(value).__module__}.{type(value).__qualname__}"}
        if _is_driver(type(value))
        else set()
    )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        children: list[Any] = [getattr(value, f.name) for f in dataclasses.fields(value)]
    elif isinstance(value, Mapping):
        children = [*value.keys(), *value.values()]
    elif isinstance(value, list | tuple | set | frozenset):
        children = list(value)
    else:
        children = []
    for child in children:
        found |= driver_objects(child, seen)
    return found


@dataclasses.dataclass
class _Leaky:
    """What the guard must refuse: a parse node and a driver connection in a field."""

    node: pglast.ast.CreateStmt | None
    conns: list[psycopg.Connection]


def _exported() -> list[str]:
    return sorted(platform.__all__)


@pytest.mark.parametrize("name", _exported())
def test_no_exported_name_mentions_a_driver_type(name: str) -> None:
    obj = getattr(platform, name)
    if inspect.isfunction(obj):
        found = set().union(*(driver_types(h) for h in _hints(obj).values()))
    elif isinstance(obj, type):
        found = driver_types(obj)
        for member in vars(obj).values():
            function = getattr(member, "__func__", member)
            if inspect.isfunction(function) and not function.__name__.startswith("_"):
                found |= set().union(*(driver_types(h) for h in _hints(function).values()))
    else:
        found = set().union(*(driver_types(arg) for arg in typing.get_args(obj)))
    assert found == set(), f"{name} exposes {sorted(found)}"


def test_the_guard_sees_a_driver_type() -> None:
    """A guard never seen red does not run: plant a pglast and a psycopg type."""
    assert driver_types(_Leaky) == {"pglast.ast.CreateStmt", "psycopg.Connection"}
    assert driver_objects({"k": (pglast.ast.CreateStmt(),)}) == {"pglast.ast.CreateStmt"}


def test_what_parse_schema_and_diff_return_holds_no_driver_object() -> None:
    ddl = (
        "CREATE TYPE s AS ENUM ('a');\n"
        "CREATE TABLE p (id INT PRIMARY KEY);\n"
        "CREATE TABLE c (id INT REFERENCES p, v s CHECK (v <> 'a'));\n"
        "CREATE VIEW w AS SELECT id FROM c;\n"
        "CREATE FUNCTION f(x INT) RETURNS INT LANGUAGE sql AS 'SELECT x';\n"
    )
    assert driver_objects(platform.parse_schema(ddl)) == set()
    assert driver_objects(platform.diff("", ddl)) == set()
