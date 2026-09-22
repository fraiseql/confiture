"""Normalized identifier captures for idempotency suggestion templates.

pglast carries an identifier in a node whose shape varies by statement kind
(a ``RangeVar``, a ``String`` list, a ``TypeName``). :class:`Captures` is the
one normalized form: suggestion-template functions take it and never read a
parse node.

All string fields hold post-unquoted, lowercased identifiers — quoting
is the template's job, not the capturer's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.idempotency.models import IdempotencyPattern

# Resolved by name, never by literal ordinal (#192): pglast 8 renumbered
# ``AlterTableType``. Both are compared inline, where a literal is invisible to
# a grep for `_NAME = <int>` — which is why the binding guard checks inline
# comparisons as well as constant blocks.
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")


@dataclass(frozen=True)
class Captures:
    """Normalized identifiers extracted from an idempotency-pattern match.

    All fields are optional — a backend that cannot extract a given
    field leaves it ``None`` and the template falls back to the generic
    suggestion. Two :class:`Captures` instances compare equal when
    every field matches, which is the property the cross-backend
    equivalence tests rely on.
    """

    schema: str | None = None
    table: str | None = None
    column: str | None = None
    new_column: str | None = None
    constraint: str | None = None
    type_name: str | None = None
    index_name: str | None = None
    view: str | None = None
    sequence: str | None = None
    extension: str | None = None


# ---------------------------------------------------------------------------
# AST captures
# ---------------------------------------------------------------------------


def _ast_string_value(node: Any) -> str | None:
    """Pull ``.sval`` from a pglast ``String`` node, or ``None``."""
    if node is None:
        return None
    sval = getattr(node, "sval", None)
    if sval is None:
        return None
    return str(sval)


def _ast_name_parts(parts: Any) -> list[str]:
    """Render a pglast ``(String, String, …)`` tuple as plain identifiers."""
    if not isinstance(parts, (tuple, list)):
        return []
    out: list[str] = []
    for part in parts:
        s = _ast_string_value(part)
        if s is None:
            return []
        out.append(s)
    return out


def _ast_qualified(relation: Any) -> tuple[str | None, str | None]:
    """``(schema, relname)`` from a pglast ``RangeVar`` node, both lowercased."""
    if relation is None:
        return None, None
    schema = getattr(relation, "schemaname", None)
    relname = getattr(relation, "relname", None)
    return (
        str(schema).lower() if schema else None,
        str(relname).lower() if relname else None,
    )


def captures_from_ast(pattern: IdempotencyPattern, node: Any) -> Captures:
    """Build :class:`Captures` from an AST node for ``pattern``."""
    return _CAPTURES_AST_DISPATCH.get(pattern, _captures_ast_unknown)(node)


def _captures_ast_unknown(_node: Any) -> Captures:
    return Captures()


def _captures_ast_create_stmt(node: Any) -> Captures:
    schema, table = _ast_qualified(getattr(node, "relation", None))
    return Captures(schema=schema, table=table)


def _captures_ast_index_stmt(node: Any) -> Captures:
    index_name = getattr(node, "idxname", None)
    schema, table = _ast_qualified(getattr(node, "relation", None))
    return Captures(
        index_name=str(index_name).lower() if index_name else None,
        schema=schema,
        table=table,
    )


def _captures_ast_create_enum_stmt(node: Any) -> Captures:
    parts = _ast_name_parts(getattr(node, "typeName", None))
    if not parts:
        return Captures()
    if len(parts) >= 2:
        return Captures(schema=parts[0].lower(), type_name=parts[1].lower())
    return Captures(type_name=parts[0].lower())


def _captures_ast_create_schema_stmt(node: Any) -> Captures:
    name = getattr(node, "schemaname", None)
    return Captures(schema=str(name).lower() if name else None)


def _captures_ast_create_seq_stmt(node: Any) -> Captures:
    schema, name = _ast_qualified(getattr(node, "sequence", None))
    return Captures(schema=schema, sequence=name)


def _captures_ast_create_extension_stmt(node: Any) -> Captures:
    name = getattr(node, "extname", None)
    return Captures(extension=str(name).lower() if name else None)


def _captures_ast_view_stmt(node: Any) -> Captures:
    schema, view = _ast_qualified(getattr(node, "view", None))
    return Captures(schema=schema, view=view)


def _captures_ast_alter_add_column(node: Any) -> Captures:
    schema, table = _ast_qualified(getattr(node, "relation", None))
    column: str | None = None
    for cmd in getattr(node, "cmds", None) or ():
        subtype = getattr(cmd, "subtype", None)
        sub_val = getattr(subtype, "value", subtype)
        try:
            sub_int = int(sub_val) if sub_val is not None else None
        except (TypeError, ValueError):
            sub_int = None
        if sub_int == _AT_ADD_COLUMN:
            col_def = getattr(cmd, "def_", None)
            colname = getattr(col_def, "colname", None) if col_def is not None else None
            if colname:
                column = str(colname).lower()
                break
    return Captures(schema=schema, table=table, column=column)


def _captures_ast_alter_add_constraint(node: Any) -> Captures:
    schema, table = _ast_qualified(getattr(node, "relation", None))
    constraint: str | None = None
    for cmd in getattr(node, "cmds", None) or ():
        subtype = getattr(cmd, "subtype", None)
        sub_val = getattr(subtype, "value", subtype)
        try:
            sub_int = int(sub_val) if sub_val is not None else None
        except (TypeError, ValueError):
            sub_int = None
        if sub_int == _AT_ADD_CONSTRAINT:
            constraint_def = getattr(cmd, "def_", None)
            conname = (
                getattr(constraint_def, "conname", None) if constraint_def is not None else None
            )
            if conname:
                constraint = str(conname).lower()
                break
    return Captures(schema=schema, table=table, constraint=constraint)


def _captures_ast_rename_stmt(node: Any) -> Captures:
    schema, table = _ast_qualified(getattr(node, "relation", None))
    old = getattr(node, "subname", None)
    new = getattr(node, "newname", None)
    return Captures(
        schema=schema,
        table=table,
        column=str(old).lower() if old else None,
        new_column=str(new).lower() if new else None,
    )


def _captures_ast_alter_table_owner(node: Any) -> Captures:
    schema, table = _ast_qualified(getattr(node, "relation", None))
    return Captures(schema=schema, table=table)


def _captures_ast_alter_view_owner(node: Any) -> Captures:
    schema, view = _ast_qualified(getattr(node, "relation", None))
    return Captures(schema=schema, view=view)


def _captures_ast_alter_matview_owner(node: Any) -> Captures:
    schema, view = _ast_qualified(getattr(node, "relation", None))
    return Captures(schema=schema, view=view)


def _captures_ast_drop_stmt(node: Any) -> Captures:
    """Pull the first dropped object's qualified name onto ``schema``/``table``."""
    objects = getattr(node, "objects", None) or ()
    for obj in objects:
        if isinstance(obj, tuple):
            parts = _ast_name_parts(obj)
            if not parts:
                continue
            if len(parts) >= 2:
                return Captures(schema=parts[0].lower(), table=parts[1].lower())
            return Captures(table=parts[0].lower())
        sval = _ast_string_value(obj)
        if sval:
            return Captures(table=sval.lower())
    return Captures()


