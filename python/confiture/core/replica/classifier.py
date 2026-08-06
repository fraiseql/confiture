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
from typing import Any

from confiture.core._pglast_enums import enums_are_usable
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.idempotency.ast_detector import is_pglast_available
from confiture.core.sql_statements import split_statements
from confiture.core.type_lattice import canonical_type

# pglast availability, resolved at import (tests monkeypatch this to force the
# regex backend, mirroring the idempotency CONFITURE_IDEMPOTENCY_FORCE_REGEX
# escape hatch).
_HAS_PGLAST = is_pglast_available()
_FORCE_REGEX_ENV = "CONFITURE_REPLICA_FORCE_REGEX"

# Resolved BY NAME, never by literal ordinal (#192): PG18 renumbered
# AlterTableType, so pglast 8 shifted every member at index >= 13 down by one
# and the hardcoded comparisons below started missing silently.
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")
_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
_AT_ALTER_COLUMN_TYPE = _pg_member("AlterTableType", "AT_AlterColumnType")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_DROP_CONSTRAINT = _pg_member("AlterTableType", "AT_DropConstraint")
_AT_CHANGE_OWNER = _pg_member("AlterTableType", "AT_ChangeOwner")
_AT_COLUMN_DEFAULT = _pg_member("AlterTableType", "AT_ColumnDefault")
_AT_SET_NOT_NULL = _pg_member("AlterTableType", "AT_SetNotNull")
_AT_DROP_NOT_NULL = _pg_member("AlterTableType", "AT_DropNotNull")

# ALTER TABLE subcommands that change nothing an N-1 reader can observe.
_AT_BENIGN = {
    _AT_DROP_CONSTRAINT: "drop_constraint",
    _AT_CHANGE_OWNER: "change_owner",
    _AT_COLUMN_DEFAULT: "column_default",
    _AT_DROP_NOT_NULL: "drop_not_null",
}

# DropStmt.removeType → the object noun, for objects whose removal breaks a
# reader still on the old version.
_DROP_UNSAFE_KIND = {
    _pg_member("ObjectType", "OBJECT_VIEW"): "view",
    _pg_member("ObjectType", "OBJECT_MATVIEW"): "materialized view",
    _pg_member("ObjectType", "OBJECT_SEQUENCE"): "sequence",
    _pg_member("ObjectType", "OBJECT_SCHEMA"): "schema",
    _pg_member("ObjectType", "OBJECT_TYPE"): "type",
    _pg_member("ObjectType", "OBJECT_DOMAIN"): "domain",
    _pg_member("ObjectType", "OBJECT_FUNCTION"): "function",
    _pg_member("ObjectType", "OBJECT_PROCEDURE"): "procedure",
    _pg_member("ObjectType", "OBJECT_EXTENSION"): "extension",
}

# Dropping these changes query *plans* or side effects, never whether an N-1
# reader's SQL still resolves.
_DROP_BENIGN_KIND = {
    _pg_member("ObjectType", "OBJECT_INDEX"): "drop_index",
    _pg_member("ObjectType", "OBJECT_TRIGGER"): "drop_trigger",
    _pg_member("ObjectType", "OBJECT_POLICY"): "drop_policy",
    _pg_member("ObjectType", "OBJECT_RULE"): "drop_rule",
}

_OBJECT_TABLE = _pg_member("ObjectType", "OBJECT_TABLE")

# Statement types that change neither schema nor data, so they produce no
# operation at all — emitting one would make every migration with a `BEGIN;`
# report as unclassified.
_AST_SKIP = frozenset(
    {
        "TransactionStmt",
        "VariableSetStmt",
        "VariableShowStmt",
        "CheckPointStmt",
        "DiscardStmt",
        "LockStmt",
        "VacuumStmt",
        "ConstraintsSetStmt",
        "NotifyStmt",
        "ListenStmt",
        "UnlistenStmt",
    }
)

