"""pglast-backed idempotency detector.

Mirrors :mod:`patterns` in interface — ``_detect_via_ast(sql)`` returns
the same ``list[PatternMatch]`` shape — but uses PostgreSQL's own parser
(via :mod:`pglast`) to recognize statements structurally rather than via
regex.

The dispatcher in :mod:`patterns` picks this backend when pglast is
importable and ``CONFITURE_IDEMPOTENCY_FORCE_REGEX`` is unset. Parse
failures bubble up as :class:`pglast.parser.ParseError`; the dispatcher
catches them and falls through to the regex backend so partial or
templated SQL still gets scanned.

Visitor layout
--------------

Detection runs in two passes:

1. **Pair collection**: walk every statement once to record names
   dropped with ``IF EXISTS`` — views, functions, procedures, and table
   constraints. Names come straight from AST nodes, so quoted/long
   identifiers are no longer truncated (issue #122 Bug 2).

2. **Match emission**: walk the statements again, dispatching by class
   name (``CreateStmt``, ``AlterTableStmt``, ``DropStmt``, …) to a
   ``_visit_<name>`` callable. Visitors that produce *pair-suppressible*
   matches (``CREATE VIEW``, ``ADD CONSTRAINT``, ``CREATE OR REPLACE``
   shape-risk notes) consult the recorded drops and skip emission when
   a matching drop precedes the create.

Unknown nodes are skipped — the regex backend is the safety net for any
statement shape we don't yet recognize, and DO-block bodies are opaque
to pglast, so non-idempotent statements wrapped in a protective
``DO $$ … EXCEPTION WHEN … $$`` are never visited as top-level
statements at all.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

from confiture.core.idempotency._ast_visitor import (
    _extract_snippet_from_stmt,
    _iter_statements,
    _line_for_stmt,
    _StatementContext,
)
from confiture.core.idempotency.models import IdempotencyPattern

if TYPE_CHECKING:
    from confiture.core.idempotency.patterns import PatternMatch


@cache
def is_pglast_available() -> bool:
    """Return True when the ``pglast`` package is importable.

    Cached because ``importlib.util.find_spec`` walks ``sys.path`` on every
    call; the answer doesn't change at runtime in practice.
    """
    return importlib.util.find_spec("pglast") is not None


# ---------------------------------------------------------------------------
# Enum constants
# ---------------------------------------------------------------------------

# pglast.enums.parsenodes.ObjectType
_OBJECT_TABLE = 41
_OBJECT_VIEW = 51
_OBJECT_MATVIEW = 23
_OBJECT_INDEX = 20
_OBJECT_FUNCTION = 19
_OBJECT_PROCEDURE = 29
_OBJECT_TYPE = 49
_OBJECT_SCHEMA = 36
_OBJECT_SEQUENCE = 37
_OBJECT_COLUMN = 6

# pglast.enums.parsenodes.AlterTableType
_AT_ADD_COLUMN = 0
_AT_ADD_CONSTRAINT = 17
_AT_DROP_CONSTRAINT = 23
_AT_CHANGE_OWNER = 27

# pglast.enums.parsenodes.ConstrType
_CONSTRAINT_PATTERNS: dict[int, IdempotencyPattern] = {
    5: IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
    6: IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY,
    7: IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE,
}

_OWNER_PATTERNS: dict[int, IdempotencyPattern] = {
    _OBJECT_TABLE: IdempotencyPattern.ALTER_TABLE_OWNER,
    _OBJECT_VIEW: IdempotencyPattern.ALTER_VIEW_OWNER,
    _OBJECT_MATVIEW: IdempotencyPattern.ALTER_MATVIEW_OWNER,
}

_DROP_PATTERNS: dict[int, IdempotencyPattern] = {
    _OBJECT_TABLE: IdempotencyPattern.DROP_TABLE,
    _OBJECT_INDEX: IdempotencyPattern.DROP_INDEX,
    _OBJECT_FUNCTION: IdempotencyPattern.DROP_FUNCTION,
    _OBJECT_VIEW: IdempotencyPattern.DROP_VIEW,
    _OBJECT_TYPE: IdempotencyPattern.DROP_TYPE,
    _OBJECT_SCHEMA: IdempotencyPattern.DROP_SCHEMA,
    _OBJECT_SEQUENCE: IdempotencyPattern.DROP_SEQUENCE,
}


def _enum_value(value: object) -> int | None:
    """Coerce a pglast enum (or raw int) to its integer value, or None."""
    if value is None:
        return None
    inner = getattr(value, "value", value)
    try:
        return int(inner)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Name extraction
# ---------------------------------------------------------------------------


def _qualified_name(relation: object) -> str | None:
    """Return ``schema.relname`` (or just ``relname``) lowercased, or None.

    Accepts pglast ``RangeVar`` nodes.
    """
    if relation is None:
        return None
    relname = getattr(relation, "relname", None)
    if not relname:
        return None
    schemaname = getattr(relation, "schemaname", None)
    if schemaname:
        return f"{str(schemaname).lower()}.{str(relname).lower()}"
    return str(relname).lower()


def _dotted_from_string_tuple(parts: object) -> str | None:
    """Render a pglast ``(String, String, …)`` tuple as ``a.b`` lowercased."""
    if not isinstance(parts, (tuple, list)):
        return None
    names: list[str] = []
    for part in parts:
        sval = getattr(part, "sval", None)
        if sval is None:
            return None
        names.append(str(sval).lower())
    return ".".join(names) if names else None


def _drop_object_names(stmt: object) -> list[str]:
    """Extract the dropped object names from a ``DropStmt`` node.

    Handles two shapes pglast emits:
    - tuple-of-``String`` (tables, views, types, schemas, sequences, indexes)
    - ``ObjectWithArgs`` with ``objname`` (functions, procedures, aggregates)

    Returns lowercased, dot-qualified names — same shape as
    :func:`_qualified_name` so the two can be compared directly.
    """
    objects = getattr(stmt, "objects", None) or ()
    names: list[str] = []
    for obj in objects:
        if isinstance(obj, tuple):
            dotted = _dotted_from_string_tuple(obj)
            if dotted:
                names.append(dotted)
            continue
        objname = getattr(obj, "objname", None)
        if objname is not None:
            dotted = _dotted_from_string_tuple(objname)
            if dotted:
                names.append(dotted)
            continue
        # Schemas come through as bare String nodes (no surrounding tuple).
        sval = getattr(obj, "sval", None)
        if sval:
            names.append(str(sval).lower())
    return names


def _funcname_dotted(funcname: object) -> str | None:
    """Render ``CreateFunctionStmt.funcname`` as a dotted lowercased string."""
    if not funcname:
        return None
    return _dotted_from_string_tuple(funcname)


# ---------------------------------------------------------------------------
# Pair-drop tracking
# ---------------------------------------------------------------------------


@dataclass
class _PairDrops:
    """Names dropped with ``IF EXISTS`` earlier in the SQL.

    Populated by :func:`_collect_pair_drops` in pass 1, consulted by the
    visitors in pass 2 to suppress matches whose corresponding object
    was already dropped (the idempotent DROP+CREATE pattern).
    """

    views: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)
    procedures: set[str] = field(default_factory=set)
    constraints: set[str] = field(default_factory=set)


def _collect_pair_drops(statements: list[_StatementContext]) -> _PairDrops:
    drops = _PairDrops()
    for ctx in statements:
        stmt = ctx.stmt
        name = type(stmt).__name__
        if name == "DropStmt":
            if not stmt.missing_ok:
                continue
            kind = _enum_value(stmt.removeType)
            for obj_name in _drop_object_names(stmt):
                if kind == _OBJECT_VIEW:
                    drops.views.add(obj_name)
                elif kind == _OBJECT_FUNCTION:
                    drops.functions.add(obj_name)
                elif kind == _OBJECT_PROCEDURE:
                    drops.procedures.add(obj_name)
        elif name == "AlterTableStmt":
            for cmd in stmt.cmds or ():
                if _enum_value(cmd.subtype) == _AT_DROP_CONSTRAINT and cmd.missing_ok and cmd.name:
                    drops.constraints.add(str(cmd.name).lower())
    return drops


# ---------------------------------------------------------------------------
# Match construction
# ---------------------------------------------------------------------------


def _make_match(
    pattern: IdempotencyPattern,
    ctx: _StatementContext,
    sql: str,
    severity: str = "error",
) -> PatternMatch:
    from confiture.core.idempotency.patterns import PatternMatch  # noqa: PLC0415

    return PatternMatch(
        pattern=pattern,
        sql_snippet=_extract_snippet_from_stmt(sql, ctx.stmt_location, ctx.stmt_len),
        line_number=_line_for_stmt(sql, ctx.stmt_location),
        start_pos=ctx.stmt_location,
        end_pos=ctx.stmt_location + ctx.stmt_len,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# CREATE visitors
# ---------------------------------------------------------------------------


def _visit_create_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    if ctx.stmt.if_not_exists:
        return
    matches.append(_make_match(IdempotencyPattern.CREATE_TABLE, ctx, sql))


def _visit_index_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    stmt = ctx.stmt
    if stmt.if_not_exists:
        return
    pattern = (
        IdempotencyPattern.CREATE_UNIQUE_INDEX if stmt.unique else IdempotencyPattern.CREATE_INDEX
    )
    matches.append(_make_match(pattern, ctx, sql))


def _visit_create_schema_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    if ctx.stmt.if_not_exists:
        return
    matches.append(_make_match(IdempotencyPattern.CREATE_SCHEMA, ctx, sql))


def _visit_create_enum_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    """``CREATE TYPE … AS ENUM (…)`` — no ``IF NOT EXISTS`` form exists."""
    matches.append(_make_match(IdempotencyPattern.CREATE_TYPE, ctx, sql))


def _visit_create_extension_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    if ctx.stmt.if_not_exists:
        return
    matches.append(_make_match(IdempotencyPattern.CREATE_EXTENSION, ctx, sql))


def _visit_create_seq_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    if ctx.stmt.if_not_exists:
        return
    matches.append(_make_match(IdempotencyPattern.CREATE_SEQUENCE, ctx, sql))


def _visit_create_function_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], drops: _PairDrops
) -> None:
    """``CREATE [OR REPLACE] FUNCTION|PROCEDURE …``.

    Without ``OR REPLACE``: hard error (``CREATE_FUNCTION`` /
    ``CREATE_PROCEDURE``). With ``OR REPLACE``: info-severity shape-risk
    note, suppressed when a matching ``DROP IF EXISTS`` precedes it.
    """
    stmt = ctx.stmt
    is_procedure = bool(stmt.is_procedure)
    if not stmt.replace:
        pattern = (
            IdempotencyPattern.CREATE_PROCEDURE
            if is_procedure
            else IdempotencyPattern.CREATE_FUNCTION
        )
        matches.append(_make_match(pattern, ctx, sql))
        return
    name = _funcname_dotted(stmt.funcname)
    drop_set = drops.procedures if is_procedure else drops.functions
    if name and name in drop_set:
        return  # User chose the explicit DROP+CREATE pattern; no shape-risk note.
    shape_risk = (
        IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK
        if is_procedure
        else IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK
    )
    matches.append(_make_match(shape_risk, ctx, sql, severity="info"))


def _visit_view_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], drops: _PairDrops
) -> None:
    """``CREATE [OR REPLACE] VIEW …`` — both shapes pair-suppressible."""
    name = _qualified_name(ctx.stmt.view)
    if ctx.stmt.replace:
        if name and name in drops.views:
            return
        matches.append(
            _make_match(
                IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK,
                ctx,
                sql,
                severity="info",
            )
        )
        return
    if name and name in drops.views:
        return  # DROP VIEW IF EXISTS + CREATE VIEW is the canonical idempotent pattern.
    matches.append(_make_match(IdempotencyPattern.CREATE_VIEW, ctx, sql))


# ---------------------------------------------------------------------------
# ALTER visitors
# ---------------------------------------------------------------------------


def _visit_alter_table_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], drops: _PairDrops
) -> None:
    """``ALTER {TABLE | VIEW | MATERIALIZED VIEW} …`` — dispatch each cmd.

    ``AlterTableStmt`` is one node per source statement, but holds a
    tuple of :class:`AlterTableCmd` (one per comma-separated clause).
    Walking the tuple is what closes the *multi-clause ALTER* gap from
    issue #122 — each clause produces its own match.
    """
    objtype = ctx.stmt.objtype
    for cmd in ctx.stmt.cmds or ():
        subtype_value = _enum_value(cmd.subtype)
        if subtype_value == _AT_ADD_COLUMN:
            # ``ADD COLUMN`` is only meaningful for tables. Skip if
            # ``IF NOT EXISTS`` is present (``cmd.missing_ok``).
            if objtype != _OBJECT_TABLE or cmd.missing_ok:
                continue
            matches.append(_make_match(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN, ctx, sql))
        elif subtype_value == _AT_ADD_CONSTRAINT:
            if objtype != _OBJECT_TABLE:
                continue
            constraint = cmd.def_
            if constraint is None:
                continue
            contype_value = _enum_value(constraint.contype)
            pattern = _CONSTRAINT_PATTERNS.get(contype_value or -1)
            if pattern is None:
                continue
            conname = getattr(constraint, "conname", None)
            if conname and str(conname).lower() in drops.constraints:
                # Paired with an earlier DROP CONSTRAINT IF EXISTS — idempotent.
                continue
            matches.append(_make_match(pattern, ctx, sql))
        elif subtype_value == _AT_CHANGE_OWNER:
            pattern = _OWNER_PATTERNS.get(objtype)
            if pattern is None:
                continue
            matches.append(_make_match(pattern, ctx, sql))


def _visit_rename_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    """``ALTER TABLE … RENAME [COLUMN] … TO …`` — column-rename only."""
    stmt = ctx.stmt
    if _enum_value(stmt.renameType) != _OBJECT_COLUMN:
        return
    if _enum_value(stmt.relationType) != _OBJECT_TABLE:
        return
    matches.append(_make_match(IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN, ctx, sql))


# ---------------------------------------------------------------------------
# DROP visitor
# ---------------------------------------------------------------------------


def _visit_drop_stmt(
    ctx: _StatementContext, sql: str, matches: list[PatternMatch], _drops: _PairDrops
) -> None:
    """``DROP <object> [IF EXISTS] [CONCURRENTLY] …``.

    ``DropStmt.missing_ok`` covers ``IF EXISTS`` for every object kind,
    including ``DROP INDEX CONCURRENTLY IF EXISTS`` — no separate code
    path needed.
    """
    if ctx.stmt.missing_ok:
        return
    pattern = _DROP_PATTERNS.get(_enum_value(ctx.stmt.removeType) or -1)
    if pattern is None:
        return
    matches.append(_make_match(pattern, ctx, sql))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_Visitor = Callable[[_StatementContext, str, list["PatternMatch"], _PairDrops], None]


_VISITORS: dict[str, _Visitor] = {
    "CreateStmt": _visit_create_stmt,
    "IndexStmt": _visit_index_stmt,
    "CreateSchemaStmt": _visit_create_schema_stmt,
    "CreateEnumStmt": _visit_create_enum_stmt,
    "CreateExtensionStmt": _visit_create_extension_stmt,
    "CreateSeqStmt": _visit_create_seq_stmt,
    "CreateFunctionStmt": _visit_create_function_stmt,
    "ViewStmt": _visit_view_stmt,
    "AlterTableStmt": _visit_alter_table_stmt,
    "RenameStmt": _visit_rename_stmt,
    "DropStmt": _visit_drop_stmt,
}


def _detect_via_ast(sql: str) -> list[PatternMatch]:
    """Detect non-idempotent SQL patterns using pglast's AST.

    Raises:
        pglast.parser.ParseError: when the SQL is not valid PostgreSQL.
            The dispatcher in :mod:`patterns` catches this and falls
            through to the regex backend.
    """
    import pglast  # noqa: PLC0415 — only imported when this backend is selected

    statements = _iter_statements(sql, pglast)
    drops = _collect_pair_drops(statements)
    matches: list[PatternMatch] = []
    for ctx in statements:
        visitor = _VISITORS.get(type(ctx.stmt).__name__)
        if visitor is not None:
            visitor(ctx, sql, matches, drops)
    return matches


__all__ = ["is_pglast_available"]
