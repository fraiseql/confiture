"""Generate typed Python wrapper stubs from PostgreSQL functions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pglast
import pglast.parser
import psycopg
from pglast.stream import RawStream

from confiture.core import plpgsql_parse
from confiture.core.ddl_walk import walk_nodes
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.type_mapping import TypeMapper
from confiture.core.plpgsql_fragments import fragments
from confiture.models.function_info import FunctionInfo, ParamMode
from confiture.models.introspection import JSONBKey
from confiture.models.stub_models import StubFile, StubFunction

#: The call whose constant keys become a result class's fields.
_BUILDER = "jsonb_build_object"


class StubGenerator:
    """Generates typed Python stubs from a PostgreSQL schema's functions."""

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        *,
        include_triggers: bool = False,
        name_pattern: str | None = None,
        mapper: TypeMapper | None = None,
    ) -> None:
        self._conn = connection
        self._schema = schema
        self._introspector = FunctionIntrospector(connection)
        self._mapper = mapper or TypeMapper()
        self._include_triggers = include_triggers
        self._name_pattern = name_pattern

    def generate(self) -> StubFile:
        """Introspect the schema and return a StubFile ready to render."""
        catalog = self._introspector.introspect(
            self._schema,
            include_triggers=self._include_triggers,
            name_pattern=self._name_pattern,
        )
        db_name = catalog.database
        functions = [
            StubFunction.from_function_info(f, self._mapper, jsonb_keys(f))
            for f in catalog.functions
        ]
        all_imports: set[str] = set()
        for fn in functions:
            all_imports |= fn.required_imports

        return StubFile(
            schema=self._schema,
            database=db_name,
            generated_at=datetime.now(UTC).isoformat(),
            functions=functions,
            imports=all_imports,
        )


def jsonb_keys(info: FunctionInfo) -> list[JSONBKey]:
    """The keys of the object a routine builds, read from its parse; ``[]`` when they cannot be.

    Every outermost ``jsonb_build_object`` call in the body gives its keys in
    order, each with its value's SQL: a call nested in another's arguments is a
    value, not more keys. A ``LANGUAGE sql`` body is parsed as SQL, a PL/pgSQL
    one compiled and read fragment by fragment. A key that is not a string
    constant, an odd argument count, or a body the parser rejects gives no keys,
    so no class is claimed for a shape that is not known.
    """
    try:
        trees = list(_body_trees(info))
    except (pglast.parser.ParseError, json.JSONDecodeError):
        return []
    keys: dict[str, JSONBKey] = {}
    for tree in trees:
        for call in _outermost_builders(tree):
            args = list(call.args or ())
            if len(args) % 2:
                return []
            for key, value in zip(args[::2], args[1::2], strict=True):
                name = getattr(getattr(key, "val", None), "sval", None)
                if type(key).__name__ != "A_Const" or name is None:
                    return []
                keys.setdefault(name, JSONBKey(key=name, value_expr=RawStream()(value)))
    return list(keys.values())


def _body_trees(info: FunctionInfo) -> Iterator[Any]:
    """The parse trees of *info*'s body: its statements, or its PL/pgSQL fragments."""
    language = info.language.lower()
    if language == "sql":
        yield from (raw.stmt for raw in pglast.parse_sql(info.source or ""))
    elif language == "plpgsql":
        compiled = plpgsql_parse.parse_body(_create_statement(info))
        for fragment in fragments(compiled):
            yield from (raw.stmt for raw in fragment.tree or ())


def _create_statement(info: FunctionInfo) -> str:
    """A ``CREATE FUNCTION`` the PL/pgSQL compiler reads *info*'s body in: its signature, its body."""
    source = info.source or ""
    tag = "$confiture$"
    while tag in source:
        tag = tag[:-1] + "_$"
    params = ", ".join(
        f"{param.mode.value} {param.name} {param.pg_type}" if param.name else param.pg_type
        for param in info.params
        if param.mode is not ParamMode.TABLE
    )
    returns = "void" if info.is_procedure else (info.return_type or "void")
    if info.returns_set:
        returns = f"SETOF {returns}"
    return f"CREATE FUNCTION f({params}) RETURNS {returns} LANGUAGE plpgsql AS {tag}{source}{tag}"


def _outermost_builders(tree: Any) -> Iterator[Any]:
    """Every ``jsonb_build_object`` call in *tree* that is not inside another one's arguments."""
    inner: set[int] = set()
    for node in walk_nodes(tree):
        if type(node).__name__ != "FuncCall" or node.funcname[-1].sval != _BUILDER:
            continue
        if id(node) in inner:
            continue
        inner.update(id(child) for arg in node.args or () for child in walk_nodes(arg))
        yield node