# Node types that are additive or reader-invisible, mapped to the kind recorded
# on the resulting :class:`Benign` operation.
_AST_BENIGN = {
    "CreateStmt": "create_table",
    "CreateTableAsStmt": "create_table_as",
    "CreateSeqStmt": "create_sequence",
    "AlterSeqStmt": "alter_sequence",
    "CreateSchemaStmt": "create_schema",
    "CreateExtensionStmt": "create_extension",
    "CreateEnumStmt": "create_type",
    "CreateRangeStmt": "create_type",
    "CompositeTypeStmt": "create_type",
    "CreateDomainStmt": "create_domain",
    "CreateTrigStmt": "create_trigger",
    "CreatePolicyStmt": "create_policy",
    "RuleStmt": "create_rule",
    "CommentStmt": "comment",
    "AlterOwnerStmt": "change_owner",
    "AlterDefaultPrivilegesStmt": "alter_default_privileges",
    "RefreshMatViewStmt": "refresh_materialized_view",
    "ClusterStmt": "cluster",
    "ReindexStmt": "reindex",
    "InsertStmt": "insert",
    "UpdateStmt": "update",
    "DeleteStmt": "delete",
    # A bare SELECT reads; it cannot change what an N-1 reader resolves. DDL run
    # inside a function it calls is invisible here — the same blind spot that
    # makes a `.py` migration UNCLASSIFIED, and not one a statement classifier
    # can close. `SELECT … INTO` creates a table, which is additive either way.
    "SelectStmt": "select",
}

_CONSTR_NOTNULL = _pg_member("ConstrType", "CONSTR_NOTNULL")
_CONSTR_DEFAULT = _pg_member("ConstrType", "CONSTR_DEFAULT")
_CONSTR_KIND = {
    _pg_member("ConstrType", "CONSTR_CHECK"): "check",
    _pg_member("ConstrType", "CONSTR_PRIMARY"): "primary_key",
    _pg_member("ConstrType", "CONSTR_UNIQUE"): "unique",
    _pg_member("ConstrType", "CONSTR_FOREIGN"): "foreign_key",
}

_RENAME_COLUMN = _pg_member("ObjectType", "OBJECT_COLUMN")


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

    new_type: str | None = None
    """The target type, as written in the statement."""

    old_type: str | None = None
    """The current type. **Never present from SQL** — ``ALTER TABLE … ALTER COLUMN
    … TYPE`` states only the target — so it is filled in from the differ or a live
    database, and stays ``None`` otherwise. Without it the direction is unknown,
    which is why the risk tier for a type change is absent by default."""


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
class DropTable(DdlOperation):
    """``DROP TABLE`` — readers on the old version still SELECT from it."""


@dataclass(frozen=True)
class DropObject(DdlOperation):
    """``DROP`` of a non-table object an N-1 reader may still reference."""

    kind: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class ReplaceObject(DdlOperation):
    """``CREATE OR REPLACE`` — the new body may or may not stay reader-compatible."""

    kind: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class Truncate(DdlOperation):
    """``TRUNCATE`` — the rows readers expect are gone."""


@dataclass(frozen=True)
class Revoke(DdlOperation):
    """``REVOKE`` — a privilege an N-1 reader still relies on may disappear."""


@dataclass(frozen=True)
class SetNotNull(DdlOperation):
    """``ALTER COLUMN … SET NOT NULL`` — an N-1 writer inserting NULL starts failing."""

    column: str | None = None


@dataclass(frozen=True)
class RenameObject(DdlOperation):
    """``RENAME TO`` / ``RENAME VALUE`` — the name an N-1 reader uses disappears."""

    kind: str | None = None
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True)
class AddEnumValue(DdlOperation):
    """``ALTER TYPE … ADD VALUE`` — additive; non-transactional below PG 12."""

    type_name: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class Benign(DdlOperation):
    """An operation with no replica forward-compatibility impact.

    Carried as a typed operation rather than dropped: the difference between
    "classified, and it is fine" and "never looked" is the whole of #206.
    """

    kind: str | None = None


@dataclass(frozen=True)
class Other(DdlOperation):
    """An operation the classifier could not map (e.g. dynamic SQL).

    The fallback for every unrecognised statement, in both backends. It routes to
    ``PFLIGHT_REPLICA_UNCLASSIFIED`` — a warning, so opacity never hard-blocks —
    and flips ``window_safe`` to false, which is the fail-safe direction.
    """

    reason: str | None = None


