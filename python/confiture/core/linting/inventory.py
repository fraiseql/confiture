"""The object inventory the lint rules read (Phase 05 #216, Phase 07 #217/#218).

Built once per lint run from ``pglast.parser.parse_sql``. Table and column names
are kept as written in the source — pglast folds unquoted identifiers to
lowercase, and ``naming_001`` / ``naming_002`` judge the spelling the author
typed — so each identifier is read back from the statement text at the node's
location. A schema qualifier is data on the object, never a reason to miss it.

Every ``CREATE`` is one entry: a second definition of the same key is a second
entry with its own offset, which is what the duplicate check reads. A function's
identity is its name *and* the types of its input parameters, so
``COMMENT ON FUNCTION f(integer)`` documents one overload and not its sibling.
Offsets and lines are character positions into the text that was parsed,
which is what pglast reports.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

import pglast
from pglast.stream import RawStream

from confiture.core._pglast_enums import member as _pg_member

_CONSTR_PRIMARY = _pg_member("ConstrType", "CONSTR_PRIMARY")
_OBJECT_TABLE = _pg_member("ObjectType", "OBJECT_TABLE")
_OBJECT_FUNCTION = _pg_member("ObjectType", "OBJECT_FUNCTION")
_OBJECT_PROCEDURE = _pg_member("ObjectType", "OBJECT_PROCEDURE")
_OBJECT_ROUTINE = _pg_member("ObjectType", "OBJECT_ROUTINE")
_OBJECT_VIEW = _pg_member("ObjectType", "OBJECT_VIEW")
_OBJECT_MATVIEW = _pg_member("ObjectType", "OBJECT_MATVIEW")
_OBJECT_TYPE = _pg_member("ObjectType", "OBJECT_TYPE")
_OBJECT_DOMAIN = _pg_member("ObjectType", "OBJECT_DOMAIN")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")

_PLAIN_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")

#: Which inventory kinds a ``COMMENT ON <object type>`` statement documents.
_COMMENT_TARGETS: dict[int | None, tuple[str, ...]] = {
    _OBJECT_TABLE: ("table",),
    _OBJECT_FUNCTION: ("function",),
    _OBJECT_PROCEDURE: ("procedure",),
    _OBJECT_ROUTINE: ("function", "procedure"),
    _OBJECT_VIEW: ("view",),
    _OBJECT_MATVIEW: ("matview",),
    _OBJECT_TYPE: ("type",),
    _OBJECT_DOMAIN: ("domain",),
}

#: Parameter modes that take part in a function's identity (IN, INOUT, VARIADIC
#: and the default mode); OUT and TABLE parameters do not.
_INPUT_MODES = frozenset({"d", "i", "b", "v"})


@dataclass(frozen=True)
class SchemaColumn:
    """A column as written: ``name`` keeps the author's case and quoting is stripped."""

    name: str
    folded: str
    line: int


@dataclass
class SchemaObject:
    """One ``CREATE`` statement, with what the rules need to know about it.

    ``kind`` is one of ``table``, ``function``, ``procedure``, ``view``,
    ``matview``, ``type`` (composite or enum) or ``domain``. ``signature`` is the
    comma-joined input parameter types of a function or procedure — the part of
    its identity after the name — and ``None`` for every other kind. ``offset``
    is the character position of the statement in the parsed text; ``file`` is
    set by callers that inventory one file at a time. ``replace`` and
    ``if_not_exists`` record ``CREATE OR REPLACE`` / ``IF NOT EXISTS``, which
    decide what a second definition of the same object does at build time.
    """

    kind: str
    name: str
    schema: str | None
    folded_name: str
    folded_schema: str | None
    line: int
    columns: list[SchemaColumn] = field(default_factory=list)
    has_primary_key: bool = False
    is_partition: bool = False
    is_temporary: bool = False
    documented: bool = False
    signature: str | None = None
    offset: int = 0
    file: str | None = None
    replace: bool = False
    if_not_exists: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    @property
    def identity(self) -> str:
        """``schema.name(signature)`` for routines, ``schema.name`` otherwise."""
        return (
            f"{self.qualified}({self.signature})" if self.signature is not None else self.qualified
        )