_CAPTURES_AST_DISPATCH: dict[IdempotencyPattern, Any] = {
    IdempotencyPattern.CREATE_TABLE: _captures_ast_create_stmt,
    IdempotencyPattern.CREATE_INDEX: _captures_ast_index_stmt,
    IdempotencyPattern.CREATE_UNIQUE_INDEX: _captures_ast_index_stmt,
    IdempotencyPattern.CREATE_TYPE: _captures_ast_create_enum_stmt,
    IdempotencyPattern.CREATE_SCHEMA: _captures_ast_create_schema_stmt,
    IdempotencyPattern.CREATE_SEQUENCE: _captures_ast_create_seq_stmt,
    IdempotencyPattern.CREATE_EXTENSION: _captures_ast_create_extension_stmt,
    IdempotencyPattern.CREATE_VIEW: _captures_ast_view_stmt,
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: _captures_ast_view_stmt,
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: _captures_ast_alter_add_column,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK: _captures_ast_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY: _captures_ast_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE: _captures_ast_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN: _captures_ast_rename_stmt,
    IdempotencyPattern.ALTER_TABLE_OWNER: _captures_ast_alter_table_owner,
    IdempotencyPattern.ALTER_VIEW_OWNER: _captures_ast_alter_view_owner,
    IdempotencyPattern.ALTER_MATVIEW_OWNER: _captures_ast_alter_matview_owner,
    IdempotencyPattern.DROP_TABLE: _captures_ast_drop_stmt,
    IdempotencyPattern.DROP_INDEX: _captures_ast_drop_stmt,
    IdempotencyPattern.DROP_VIEW: _captures_ast_drop_stmt,
    IdempotencyPattern.DROP_TYPE: _captures_ast_drop_stmt,
    IdempotencyPattern.DROP_SCHEMA: _captures_ast_drop_stmt,
    IdempotencyPattern.DROP_SEQUENCE: _captures_ast_drop_stmt,
}