def _use_ast() -> bool:
    if os.environ.get(_FORCE_REGEX_ENV, "").lower() in {"1", "true", "yes"}:
        return False
    # A half-resolvable enum surface (upstream removed a member we walk) means
    # the elif chains below would silently drop operations — the #192 failure
    # mode. Degrade to regex rather than emit a false window_safe verdict.
    return _HAS_PGLAST and enums_are_usable()


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
            elif name not in _AST_SKIP:
                ops.extend(self._ast_wider(node, name))
        return ops

    def _ast_wider(self, node: object, name: str) -> list[DdlOperation]:
        """Classify a statement outside the original seven-operation matrix (#206).

        Everything that reaches here either maps to a typed operation or becomes
        :class:`Other`. Returning an empty list is what made ``DROP TABLE``
        certify as window-safe, so this method never does.
        """
        if name == "DropStmt":
            return _ast_drop(node)
        if name == "TruncateStmt":
            return [
                Truncate(table=_relname(relation))
                for relation in getattr(node, "relations", None) or ()
            ] or [Truncate()]
        if name == "GrantStmt":
            if getattr(node, "is_grant", True):
                return [Benign(kind="grant")]
            return [Revoke(table=_first_relname(getattr(node, "objects", None)))]
        if name == "AlterEnumStmt":
            return [_ast_alter_enum(node)]
        if name == "ViewStmt":
            return [_replace_or_benign(node, "view", _relname(getattr(node, "view", None)))]
        if name == "CreateFunctionStmt":
            noun = "procedure" if getattr(node, "is_procedure", False) else "function"
            return [_replace_or_benign(node, noun, _name_parts(getattr(node, "funcname", None)))]
        benign = _AST_BENIGN.get(name)
        if benign is not None:
            return [Benign(table=_relname(getattr(node, "relation", None)), kind=benign)]
        return [Other(reason=_readable_node(name))]

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
                ops.append(
                    ChangeColumnType(
                        table=table,
                        column=cmd.name,
                        new_type=canonical_type(_type_name(getattr(cmd.def_, "typeName", None))),
                    )
                )
            elif subtype == _AT_ADD_CONSTRAINT:
                constraint = cmd.def_
                kind = _CONSTR_KIND.get(_enum_int(getattr(constraint, "contype", None)) or -1)
                not_valid = bool(getattr(constraint, "skip_validation", False))
                ops.append(AddConstraint(table=table, kind=kind, not_valid=not_valid))
            elif subtype == _AT_SET_NOT_NULL:
                ops.append(SetNotNull(table=table, column=cmd.name))
            elif subtype in _AT_BENIGN:
                ops.append(Benign(table=table, kind=_AT_BENIGN[subtype]))
            else:
                ops.append(Other(table=table, reason="ALTER TABLE subcommand"))
        return ops

    def _ast_rename(self, node: object) -> DdlOperation | None:
        if _enum_int(getattr(node, "renameType", None)) == _RENAME_COLUMN:
            return RenameColumn(
                table=_relname(getattr(node, "relation", None)),
                old=getattr(node, "subname", None),
                new=getattr(node, "newname", None),
            )
        # Renaming any other object still retires the name an N-1 reader uses.
        return RenameObject(
            table=_relname(getattr(node, "relation", None)),
            kind="object",
            old=getattr(node, "subname", None),
            new=getattr(node, "newname", None),
        )

    # ------------------------------------------------------------------ #
    # regex backend (fallback / parity)
    # ------------------------------------------------------------------ #

    def _classify_regex(self, sql: str) -> list[DdlOperation]:
        ops: list[DdlOperation] = []
        for stmt in _split_statements(sql):
            if not stmt.strip() or _RE_SKIP.match(stmt.strip()):
                continue
            op = self._regex_one(stmt)
            ops.append(op if op is not None else self._regex_wider(stmt))
        return ops

    def _regex_wider(self, stmt: str) -> DdlOperation:
        """The regex twin of :meth:`_ast_wider` — never returns ``None`` (#206)."""
        s = stmt.strip()

        m = _RE_DROP.match(s)
        if m:
            word = re.sub(r"\s+", " ", m.group("what")).lower()
            name = _norm(_split_names(m.group("names"))[0])
            if word == "table":
                return DropTable(table=name)
            if word in _DROP_UNSAFE_WORDS:
                return DropObject(table=name, kind=word, name=name)
            return Benign(table=name, kind=f"drop_{word.replace(' ', '_')}")
        m = _RE_TRUNCATE.match(s)
        if m:
            return Truncate(table=_norm(_split_names(m.group("names"))[0]))
        m = _RE_REVOKE.match(s)
        if m:
            target = _RE_GRANT_TARGET.search(s)
            return Revoke(table=_norm(target.group("obj")) if target else None)
        m = _RE_ALTER_ENUM.match(s)
        if m:
            type_name = _norm(m.group("type"))
            if m.group("verb").lower() == "add":
                return AddEnumValue(table=type_name, type_name=type_name, value=m.group("val"))
            return RenameObject(table=type_name, kind="enum value", new=m.group("val"))
        m = _RE_ALTER_TABLE_SUB.match(s)
        if m:
            return self._regex_alter_sub(_norm(m.group("table")), m.group("rest").strip())
        m = _RE_REPLACE_OBJECT.match(s)
        if m:
            noun = re.sub(r"\s+", " ", m.group("what")).lower()
            return ReplaceObject(
                table=_norm(m.group("name")), kind=noun, name=_norm(m.group("name"))
            )
        for pattern, kind in _RE_BENIGN:
            m = pattern.match(s)
            if m:
                return Benign(table=_norm(m.groupdict().get("name")), kind=kind)
        return Other(reason=_command_head(s))

    def _regex_alter_sub(self, table: str | None, rest: str) -> DdlOperation:
        """An ALTER TABLE subcommand the matrix patterns did not match."""
        low = rest.lower()
        if _RE_AT_SET_NOT_NULL.match(rest):
            m = _RE_AT_ALTER_COLUMN.match(rest)
            return SetNotNull(table=table, column=_norm(m.group("col")) if m else None)
        if _RE_AT_RENAME_TO.match(rest):
            return RenameObject(table=table, kind="object", new=_norm(rest.split()[-1]))
        for pattern, kind in _RE_AT_BENIGN:
            if pattern.match(rest):
                return Benign(table=table, kind=kind)
        if low.startswith("owner to"):
            return Benign(table=table, kind="change_owner")
        return Other(table=table, reason="ALTER TABLE subcommand")

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
            return ChangeColumnType(
                table=_norm(m.group("table")),
                column=_norm(m.group("col")),
                new_type=canonical_type(_clean_type(m.group("newtype"))),
            )
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


