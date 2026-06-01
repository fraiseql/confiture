"""Classify migration DDL into replica-safety-relevant operations (issue #139).

Reuses the two-tier parsing strategy of ``core/idempotency/`` — pglast primary,
regex fallback — adding no new SQL parser. The output carries exactly the
attributes the replica-safety matrix needs (nullability, DEFAULT presence,
CONCURRENTLY, constraint kind/validation, type change).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from confiture.core.idempotency.ast_detector import is_pglast_available

# pglast availability, resolved at import (tests monkeypatch this to force the
# regex backend, mirroring the idempotency CONFITURE_IDEMPOTENCY_FORCE_REGEX
# escape hatch).
_HAS_PGLAST = is_pglast_available()
_FORCE_REGEX_ENV = "CONFITURE_REPLICA_FORCE_REGEX"

# AlterTableType subtype values (pglast.enums.parsenodes.AlterTableType).
_AT_ADD_COLUMN = 0
_AT_DROP_COLUMN = 14
_AT_ALTER_COLUMN_TYPE = 25
_AT_ADD_CONSTRAINT = 17

# ConstrType values (pglast.enums.parsenodes.ConstrType).
_CONSTR_NOTNULL = 1
_CONSTR_DEFAULT = 2
_CONSTR_KIND = {5: "check", 6: "primary_key", 7: "unique", 9: "foreign_key"}

_RENAME_COLUMN = 6  # ObjectType.OBJECT_COLUMN


# ---------------------------------------------------------------------------
# Typed operations (the replica-safety matrix domain)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DdlOperation:
    """Base for a classified DDL operation. Attributes shared by all variants."""

    table: str | None = None
    migration_version: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class AddColumn(DdlOperation):
    column: str | None = None
    nullable: bool = True
    has_default: bool = False


@dataclass(frozen=True)
class DropColumn(DdlOperation):
    column: str | None = None


@dataclass(frozen=True)
class RenameColumn(DdlOperation):
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True)
class ChangeColumnType(DdlOperation):
    column: str | None = None


@dataclass(frozen=True)
class AddConstraint(DdlOperation):
    kind: str | None = None
    not_valid: bool = False


@dataclass(frozen=True)
class CreateIndex(DdlOperation):
    concurrently: bool = False


@dataclass(frozen=True)
class CreateTable(DdlOperation):
    pass


@dataclass(frozen=True)
class Other(DdlOperation):
    """An operation the classifier could not map (e.g. dynamic SQL)."""

    reason: str | None = None


def _use_ast() -> bool:
    if os.environ.get(_FORCE_REGEX_ENV, "").lower() in {"1", "true", "yes"}:
        return False
    return _HAS_PGLAST


class OperationClassifier:
    """Parse migration SQL into a list of typed :class:`DdlOperation`."""

    def classify(self, sql: str) -> list[DdlOperation]:
        """Return the ordered DDL operations in ``sql``.

        Uses pglast when available, else a regex fallback; both backends are
        parity-tested for the supported operations.
        """
        if _use_ast():
            try:
                return self._classify_ast(sql)
            except Exception:  # noqa: BLE001 — fall back to regex on any parse hiccup
                return self._classify_regex(sql)
        return self._classify_regex(sql)

    # ------------------------------------------------------------------ #
    # pglast backend
    # ------------------------------------------------------------------ #

    def _classify_ast(self, sql: str) -> list[DdlOperation]:
        import pglast  # noqa: PLC0415

        ops: list[DdlOperation] = []
        for raw in pglast.parse_sql(sql):
            node = raw.stmt
            name = type(node).__name__
            if name == "AlterTableStmt":
                ops.extend(self._ast_alter_table(node))
            elif name == "RenameStmt":
                op = self._ast_rename(node)
                if op is not None:
                    ops.append(op)
            elif name == "IndexStmt":
                ops.append(
                    CreateIndex(
                        table=_relname(node.relation),
                        concurrently=bool(node.concurrent),
                    )
                )
            elif name == "CreateStmt":
                ops.append(CreateTable(table=_relname(node.relation)))
        return ops

    def _ast_alter_table(self, node: object) -> list[DdlOperation]:
        table = _relname(getattr(node, "relation", None))
        ops: list[DdlOperation] = []
        for cmd in getattr(node, "cmds", None) or ():
            subtype = _enum_int(cmd.subtype)
            if subtype == _AT_ADD_COLUMN:
                coldef = cmd.def_
                column = getattr(coldef, "colname", None)
                nullable = not _column_is_not_null(coldef)
                has_default = _column_has_default(coldef)
                ops.append(
                    AddColumn(
                        table=table, column=column, nullable=nullable, has_default=has_default
                    )
                )
            elif subtype == _AT_DROP_COLUMN:
                ops.append(DropColumn(table=table, column=cmd.name))
            elif subtype == _AT_ALTER_COLUMN_TYPE:
                ops.append(ChangeColumnType(table=table, column=cmd.name))
            elif subtype == _AT_ADD_CONSTRAINT:
                constraint = cmd.def_
                kind = _CONSTR_KIND.get(_enum_int(getattr(constraint, "contype", None)) or -1)
                not_valid = bool(getattr(constraint, "skip_validation", False))
                ops.append(AddConstraint(table=table, kind=kind, not_valid=not_valid))
        return ops

    def _ast_rename(self, node: object) -> DdlOperation | None:
        if _enum_int(getattr(node, "renameType", None)) != _RENAME_COLUMN:
            return None
        return RenameColumn(
            table=_relname(getattr(node, "relation", None)),
            old=getattr(node, "subname", None),
            new=getattr(node, "newname", None),
        )

    # ------------------------------------------------------------------ #
    # regex backend (fallback / parity)
    # ------------------------------------------------------------------ #

    def _classify_regex(self, sql: str) -> list[DdlOperation]:
        ops: list[DdlOperation] = []
        for stmt in _split_statements(sql):
            op = self._regex_one(stmt)
            if op is not None:
                ops.append(op)
        return ops

    def _regex_one(self, stmt: str) -> DdlOperation | None:
        s = stmt.strip()
        if not s:
            return None
        lower = s.lower()

        m = _RE_ADD_COLUMN.match(s)
        if m:
            rest = m.group("rest").lower()
            return AddColumn(
                table=_norm(m.group("table")),
                column=_norm(m.group("col")),
                nullable="not null" not in rest,
                has_default="default" in rest,
            )
        m = _RE_DROP_COLUMN.match(s)
        if m:
            return DropColumn(table=_norm(m.group("table")), column=_norm(m.group("col")))
        m = _RE_RENAME_COLUMN.match(s)
        if m:
            return RenameColumn(
                table=_norm(m.group("table")),
                old=_norm(m.group("old")),
                new=_norm(m.group("new")),
            )
        m = _RE_ALTER_TYPE.match(s)
        if m:
            return ChangeColumnType(table=_norm(m.group("table")), column=_norm(m.group("col")))
        m = _RE_ADD_CONSTRAINT.match(s)
        if m:
            return AddConstraint(
                table=_norm(m.group("table")),
                kind=_constraint_kind_from_text(s),
                not_valid="not valid" in lower,
            )
        m = _RE_CREATE_INDEX.match(s)
        if m:
            return CreateIndex(
                table=_norm(m.group("table")),
                concurrently=m.group("conc") is not None,
            )
        m = _RE_CREATE_TABLE.match(s)
        if m:
            return CreateTable(table=_norm(m.group("table")))
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IDENT = r'(?P<{name}>"?[\w.]+"?)'


def _norm(ident: str | None) -> str | None:
    if ident is None:
        return None
    return ident.strip().strip('"').lower()


def _relname(relation: object) -> str | None:
    if relation is None:
        return None
    relname = getattr(relation, "relname", None)
    if not relname:
        return None
    schema = getattr(relation, "schemaname", None)
    return f"{str(schema).lower()}.{str(relname).lower()}" if schema else str(relname).lower()


def _enum_int(value: object) -> int | None:
    if value is None:
        return None
    inner = getattr(value, "value", value)
    try:
        return int(inner)
    except (TypeError, ValueError):
        return None


def _column_is_not_null(coldef: object) -> bool:
    if bool(getattr(coldef, "is_not_null", False)):
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if _enum_int(getattr(c, "contype", None)) == _CONSTR_NOTNULL:
            return True
    return False


def _column_has_default(coldef: object) -> bool:
    if getattr(coldef, "raw_default", None) is not None:
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if _enum_int(getattr(c, "contype", None)) == _CONSTR_DEFAULT:
            return True
    return False


def _constraint_kind_from_text(stmt: str) -> str | None:
    low = stmt.lower()
    if " check " in low or low.rstrip().endswith("check") or re.search(r"\bcheck\s*\(", low):
        return "check"
    if "primary key" in low:
        return "primary_key"
    if "unique" in low:
        return "unique"
    if "foreign key" in low or "references" in low:
        return "foreign_key"
    return None


def _split_statements(sql: str) -> list[str]:
    """Naive top-level split on ';' (regex fallback only)."""
    # Strip line comments to avoid splitting on ';' inside them.
    no_comments = re.sub(r"--[^\n]*", "", sql)
    return no_comments.split(";")


_RE_ADD_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="table")
    + r"\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _IDENT.format(name="col")
    + r"\s+(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_DROP_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="table")
    + r"\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="col"),
    re.IGNORECASE,
)
_RE_RENAME_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="table")
    + r"\s+RENAME\s+COLUMN\s+" + _IDENT.format(name="old")
    + r"\s+TO\s+" + _IDENT.format(name="new"),
    re.IGNORECASE,
)
_RE_ALTER_TYPE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="table")
    + r"\s+ALTER\s+COLUMN\s+" + _IDENT.format(name="col")
    + r"\s+(?:SET\s+DATA\s+)?TYPE\s+",
    re.IGNORECASE,
)
_RE_ADD_CONSTRAINT = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENT.format(name="table")
    + r"\s+ADD\s+CONSTRAINT\s+",
    re.IGNORECASE,
)
_RE_CREATE_INDEX = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<conc>CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+(?:ONLY\s+)?" + _IDENT.format(name="table"),
    re.IGNORECASE,
)
_RE_CREATE_TABLE = re.compile(
    r"^\s*CREATE\s+(?:UNLOGGED\s+|TEMPORARY\s+|TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    + _IDENT.format(name="table"),
    re.IGNORECASE,
)
