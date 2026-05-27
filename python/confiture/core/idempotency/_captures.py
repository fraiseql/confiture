"""Normalized identifier captures for idempotency suggestion templates.

The regex and AST backends extract identifiers in incompatible shapes —
``re.Match.group(N)`` strings versus pglast typed nodes. The
:class:`Captures` dataclass is the single normalized form both backends
produce; suggestion-template functions take :class:`Captures` and never
need to know which backend the match came from.

All string fields hold post-unquoted, lowercased identifiers — quoting
is the template's job, not the capturer's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from confiture.core.idempotency.models import IdempotencyPattern


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
# Regex captures
# ---------------------------------------------------------------------------

_DENT = r"(?:\"[^\"]+\"|\w+)"  # quoted or unquoted identifier
_QUAL = rf"(?:({_DENT})\.)?({_DENT})"  # optional ``schema.`` + name; two groups
_IDENT_QUAL = rf"({_DENT})(?:\.({_DENT}))?"  # alt: name + optional ``.attr``

_RE_CREATE_TABLE = re.compile(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_QUAL}", re.IGNORECASE)
_RE_CREATE_INDEX = re.compile(
    rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?({_DENT})"
    rf"\s+ON\s+(?:ONLY\s+)?{_QUAL}",
    re.IGNORECASE,
)
_RE_CREATE_TYPE = re.compile(rf"CREATE\s+TYPE\s+{_QUAL}", re.IGNORECASE)
_RE_CREATE_SCHEMA = re.compile(
    rf"CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?({_DENT})", re.IGNORECASE
)
_RE_CREATE_SEQUENCE = re.compile(
    rf"CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_QUAL}", re.IGNORECASE
)
_RE_CREATE_EXTENSION = re.compile(
    rf"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?({_DENT})", re.IGNORECASE
)
_RE_CREATE_VIEW = re.compile(
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+{_QUAL}", re.IGNORECASE
)
_RE_ALTER_TABLE = re.compile(
    rf"ALTER\s+TABLE\s+(?:ONLY\s+)?{_QUAL}", re.IGNORECASE
)
_RE_ALTER_VIEW = re.compile(rf"ALTER\s+VIEW\s+{_QUAL}", re.IGNORECASE)
_RE_ALTER_MATVIEW = re.compile(
    rf"ALTER\s+MATERIALIZED\s+VIEW\s+{_QUAL}", re.IGNORECASE
)
_RE_ADD_COLUMN = re.compile(
    rf"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?({_DENT})", re.IGNORECASE
)
_RE_ADD_CONSTRAINT = re.compile(rf"ADD\s+CONSTRAINT\s+({_DENT})", re.IGNORECASE)
_RE_RENAME_COLUMN = re.compile(
    rf"RENAME\s+(?:COLUMN\s+)?({_DENT})\s+TO\s+({_DENT})", re.IGNORECASE
)
_RE_DROP_GENERIC = re.compile(
    r"DROP\s+(?:TABLE|VIEW|TYPE|SEQUENCE|SCHEMA|INDEX|MATERIALIZED\s+VIEW)\s+"
    rf"(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?{_QUAL}",
    re.IGNORECASE,
)


def _unquote(s: str | None) -> str | None:
    """Strip surrounding double-quotes from a SQL identifier, if any."""
    if s is None:
        return None
    s = s.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s.lower()


def _qual_pair(schema_group: str | None, name_group: str | None) -> tuple[str | None, str | None]:
    """Normalize a ``(schema, name)`` regex-group pair into clean identifiers."""
    return _unquote(schema_group), _unquote(name_group)


def captures_from_regex(pattern: IdempotencyPattern, m: re.Match[str]) -> Captures:
    """Build :class:`Captures` from a regex match for ``pattern``.

    Returns an all-``None`` :class:`Captures` when extraction can't
    pull identifiers reliably — the template machinery falls back to
    the generic suggestion in that case.
    """
    text = m.string[m.start() : min(m.end() + 200, len(m.string))]
    return _CAPTURES_REGEX_DISPATCH.get(pattern, _captures_regex_unknown)(text)


def _captures_regex_unknown(_text: str) -> Captures:
    return Captures()


def _captures_regex_create_table(text: str) -> Captures:
    m = _RE_CREATE_TABLE.search(text)
    if m is None:
        return Captures()
    schema, table = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, table=table)


def _captures_regex_create_index(text: str) -> Captures:
    m = _RE_CREATE_INDEX.search(text)
    if m is None:
        return Captures()
    index_name = _unquote(m.group(1))
    schema, table = _qual_pair(m.group(2), m.group(3))
    return Captures(index_name=index_name, schema=schema, table=table)


def _captures_regex_create_type(text: str) -> Captures:
    m = _RE_CREATE_TYPE.search(text)
    if m is None:
        return Captures()
    schema, type_name = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, type_name=type_name)


def _captures_regex_create_schema(text: str) -> Captures:
    m = _RE_CREATE_SCHEMA.search(text)
    if m is None:
        return Captures()
    return Captures(schema=_unquote(m.group(1)))


def _captures_regex_create_sequence(text: str) -> Captures:
    m = _RE_CREATE_SEQUENCE.search(text)
    if m is None:
        return Captures()
    schema, sequence = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, sequence=sequence)


def _captures_regex_create_extension(text: str) -> Captures:
    m = _RE_CREATE_EXTENSION.search(text)
    if m is None:
        return Captures()
    return Captures(extension=_unquote(m.group(1)))


def _captures_regex_create_view(text: str) -> Captures:
    m = _RE_CREATE_VIEW.search(text)
    if m is None:
        return Captures()
    schema, view = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, view=view)


def _captures_regex_alter_add_column(text: str) -> Captures:
    table_match = _RE_ALTER_TABLE.search(text)
    if table_match is None:
        return Captures()
    schema, table = _qual_pair(table_match.group(1), table_match.group(2))
    column_match = _RE_ADD_COLUMN.search(text)
    column = _unquote(column_match.group(1)) if column_match else None
    return Captures(schema=schema, table=table, column=column)


def _captures_regex_alter_add_constraint(text: str) -> Captures:
    table_match = _RE_ALTER_TABLE.search(text)
    if table_match is None:
        return Captures()
    schema, table = _qual_pair(table_match.group(1), table_match.group(2))
    constraint_match = _RE_ADD_CONSTRAINT.search(text)
    constraint = _unquote(constraint_match.group(1)) if constraint_match else None
    return Captures(schema=schema, table=table, constraint=constraint)


def _captures_regex_alter_rename_column(text: str) -> Captures:
    table_match = _RE_ALTER_TABLE.search(text)
    if table_match is None:
        return Captures()
    schema, table = _qual_pair(table_match.group(1), table_match.group(2))
    rename_match = _RE_RENAME_COLUMN.search(text)
    if rename_match is None:
        return Captures(schema=schema, table=table)
    column = _unquote(rename_match.group(1))
    new_column = _unquote(rename_match.group(2))
    return Captures(schema=schema, table=table, column=column, new_column=new_column)


def _captures_regex_alter_table_owner(text: str) -> Captures:
    m = _RE_ALTER_TABLE.search(text)
    if m is None:
        return Captures()
    schema, table = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, table=table)


def _captures_regex_alter_view_owner(text: str) -> Captures:
    m = _RE_ALTER_VIEW.search(text)
    if m is None:
        return Captures()
    schema, view = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, view=view)


def _captures_regex_alter_matview_owner(text: str) -> Captures:
    m = _RE_ALTER_MATVIEW.search(text)
    if m is None:
        return Captures()
    schema, view = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, view=view)


def _captures_regex_drop_generic(text: str) -> Captures:
    """Extract ``schema.name`` from any of the ``DROP <kind> …`` patterns."""
    m = _RE_DROP_GENERIC.search(text)
    if m is None:
        return Captures()
    schema, name = _qual_pair(m.group(1), m.group(2))
    return Captures(schema=schema, table=name)


_CAPTURES_REGEX_DISPATCH: dict[IdempotencyPattern, Any] = {
    IdempotencyPattern.CREATE_TABLE: _captures_regex_create_table,
    IdempotencyPattern.CREATE_INDEX: _captures_regex_create_index,
    IdempotencyPattern.CREATE_UNIQUE_INDEX: _captures_regex_create_index,
    IdempotencyPattern.CREATE_TYPE: _captures_regex_create_type,
    IdempotencyPattern.CREATE_SCHEMA: _captures_regex_create_schema,
    IdempotencyPattern.CREATE_SEQUENCE: _captures_regex_create_sequence,
    IdempotencyPattern.CREATE_EXTENSION: _captures_regex_create_extension,
    IdempotencyPattern.CREATE_VIEW: _captures_regex_create_view,
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: _captures_regex_create_view,
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: _captures_regex_alter_add_column,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK: _captures_regex_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY: _captures_regex_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE: _captures_regex_alter_add_constraint,
    IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN: _captures_regex_alter_rename_column,
    IdempotencyPattern.ALTER_TABLE_OWNER: _captures_regex_alter_table_owner,
    IdempotencyPattern.ALTER_VIEW_OWNER: _captures_regex_alter_view_owner,
    IdempotencyPattern.ALTER_MATVIEW_OWNER: _captures_regex_alter_matview_owner,
    IdempotencyPattern.DROP_TABLE: _captures_regex_drop_generic,
    IdempotencyPattern.DROP_INDEX: _captures_regex_drop_generic,
    IdempotencyPattern.DROP_VIEW: _captures_regex_drop_generic,
    IdempotencyPattern.DROP_TYPE: _captures_regex_drop_generic,
    IdempotencyPattern.DROP_SCHEMA: _captures_regex_drop_generic,
    IdempotencyPattern.DROP_SEQUENCE: _captures_regex_drop_generic,
}


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


def _captures_ast_create_function_stmt(node: Any) -> Captures:
    parts = _ast_name_parts(getattr(node, "funcname", None))
    if not parts:
        return Captures()
    if len(parts) >= 2:
        return Captures(schema=parts[0].lower(), table=parts[1].lower())
    return Captures(table=parts[0].lower())


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
        if sub_int == 0:  # AT_ADD_COLUMN
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
        if sub_int == 17:  # AT_ADD_CONSTRAINT
            constraint_def = getattr(cmd, "def_", None)
            conname = getattr(constraint_def, "conname", None) if constraint_def is not None else None
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