@dataclass
class Inventory:
    objects: list[SchemaObject] = field(default_factory=list)

    @property
    def tables(self) -> list[SchemaObject]:
        return [o for o in self.objects if o.kind == "table"]

    def find(self, folded_schema: str | None, folded_name: str) -> SchemaObject | None:
        """The table a statement refers to; a missing schema on either side matches any."""
        matches = self.find_all(("table",), folded_schema, folded_name)
        return matches[0] if matches else None

    def find_all(
        self,
        kinds: tuple[str, ...],
        folded_schema: str | None,
        folded_name: str,
        signature: str | None = None,
    ) -> list[SchemaObject]:
        """Every definition of the object a statement names, in source order.

        A missing schema on either side matches any schema; ``signature`` narrows
        routines to one overload when given.
        """
        matches: list[SchemaObject] = []
        for obj in self.objects:
            if obj.kind not in kinds or obj.folded_name != folded_name:
                continue
            if (
                folded_schema is not None
                and obj.folded_schema is not None
                and obj.folded_schema != folded_schema
            ):
                continue
            if signature is not None and obj.signature != signature:
                continue
            matches.append(obj)
        return matches


def _enum_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def identifier_at(sql: str, location: int | None, fallback: str) -> list[str]:
    """The (possibly qualified) identifier written at ``location``, quotes stripped.

    Returns one segment per dotted part; ``fallback`` (pglast's folded name) when
    the location is missing or does not start an identifier.
    """
    if location is None or location < 0 or location >= len(sql):
        return [fallback]
    segments: list[str] = []
    pos = location
    while pos < len(sql):
        if sql[pos] == '"':
            end = pos + 1
            text: list[str] = []
            while end < len(sql):
                if sql[end] == '"':
                    if end + 1 < len(sql) and sql[end + 1] == '"':
                        text.append('"')
                        end += 2
                        continue
                    break
                text.append(sql[end])
                end += 1
            segments.append("".join(text))
            pos = end + 1
        else:
            m = _PLAIN_IDENT.match(sql, pos)
            if not m:
                break
            segments.append(m.group(0))
            pos = m.end()
        if pos < len(sql) and sql[pos] == ".":
            pos += 1
            continue
        break
    return segments or [fallback]


def _line_of(sql: str, location: int | None) -> int:
    if location is None or location < 0:
        return 1
    return sql.count("\n", 0, min(location, len(sql))) + 1


def _statement_offset(sql: str, raw: Any) -> int:
    """Where the statement's first token starts, past any whitespace or comment.

    pglast reports character positions into the parsed text (verified against
    non-ASCII prefixes), so no byte-to-character conversion is applied.
    """
    pos = getattr(raw, "stmt_location", 0) or 0
    while pos < len(sql):
        if sql[pos].isspace():
            pos += 1
        elif sql.startswith("--", pos):
            newline = sql.find("\n", pos)
            pos = len(sql) if newline < 0 else newline + 1
        elif sql.startswith("/*", pos):
            close = sql.find("*/", pos + 2)
            pos = len(sql) if close < 0 else close + 2
        else:
            break
    return pos


def _column(sql: str, node: Any) -> SchemaColumn:
    written = identifier_at(sql, getattr(node, "location", None), node.colname)[-1]
    return SchemaColumn(
        name=written, folded=node.colname, line=_line_of(sql, getattr(node, "location", None))
    )


def _has_primary_constraint(constraints: Any) -> bool:
    return any(
        _enum_value(getattr(c, "contype", None)) == _CONSTR_PRIMARY for c in constraints or []
    )


def _type_text(type_name: Any) -> str:
    """``integer[]`` for a ``TypeName``, typmods dropped — an argument's identity."""
    bare = copy.deepcopy(type_name)
    bare.typmods = None
    return RawStream()(bare)


def _signature(parameters: Any) -> str:
    return ", ".join(
        _type_text(p.argType)
        for p in parameters or []
        if getattr(p.mode, "value", p.mode) in _INPUT_MODES
    )


def _split_names(names: Any) -> tuple[str | None, str]:
    """``(schema, name)`` from a pglast name list; the schema is ``None`` when absent."""
    parts = [getattr(n, "sval", None) for n in names or []]
    parts = [p for p in parts if p is not None]
    return (parts[-2] if len(parts) >= 2 else None), parts[-1]


def _object(
    kind: str, schema: str | None, name: str, line: int, offset: int, **extra: Any
) -> SchemaObject:
    return SchemaObject(
        kind=kind,
        name=name,
        schema=schema,
        folded_name=name,
        folded_schema=schema,
        line=line,
        offset=offset,
        **extra,
    )


def _table_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    rv = stmt.relation
    parts = identifier_at(sql, rv.location, rv.relname)
    name = parts[-1]
    schema = parts[-2] if len(parts) >= 2 else None
    table = SchemaObject(
        kind="table",
        name=name,
        schema=schema,
        folded_name=rv.relname,
        folded_schema=rv.schemaname,
        line=_line_of(sql, rv.location),
        is_partition=stmt.partbound is not None,
        is_temporary=getattr(rv, "relpersistence", "p") == "t",
        offset=offset,
        if_not_exists=bool(getattr(stmt, "if_not_exists", False)),
    )
    for elt in stmt.tableElts or []:
        kind = type(elt).__name__
        if kind == "ColumnDef":
            table.columns.append(_column(sql, elt))
            if _has_primary_constraint(elt.constraints):
                table.has_primary_key = True
        elif kind == "Constraint" and _enum_value(elt.contype) == _CONSTR_PRIMARY:
            table.has_primary_key = True
    return table