def _readable_node(node_name: str) -> str:
    """`CreateStatsStmt` → `create stats statement`, for the finding's reason."""
    words = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", node_name)
    return " ".join(word.lower() for word in words) or node_name


def _name_parts(raw: Any) -> str | None:
    """Join a pglast list of ``String`` name parts into a dotted identifier."""
    parts = [str(getattr(part, "sval", part)) for part in raw or ()]
    return ".".join(part.lower() for part in parts if part) or None


def _clean_type(raw: str | None) -> str | None:
    """Trim a type captured from SQL, dropping a trailing `USING`/`NOT NULL` tail."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip().rstrip(",;")
    text = re.split(r"\b(?:USING|COLLATE|NOT|NULL|DEFAULT)\b", text, flags=re.IGNORECASE)[0]
    return text.strip() or None


def _type_name(type_node: Any) -> str | None:
    """Render a pglast ``TypeName`` back to ``varchar(50)`` / ``numeric(10,2)``.

    The ``pg_catalog`` qualifier the parser adds is dropped; the internal spelling
    (``int8``) is left alone, since :mod:`confiture.core.type_lattice` aliases it.
    """
    if type_node is None:
        return None
    parts = [str(getattr(part, "sval", part)) for part in getattr(type_node, "names", None) or ()]
    names = [part for part in parts if part and part != "pg_catalog"]
    if not names:
        return None
    name = ".".join(names)
    mods = [
        str(ival)
        for ival in (
            getattr(getattr(mod, "val", None), "ival", None)
            for mod in getattr(type_node, "typmods", None) or ()
        )
        if ival is not None
    ]
    return f"{name}({', '.join(mods)})" if mods else name


def _first_relname(objects: Any) -> str | None:
    for obj in objects or ():
        name = _relname(obj)
        if name:
            return name
    return None


def _ast_drop(node: object) -> list[DdlOperation]:
    """One operation per dropped object, never an empty list."""
    remove_type = _enum_int(getattr(node, "removeType", None))
    names = [_object_name(obj) for obj in getattr(node, "objects", None) or ()] or [None]
    if remove_type == _OBJECT_TABLE:
        return [DropTable(table=name) for name in names]
    if remove_type in _DROP_UNSAFE_KIND:
        kind = _DROP_UNSAFE_KIND[remove_type]
        return [DropObject(table=name, kind=kind, name=name) for name in names]
    if remove_type in _DROP_BENIGN_KIND:
        kind = _DROP_BENIGN_KIND[remove_type]
        return [Benign(table=name, kind=kind) for name in names]
    return [Other(table=name, reason="DROP of an unclassified object type") for name in names]


def _object_name(obj: object) -> str | None:
    """Flatten one ``DropStmt.objects`` element into a dotted identifier."""
    inner = getattr(obj, "objname", obj)  # ObjectWithArgs → its name
    sval = getattr(inner, "sval", None)
    if sval is not None:
        return str(sval).lower()
    if isinstance(inner, (list, tuple)):
        return _name_parts(inner)
    return _norm(str(inner)) if inner is not None else None


def _ast_alter_enum(node: object) -> DdlOperation:
    """`ADD VALUE` is additive; `RENAME VALUE` retires a value readers match on."""
    type_name = _name_parts(getattr(node, "typeName", None))
    old = getattr(node, "oldVal", None)
    new = getattr(node, "newVal", None)
    if old is None:
        return AddEnumValue(table=type_name, type_name=type_name, value=new)
    return RenameObject(table=type_name, kind="enum value", old=old, new=new)


def _replace_or_benign(node: object, noun: str, name: str | None) -> DdlOperation:
    """`CREATE OR REPLACE` is a body swap confiture cannot judge; plain CREATE is additive."""
    if bool(getattr(node, "replace", False)):
        return ReplaceObject(table=name, kind=noun, name=name)
    return Benign(table=name, kind=f"create_{noun.replace(' ', '_')}")


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
    """Top-level split, shared with ``core/change_set.py``.

    Must stay dollar-quote aware: a naive ``split(";")`` shreds a ``CREATE
    FUNCTION`` body, and since #206 each fragment would surface as a spurious
    UNCLASSIFIED finding rather than being silently dropped.
    """
    return split_statements(sql)


_RE_ADD_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="table")
    + r"\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    + _IDENT.format(name="col")
    + r"\s+(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_DROP_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="table")
    + r"\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="col"),
    re.IGNORECASE,
)
_RE_RENAME_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="table")
    + r"\s+RENAME\s+COLUMN\s+"
    + _IDENT.format(name="old")
    + r"\s+TO\s+"
    + _IDENT.format(name="new"),
    re.IGNORECASE,
)
_RE_ALTER_TYPE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="table")
    + r"\s+ALTER\s+COLUMN\s+"
    + _IDENT.format(name="col")
    + r"\s+(?:SET\s+DATA\s+)?TYPE\s+(?P<newtype>[\w ]+(?:\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)",
    re.IGNORECASE,
)
_RE_ADD_CONSTRAINT = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    + _IDENT.format(name="table")
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

# --------------------------------------------------------------------------- #
# Widened regex surface (#206) — the twin of the _ast_wider tables above.
# --------------------------------------------------------------------------- #

_ANY = r'(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\.(?:"[^"]+"|[A-Za-z_][\w$]*))*'

# Statement heads that change neither schema nor data (the regex twin of _AST_SKIP).
_RE_SKIP = re.compile(
    r"^(?:BEGIN|COMMIT|END|ROLLBACK|START\s+TRANSACTION|SAVEPOINT|RELEASE\b|SET\b|RESET\b"
    r"|SHOW\b|CHECKPOINT|DISCARD\b|LOCK\b|VACUUM\b|ANALYZE\b|ANALYSE\b|LISTEN\b|NOTIFY\b"
    r"|UNLISTEN\b)",
    re.IGNORECASE,
)

_RE_DROP = re.compile(
    r"^DROP\s+(?P<what>TABLE|INDEX|MATERIALIZED\s+VIEW|VIEW|SEQUENCE|SCHEMA|TYPE|DOMAIN"
    r"|FUNCTION|PROCEDURE|TRIGGER|POLICY|RULE|EXTENSION)\s+"
    r"(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?(?P<names>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# Dropping any of these retires a name an N-1 reader may still resolve.
_DROP_UNSAFE_WORDS = frozenset(
    {
        "view",
        "materialized view",
        "sequence",
        "schema",
        "type",
        "domain",
        "function",
        "procedure",
        "extension",
    }
)

_RE_TRUNCATE = re.compile(
    r"^TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?(?P<names>.+)$", re.IGNORECASE | re.DOTALL
)
_RE_REVOKE = re.compile(r"^REVOKE\b", re.IGNORECASE)
_RE_GRANT_TARGET = re.compile(
    rf"\bON\s+(?:TABLE\s+|SEQUENCE\s+|SCHEMA\s+)?(?P<obj>{_ANY})", re.IGNORECASE
)
_RE_ALTER_ENUM = re.compile(
    rf"^ALTER\s+TYPE\s+(?P<type>{_ANY})\s+(?P<verb>ADD|RENAME)\s+VALUE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?'(?P<val>[^']*)'",
    re.IGNORECASE,
)
_RE_ALTER_TABLE_SUB = re.compile(
    rf"^ALTER\s+(?:TABLE|MATERIALIZED\s+VIEW|VIEW|FOREIGN\s+TABLE)\s+(?:IF\s+EXISTS\s+)?"
    rf"(?:ONLY\s+)?(?P<table>{_ANY})\s+(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_REPLACE_OBJECT = re.compile(
    rf"^CREATE\s+OR\s+REPLACE\s+(?P<what>VIEW|MATERIALIZED\s+VIEW|FUNCTION|PROCEDURE)\s+"
    rf"(?P<name>{_ANY})",
    re.IGNORECASE,
)

_RE_AT_SET_NOT_NULL = re.compile(
    rf"^ALTER\s+(?:COLUMN\s+)?{_ANY}\s+SET\s+NOT\s+NULL", re.IGNORECASE
)
_RE_AT_ALTER_COLUMN = re.compile(rf"^ALTER\s+(?:COLUMN\s+)?(?P<col>{_ANY})", re.IGNORECASE)
_RE_AT_RENAME_TO = re.compile(r"^RENAME\s+TO\b", re.IGNORECASE)
_RE_AT_BENIGN: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"^ALTER\s+(?:COLUMN\s+)?{_ANY}\s+DROP\s+NOT\s+NULL", re.IGNORECASE),
        "drop_not_null",
    ),
    (
        re.compile(rf"^ALTER\s+(?:COLUMN\s+)?{_ANY}\s+SET\s+DEFAULT", re.IGNORECASE),
        "column_default",
    ),
    (
        re.compile(rf"^ALTER\s+(?:COLUMN\s+)?{_ANY}\s+DROP\s+DEFAULT", re.IGNORECASE),
        "column_default",
    ),
    (re.compile(r"^DROP\s+CONSTRAINT\b", re.IGNORECASE), "drop_constraint"),
)

# `head → kind` for statements that are additive or invisible to an N-1 reader.
_RE_BENIGN: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^CREATE\s+MATERIALIZED\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ANY})",
            re.IGNORECASE,
        ),
        "create_materialized_view",
    ),
    (re.compile(rf"^CREATE\s+(?:\w+\s+)*?VIEW\s+(?P<name>{_ANY})", re.IGNORECASE), "create_view"),
    (re.compile(rf"^CREATE\s+FUNCTION\s+(?P<name>{_ANY})", re.IGNORECASE), "create_function"),
    (re.compile(rf"^CREATE\s+PROCEDURE\s+(?P<name>{_ANY})", re.IGNORECASE), "create_procedure"),
    (
        re.compile(rf"^CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ANY})", re.IGNORECASE),
        "create_schema",
    ),
    (
        re.compile(
            rf"^CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ANY})", re.IGNORECASE
        ),
        "create_sequence",
    ),
    (re.compile(rf"^CREATE\s+TYPE\s+(?P<name>{_ANY})", re.IGNORECASE), "create_type"),
    (re.compile(rf"^CREATE\s+DOMAIN\s+(?P<name>{_ANY})", re.IGNORECASE), "create_domain"),
    (
        re.compile(
            rf"^CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ANY})", re.IGNORECASE
        ),
        "create_extension",
    ),
    (
        re.compile(rf"^CREATE\s+(?:CONSTRAINT\s+)?TRIGGER\s+(?P<name>{_ANY})", re.IGNORECASE),
        "create_trigger",
    ),
    (re.compile(rf"^CREATE\s+POLICY\s+(?P<name>{_ANY})", re.IGNORECASE), "create_policy"),
    (re.compile(rf"^CREATE\s+RULE\s+(?P<name>{_ANY})", re.IGNORECASE), "create_rule"),
    (re.compile(r"^GRANT\b", re.IGNORECASE), "grant"),
    (re.compile(rf"^COMMENT\s+ON\s+(?:\w+\s+)+?(?P<name>{_ANY})", re.IGNORECASE), "comment"),
    (re.compile(rf"^INSERT\s+INTO\s+(?P<name>{_ANY})", re.IGNORECASE), "insert"),
    (re.compile(rf"^UPDATE\s+(?:ONLY\s+)?(?P<name>{_ANY})", re.IGNORECASE), "update"),
    (re.compile(rf"^DELETE\s+FROM\s+(?:ONLY\s+)?(?P<name>{_ANY})", re.IGNORECASE), "delete"),
    (
        re.compile(
            rf"^REFRESH\s+MATERIALIZED\s+VIEW\s+(?:CONCURRENTLY\s+)?(?P<name>{_ANY})", re.IGNORECASE
        ),
        "refresh_materialized_view",
    ),
    (re.compile(rf"^CLUSTER\s+(?P<name>{_ANY})", re.IGNORECASE), "cluster"),
    (re.compile(rf"^REINDEX\s+(?:\w+\s+)?(?P<name>{_ANY})", re.IGNORECASE), "reindex"),
    (
        re.compile(rf"^ALTER\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?(?P<name>{_ANY})", re.IGNORECASE),
        "alter_sequence",
    ),
    (re.compile(r"^ALTER\s+DEFAULT\s+PRIVILEGES\b", re.IGNORECASE), "alter_default_privileges"),
    (re.compile(r"^(?:SELECT|TABLE|VALUES|WITH)\b", re.IGNORECASE), "select"),
    (
        re.compile(
            rf"^CREATE\s+(?:GLOBAL\s+|LOCAL\s+)?(?:UNLOGGED\s+|TEMPORARY\s+|TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ANY})\s+AS\b",
            re.IGNORECASE,
        ),
        "create_table_as",
    ),
)


def _split_names(raw: str) -> list[str]:
    """Split `a, b.c` into names, dropping any argument list or trailing clause."""
    names = []
    for chunk in re.sub(
        r"\b(?:CASCADE|RESTRICT)\b.*$", "", raw, flags=re.IGNORECASE | re.DOTALL
    ).split(","):
        name = chunk.strip().split("(")[0].strip()
        name = name.split()[0] if name.split() else ""
        if name:
            names.append(name)
    return names or [""]


def _command_head(statement: str, *, words: int = 4) -> str:
    """The leading keywords of a statement, with every literal stripped.

    The reason reaches an operator, and an unclassified statement is exactly the
    kind that might carry a credential (``CREATE USER … PASSWORD 'x'``). Only bare
    word tokens survive.
    """
    tokens: list[str] = []
    for token in statement.split():
        if not re.fullmatch(r"[A-Za-z_][\w$.]*", token):
            break
        tokens.append(token.lower())
        if len(tokens) >= words:
            break
    return " ".join(tokens) or "statement"
