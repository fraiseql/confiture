"""The object inventory the default lint rules read (Phase 05, #216).

Built once per lint run from ``pglast.parser.parse_sql``. Names are kept as
written in the source — pglast folds unquoted identifiers to lowercase, and
``naming_001`` / ``naming_002`` judge the spelling the author typed — so each
identifier is read back from the statement text at the node's location.
A schema qualifier is data on the object, never a reason to miss it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pglast

from confiture.core._pglast_enums import member as _pg_member

_CONSTR_PRIMARY = _pg_member("ConstrType", "CONSTR_PRIMARY")
_OBJECT_TABLE = _pg_member("ObjectType", "OBJECT_TABLE")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")

_PLAIN_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


@dataclass(frozen=True)
class SchemaColumn:
    """A column as written: ``name`` keeps the author's case and quoting is stripped."""

    name: str
    folded: str
    line: int


@dataclass
class SchemaObject:
    """A table from ``CREATE TABLE``, with what the default rules need to know."""

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

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass
class Inventory:
    tables: list[SchemaObject] = field(default_factory=list)

    def find(self, folded_schema: str | None, folded_name: str) -> SchemaObject | None:
        """The table a statement refers to; a missing schema on either side matches any."""
        for table in self.tables:
            if table.folded_name != folded_name:
                continue
            if (
                folded_schema is None
                or table.folded_schema is None
                or table.folded_schema == folded_schema
            ):
                return table
        return None


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


def _column(sql: str, node: Any) -> SchemaColumn:
    written = identifier_at(sql, getattr(node, "location", None), node.colname)[-1]
    return SchemaColumn(
        name=written, folded=node.colname, line=_line_of(sql, getattr(node, "location", None))
    )


def _has_primary_constraint(constraints: Any) -> bool:
    return any(
        _enum_value(getattr(c, "contype", None)) == _CONSTR_PRIMARY for c in constraints or []
    )


def _table_from_create(sql: str, stmt: Any) -> SchemaObject:
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


def _apply_comment(stmt: Any, inventory: Inventory) -> None:
    if _enum_value(stmt.objtype) != _OBJECT_TABLE:
        return
    names = [getattr(o, "sval", None) for o in (stmt.object or [])]
    names = [n for n in names if n is not None]
    if not names:
        return
    table = inventory.find(names[-2] if len(names) >= 2 else None, names[-1])
    if table is not None:
        table.documented = True


def build_inventory(sql: str) -> Inventory:
    """Parse ``sql`` and collect its tables. Raises ``pglast.parser.ParseError``."""
    inventory = Inventory()
    tree = pglast.parse_sql(sql)
    statements = [raw.stmt for raw in tree or []]
    for stmt in statements:
        if type(stmt).__name__ == "CreateStmt":
            inventory.tables.append(_table_from_create(sql, stmt))
    for stmt in statements:
        kind = type(stmt).__name__
        if kind == "AlterTableStmt":
            _apply_alter(sql, stmt, inventory)
        elif kind == "CommentStmt":
            _apply_comment(stmt, inventory)
    return inventory