def _routine_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    schema, name = _split_names(stmt.funcname)
    return _object(
        "procedure" if stmt.is_procedure else "function",
        schema,
        name,
        _line_of(sql, offset),
        offset,
        signature=_signature(stmt.parameters),
        replace=bool(getattr(stmt, "replace", False)),
    )


def _relation_object(sql: str, kind: str, rv: Any, offset: int) -> SchemaObject:
    return _object(kind, rv.schemaname, rv.relname, _line_of(sql, rv.location), offset)


def _object_from_statement(sql: str, raw: Any) -> SchemaObject | None:
    stmt = raw.stmt
    kind = type(stmt).__name__
    offset = _statement_offset(sql, raw)
    if kind == "CreateStmt":
        return _table_from_create(sql, stmt, offset)
    if kind == "CreateFunctionStmt":
        return _routine_from_create(sql, stmt, offset)
    if kind == "ViewStmt":
        view = _relation_object(sql, "view", stmt.view, offset)
        view.replace = bool(getattr(stmt, "replace", False))
        return view
    if kind == "CreateTableAsStmt" and _enum_value(stmt.objtype) == _OBJECT_MATVIEW:
        matview = _relation_object(sql, "matview", stmt.into.rel, offset)
        matview.if_not_exists = bool(getattr(stmt, "if_not_exists", False))
        return matview
    if kind == "CompositeTypeStmt":
        return _relation_object(sql, "type", stmt.typevar, offset)
    if kind == "CreateEnumStmt":
        schema, name = _split_names(stmt.typeName)
        return _object("type", schema, name, _line_of(sql, offset), offset)
    if kind == "CreateDomainStmt":
        schema, name = _split_names(stmt.domainname)
        return _object("domain", schema, name, _line_of(sql, offset), offset)
    return None


def _apply_alter(sql: str, stmt: Any, inventory: Inventory) -> None:
    rv = stmt.relation
    table = inventory.find(rv.schemaname, rv.relname)
    if table is None:
        return
    for cmd in stmt.cmds or []:
        subtype = _enum_value(getattr(cmd, "subtype", None))
        definition = getattr(cmd, "def_", None)
        if subtype == _AT_ADD_CONSTRAINT and definition is not None:
            if _enum_value(getattr(definition, "contype", None)) == _CONSTR_PRIMARY:
                table.has_primary_key = True
        elif (
            subtype == _AT_ADD_COLUMN
            and definition is not None
            and type(definition).__name__ == "ColumnDef"
        ):
            table.columns.append(_column(sql, definition))
            if _has_primary_constraint(definition.constraints):
                table.has_primary_key = True


def _comment_target(stmt: Any) -> tuple[str | None, str, str | None] | None:
    """``(schema, name, signature)`` the comment names; signature ``None`` = any."""
    obj = stmt.object
    node_kind = type(obj).__name__
    if node_kind == "ObjectWithArgs":
        schema, name = _split_names(obj.objname)
        if getattr(obj, "args_unspecified", False) or obj.objargs is None:
            return schema, name, None
        return schema, name, ", ".join(_type_text(t) for t in obj.objargs)
    if node_kind == "TypeName":
        schema, name = _split_names(obj.names)
        return schema, name, None
    names = [getattr(o, "sval", None) for o in (obj or [])]
    names = [n for n in names if n is not None]
    if not names:
        return None
    return (names[-2] if len(names) >= 2 else None), names[-1], None


def _apply_comment(stmt: Any, inventory: Inventory) -> None:
    kinds = _COMMENT_TARGETS.get(_enum_value(stmt.objtype))
    if kinds is None:
        return
    target = _comment_target(stmt)
    if target is None:
        return
    schema, name, signature = target
    for obj in inventory.find_all(kinds, schema, name, signature):
        obj.documented = True


def build_inventory(sql: str) -> Inventory:
    """Parse ``sql`` and collect its objects. Raises ``pglast.parser.ParseError``."""
    inventory = Inventory()
    raws = list(pglast.parse_sql(sql) or [])
    for raw in raws:
        obj = _object_from_statement(sql, raw)
        if obj is not None:
            inventory.objects.append(obj)
    for raw in raws:
        stmt = raw.stmt
        kind = type(stmt).__name__
        if kind == "AlterTableStmt":
            _apply_alter(sql, stmt, inventory)
        elif kind == "CommentStmt":
            _apply_comment(stmt, inventory)
    return inventory
