"""The preflight change set: what a migration set changes, and how risky it is (#197).

`migrate preflight --format json` carries a `change_set` object beside the
`window_safe` boolean. Each entry names one change and — when confiture can say
so honestly — its :class:`~confiture.core.risk_tier.RiskTier`. The wire shape,
the tier boundaries and the version rule are the ratified cross-repo contract
(fraisier-core#44, ``docs/proposals/migration-risk-contract.md``).

Three rules shape the code:

1. **Never drop a statement.** A statement this module cannot classify still
   produces an entry, with no ``tier``. Dropping it would shrink the set, and a
   shorter list of fully-classified changes reads as a *cleaner* plan than the
   truth — the one failure direction the contract exists to prevent.
2. **Never guess a tier.** ``ALTER COLUMN … TYPE`` is reversible when widening
   and irreversible when narrowing; preflight runs without a database and cannot
   tell, so it emits no tier rather than a confident wrong answer.
3. **This is not the replica classifier.** ``core/replica/classifier.py`` feeds
   the pinned ``window_safe`` verdict (#154) and reports only the operations in
   its safety matrix — an operation outside that matrix degrades to ``depends``
   there, which flips ``window_safe`` to false. Widening *it* to cover the
   change-set vocabulary would move that pinned field, so this module walks the
   statements itself. The cost is a second parse of files preflight has already
   read; the alternative was a false verdict on a cross-repo contract.

Both backends of the house two-tier strategy are implemented — pglast primary,
regex fallback — and are parity-tested statement by statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from confiture.core._pglast_enums import enums_are_usable
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.idempotency.ast_detector import is_pglast_available
from confiture.core.risk_tier import RiskTier, worst_tier

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "CONTRACT_VERSION",
    "ChangeEntry",
    "ChangeSet",
    "build_change_set",
    "classify_statements",
]

# Bumped only by a removal, a rename, or a change in what a tier *means*.
# Adding a field to an entry does not bump it.
CONTRACT_VERSION: Final = 1

_DEFAULT_SCHEMA: Final = "public"

_HAS_PGLAST = is_pglast_available()


# --------------------------------------------------------------------------- #
# Wire types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChangeEntry:
    """One change, as it crosses the adapter seam."""

    kind: str
    """Stable machine code, ``snake_case``. Rendered verbatim; never parsed for meaning."""

    object: str
    """Fully-qualified target — ``schema.table``, ``schema.table.column``, ``schema.table.index``."""

    migration: str | None = None
    """The migration **version prefix**, matching ``issues[].migration``."""

    tier: RiskTier | None = None
    """``None`` ⇒ unclassified ⇒ the consumer denies. Never inferred from ``kind``."""

    detail: str | None = None
    """One human-readable line for the plan render. Never parsed, never a credential."""

    def to_dict(self) -> dict[str, Any]:
        """Wire form. Absent optional fields are omitted, not emitted as ``null``."""
        payload: dict[str, Any] = {"kind": self.kind, "object": self.object}
        if self.migration is not None:
            payload["migration"] = self.migration
        if self.tier is not None:
            payload["tier"] = self.tier.value
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class ChangeSet:
    """The classified change set for a migration tree.

    An **empty** ``changes`` means "looked, nothing to change". A change set that
    is *absent* from the payload means "did not classify". The object wrapper is
    what keeps those two apart, and that distinction is the point of it.
    """

    changes: tuple[ChangeEntry, ...] = ()
    contract_version: int = CONTRACT_VERSION

    @property
    def worst_tier(self) -> RiskTier | None:
        """Most severe tier over the *classifiable* entries (``None`` if none are)."""
        return worst_tier(entry.tier for entry in self.changes)

    @property
    def has_unclassified(self) -> bool:
        """True when any entry carries no tier."""
        return any(entry.tier is None for entry in self.changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "changes": [entry.to_dict() for entry in self.changes],
        }


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #

# kind → tier, for the kinds whose tier does not depend on the statement's own
# attributes. A kind absent from this table is unclassified. Shared by both
# backends, so they cannot disagree about a boundary.
_TIER_BY_KIND: Final[dict[str, RiskTier | None]] = {
    # additive — adds a new object; no existing reader or writer can break
    "create_table": RiskTier.ADDITIVE,
    "create_table_as": RiskTier.ADDITIVE,
    "create_view": RiskTier.ADDITIVE,
    "create_materialized_view": RiskTier.ADDITIVE,
    "create_schema": RiskTier.ADDITIVE,
    "create_sequence": RiskTier.ADDITIVE,
    "create_type": RiskTier.ADDITIVE,
    "create_domain": RiskTier.ADDITIVE,
    "create_extension": RiskTier.ADDITIVE,
    "create_function": RiskTier.ADDITIVE,
    "create_procedure": RiskTier.ADDITIVE,
    "create_trigger": RiskTier.ADDITIVE,
    "create_policy": RiskTier.ADDITIVE,
    "create_rule": RiskTier.ADDITIVE,
    "insert": RiskTier.ADDITIVE,
    # `ALTER TYPE … ADD VALUE` cannot be taken back, but it destroys nothing and
    # breaks no reader — irreversibility in this taxonomy is about data.
    "alter_type": RiskTier.ADDITIVE,
    # reversible — changes existing state, with a down path that restores it
    "rename_column": RiskTier.REVERSIBLE,
    "rename_object": RiskTier.REVERSIBLE,
    "set_column_default": RiskTier.REVERSIBLE,
    "drop_column_default": RiskTier.REVERSIBLE,
    "drop_not_null": RiskTier.REVERSIBLE,
    "replace_view": RiskTier.REVERSIBLE,
    "replace_function": RiskTier.REVERSIBLE,
    "replace_procedure": RiskTier.REVERSIBLE,
    "change_owner": RiskTier.REVERSIBLE,
    "alter_sequence": RiskTier.REVERSIBLE,
    "alter_default_privileges": RiskTier.REVERSIBLE,
    "grant": RiskTier.REVERSIBLE,
    "revoke": RiskTier.REVERSIBLE,
    "comment": RiskTier.REVERSIBLE,
    # lock_risky — semantically safe, but takes a lock that can stall a hot table
    "set_not_null": RiskTier.LOCK_RISKY,
    "cluster": RiskTier.LOCK_RISKY,
    "refresh_materialized_view": RiskTier.LOCK_RISKY,
    "reindex": RiskTier.LOCK_RISKY,
    # destructive — destroys data or an object, restorable from backup
    "drop_index": RiskTier.DESTRUCTIVE,
    "drop_view": RiskTier.DESTRUCTIVE,
    "drop_materialized_view": RiskTier.DESTRUCTIVE,
    "drop_function": RiskTier.DESTRUCTIVE,
    "drop_procedure": RiskTier.DESTRUCTIVE,
    "drop_type": RiskTier.DESTRUCTIVE,
    "drop_domain": RiskTier.DESTRUCTIVE,
    "drop_trigger": RiskTier.DESTRUCTIVE,
    "drop_policy": RiskTier.DESTRUCTIVE,
    "drop_rule": RiskTier.DESTRUCTIVE,
    "drop_extension": RiskTier.DESTRUCTIVE,
    "drop_constraint": RiskTier.DESTRUCTIVE,
    "truncate": RiskTier.DESTRUCTIVE,
    "delete": RiskTier.DESTRUCTIVE,
    "update": RiskTier.DESTRUCTIVE,
    # irreversible — destroys data with no down path that can restore it
    "drop_column": RiskTier.IRREVERSIBLE,
    "drop_table": RiskTier.IRREVERSIBLE,
    "drop_schema": RiskTier.IRREVERSIBLE,
    "drop_sequence": RiskTier.IRREVERSIBLE,
}

# Detail lines that read better than the generic "KIND WITH UNDERSCORES" form.
_DETAIL_BY_KIND: Final[dict[str, str]] = {
    "replace_view": "CREATE OR REPLACE VIEW",
    "replace_function": "CREATE OR REPLACE FUNCTION",
    "replace_procedure": "CREATE OR REPLACE PROCEDURE",
    "create_table_as": "CREATE TABLE AS",
}


def _detail_for(kind: str) -> str:
    """The default one-line detail for ``kind`` — shared by both backends."""
    return _DETAIL_BY_KIND.get(kind, kind.replace("_", " ").upper())


_ALTER_COLUMN_TYPE_DETAIL: Final = (
    "reversible when widening and irreversible when narrowing; preflight cannot "
    "tell without the source and target types"
)


def tier_for_add_column(*, nullable: bool, has_default: bool) -> RiskTier:
    """`ADD COLUMN`: additive when nullable, otherwise a lock risk.

    ``NOT NULL DEFAULT`` rewrites the table on PostgreSQL below 11 and takes an
    ACCESS EXCLUSIVE lock on every version; ``NOT NULL`` without a default aborts
    outright on a non-empty table. Neither destroys data, and preflight has no
    connection with which to check the server version, so both take the more
    severe of the two readings available to it.
    """
    del has_default  # both NOT NULL forms are lock-risky; named for the call sites
    return RiskTier.ADDITIVE if nullable else RiskTier.LOCK_RISKY


def tier_for_create_index(*, concurrently: bool) -> RiskTier:
    """`CREATE INDEX CONCURRENTLY` is additive; a plain one blocks writes."""
    return RiskTier.ADDITIVE if concurrently else RiskTier.LOCK_RISKY


def tier_for_add_constraint(*, not_valid: bool) -> RiskTier:
    """`NOT VALID` defers the scan; immediate validation locks and can reject rows."""
    return RiskTier.REVERSIBLE if not_valid else RiskTier.LOCK_RISKY


# --------------------------------------------------------------------------- #
# Classification context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Context:
    """What every entry produced from one file gets stamped with."""

    migration: str | None = None
    source: str | None = None
    default_schema: str = _DEFAULT_SCHEMA

    def entry(
        self,
        kind: str,
        obj: str | None = None,
        *,
        detail: str | None = None,
        tier: RiskTier | None = None,
    ) -> ChangeEntry:
        """Build an entry, defaulting the tier from :data:`_TIER_BY_KIND`."""
        return ChangeEntry(
            kind=kind,
            object=obj or self.source or "unknown",
            migration=self.migration,
            tier=tier if tier is not None else _TIER_BY_KIND.get(kind),
            detail=detail,
        )

    def unclassified(self, kind: str, obj: str | None, detail: str) -> ChangeEntry:
        """An entry confiture will not tier. Explicitly tier-less, never dropped."""
        return ChangeEntry(
            kind=kind,
            object=obj or self.source or "unknown",
            migration=self.migration,
            tier=None,
            detail=detail,
        )

    def qualified(self, schema: str | None, name: str | None, child: str | None = None) -> str:
        """`schema.name[.child]`, defaulting the schema when the DDL omits one."""
        parts = [_ident(schema) or self.default_schema, _ident(name)]
        if child:
            parts.append(_ident(child))
        return ".".join(part for part in parts if part)

    def dotted(self, raw: str | None, child: str | None = None) -> str | None:
        """Qualify an already-dotted identifier such as ``app.tb_user``.

        With a ``child``, ``raw`` is the relation and ``child`` the leaf; without
        one, ``raw`` may itself already carry the leaf (``app.tb_user.nickname``).
        """
        if not raw:
            return None
        parts = _split_dotted(raw)
        if child is None:
            return self.from_parts(parts)
        if len(parts) >= 2:
            return self.qualified(parts[-2], parts[-1], child)
        return self.qualified(None, parts[0], child)

    def bare(self, raw: str | None) -> str | None:
        """A name that is not schema-scoped (a schema, an extension, a role)."""
        if not raw:
            return None
        return _ident(_split_dotted(raw)[-1])

    def from_parts(self, parts: list[str]) -> str | None:
        """Qualify already-split identifier parts.

        Three parts is ``schema.table.child`` — a column, or a trigger/policy
        whose name is scoped to its table. Taking only the last two would report
        the *table* as the schema.
        """
        if not parts:
            return None
        if len(parts) >= 3:
            return self.qualified(parts[-3], parts[-2], parts[-1])
        if len(parts) == 2:
            return self.qualified(parts[0], parts[1])
        return self.qualified(None, parts[0])


def _ident(raw: str | None) -> str | None:
    """Fold an identifier the way PostgreSQL folds an unquoted one."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        return text[1:-1]
    return text.lower()


def _split_dotted(raw: str) -> list[str]:
    """Split ``a.b`` on dots, keeping quoted segments intact."""
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for char in raw.strip():
        if char == '"':
            in_quotes = not in_quotes
            buf.append(char)
        elif char == "." and not in_quotes:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return [part for part in parts if part]


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def build_change_set(
    migrations_dir: Path,
    *,
    versions: list[str] | None = None,
    default_schema: str = _DEFAULT_SCHEMA,
) -> ChangeSet:
    """Classify every change in ``migrations_dir``.

    Mirrors ``run_preflight``'s discovery — ``*.up.sql`` then ``*.py`` (skipping
    ``__init__.py`` and ``_``-prefixed helpers) — so the change set covers exactly
    the migrations preflight reports on. A missing directory classifies to an
    empty set; preflight already reports that condition on its own.
    """
    from confiture.core._migrator.discovery import _version_from_migration_filename

    if not migrations_dir.exists():
        return ChangeSet()

    entries: list[ChangeEntry] = []

    for up_file in sorted(migrations_dir.glob("*.up.sql"), key=lambda f: f.name):
        version = _version_from_migration_filename(up_file.name)
        if versions is not None and version not in versions:
            continue
        entries.extend(
            classify_statements(
                _read_sql(up_file),
                migration=version,
                source=up_file.name,
                default_schema=default_schema,
            )
        )

    for py_file in sorted(_python_migrations(migrations_dir), key=lambda f: f.name):
        version = _version_from_migration_filename(py_file.name)
        if versions is not None and version not in versions:
            continue
        entries.append(
            ChangeEntry(
                kind="python_migration",
                object=py_file.name,
                migration=version,
                tier=None,
                detail=(
                    "non-SQL migration: confiture cannot read its DDL, so its "
                    "changes are unclassified — review by hand"
                ),
            )
        )

    return ChangeSet(changes=tuple(entries))


def classify_statements(
    sql: str,
    *,
    migration: str | None = None,
    source: str | None = None,
    default_schema: str = _DEFAULT_SCHEMA,
) -> list[ChangeEntry]:
    """Classify every statement in ``sql``.

    ``source`` names the file and is the ``object`` for statements whose target
    cannot be determined. SQL the parser rejects yields an unclassified entry
    rather than an empty list, so a broken migration denies instead of reading as
    "nothing changes".
    """
    ctx = _Context(migration=migration, source=source, default_schema=default_schema)
    if _use_ast():
        try:
            return _ast_entries(sql, ctx)
        except Exception:  # noqa: BLE001 — any parse hiccup falls back to regex
            pass
    return _regex_entries(sql, ctx)


def _use_ast() -> bool:
    # A half-resolvable enum surface would mis-map operations silently — the #192
    # failure mode. Degrade to the regex backend instead.
    return _HAS_PGLAST and enums_are_usable()


def _python_migrations(migrations_dir: Path) -> Iterator[Path]:
    """`.py` migrations, filtered exactly as ``run_preflight`` filters them."""
    return (
        f
        for f in migrations_dir.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    )


def _read_sql(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _command_prefix(statement: str, *, words: int = 5) -> str:
    """The leading keywords of a statement, with every literal stripped.

    ``detail`` is rendered to an operator and must never carry a credential, and
    an unclassified statement is exactly the kind that might hold one
    (``CREATE USER … PASSWORD 'x'``). Only bare word tokens survive.
    """
    tokens: list[str] = []
    for token in statement.split():
        if not re.fullmatch(r"[A-Za-z_][\w$.]*", token):
            break
        tokens.append(token)
        if len(tokens) >= words:
            break
    return " ".join(tokens) or "statement"


# --------------------------------------------------------------------------- #
# pglast backend
# --------------------------------------------------------------------------- #

# Resolved BY NAME, never by literal ordinal (#192).
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")
_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
_AT_ALTER_COLUMN_TYPE = _pg_member("AlterTableType", "AT_AlterColumnType")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_DROP_CONSTRAINT = _pg_member("AlterTableType", "AT_DropConstraint")
_AT_CHANGE_OWNER = _pg_member("AlterTableType", "AT_ChangeOwner")
_AT_COLUMN_DEFAULT = _pg_member("AlterTableType", "AT_ColumnDefault")
_AT_SET_NOT_NULL = _pg_member("AlterTableType", "AT_SetNotNull")
_AT_DROP_NOT_NULL = _pg_member("AlterTableType", "AT_DropNotNull")

_OBJECT_COLUMN = _pg_member("ObjectType", "OBJECT_COLUMN")
_OBJECT_MATVIEW = _pg_member("ObjectType", "OBJECT_MATVIEW")

# DropStmt.removeType → kind. Names resolved by member, never by ordinal.
_DROP_KIND: Final[dict[int, str]] = {
    _pg_member("ObjectType", "OBJECT_TABLE"): "drop_table",
    _pg_member("ObjectType", "OBJECT_INDEX"): "drop_index",
    _pg_member("ObjectType", "OBJECT_VIEW"): "drop_view",
    _OBJECT_MATVIEW: "drop_materialized_view",
    _pg_member("ObjectType", "OBJECT_SEQUENCE"): "drop_sequence",
    _pg_member("ObjectType", "OBJECT_SCHEMA"): "drop_schema",
    _pg_member("ObjectType", "OBJECT_TYPE"): "drop_type",
    _pg_member("ObjectType", "OBJECT_DOMAIN"): "drop_domain",
    _pg_member("ObjectType", "OBJECT_FUNCTION"): "drop_function",
    _pg_member("ObjectType", "OBJECT_PROCEDURE"): "drop_procedure",
    _pg_member("ObjectType", "OBJECT_TRIGGER"): "drop_trigger",
    _pg_member("ObjectType", "OBJECT_POLICY"): "drop_policy",
    _pg_member("ObjectType", "OBJECT_EXTENSION"): "drop_extension",
}

# Objects that are not schema-scoped: their name *is* fully qualified.
_STANDALONE_DROP_KINDS: Final = frozenset({"drop_schema", "drop_extension"})

# Statement types that change neither schema nor data. Emitting entries for
# these would make every migration with a `BEGIN;` deny.
_AST_SKIP: Final = frozenset(
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


def _ast_entries(sql: str, ctx: _Context) -> list[ChangeEntry]:
    import pglast  # noqa: PLC0415 — optional [ast] extra

    entries: list[ChangeEntry] = []
    for raw in pglast.parse_sql(sql):
        entries.extend(_ast_statement(raw, sql, ctx))
    return entries


def _ast_statement(raw: object, sql: str, ctx: _Context) -> list[ChangeEntry]:
    node = getattr(raw, "stmt", None)
    name = type(node).__name__
    if name in _AST_SKIP:
        return []
    handler = _AST_HANDLERS.get(name)
    if handler is None:
        return [
            ctx.unclassified(
                "unclassified",
                None,
                f"{_command_prefix(_ast_source(raw, sql))} — confiture does not "
                "classify this statement",
            )
        ]
    return handler(node, ctx)


def _ast_source(raw: object, sql: str) -> str:
    """The original text of one statement, for a keyword-only detail line."""
    start = getattr(raw, "stmt_location", 0) or 0
    length = getattr(raw, "stmt_len", 0) or 0
    return sql[start : start + length] if length else sql[start:]


def _enum_int(value: object) -> int | None:
    if value is None:
        return None
    inner = getattr(value, "value", value)
    try:
        return int(inner)
    except (TypeError, ValueError):
        return None


def _rel(relation: object) -> tuple[str | None, str | None]:
    if relation is None:
        return (None, None)
    return (getattr(relation, "schemaname", None), getattr(relation, "relname", None))


def _ast_alter_table(node: object, ctx: _Context) -> list[ChangeEntry]:
    # `core/replica/classifier.py` owns the column-attribute helpers; reusing
    # them keeps the two surfaces agreeing on what "nullable" means.
    from confiture.core.replica.classifier import _column_has_default, _column_is_not_null

    schema, table = _rel(getattr(node, "relation", None))
    target = ctx.qualified(schema, table)
    entries: list[ChangeEntry] = []

    for cmd in getattr(node, "cmds", None) or ():
        subtype = _enum_int(cmd.subtype)
        name = getattr(cmd, "name", None)
        if subtype == _AT_ADD_COLUMN:
            coldef = cmd.def_
            column = getattr(coldef, "colname", None)
            nullable = not _column_is_not_null(coldef)
            has_default = _column_has_default(coldef)
            entries.append(
                ctx.entry(
                    "add_column",
                    ctx.qualified(schema, table, column),
                    tier=tier_for_add_column(nullable=nullable, has_default=has_default),
                    detail=_add_column_detail(column, nullable=nullable, has_default=has_default),
                )
            )
        elif subtype == _AT_DROP_COLUMN:
            entries.append(
                ctx.entry(
                    "drop_column",
                    ctx.qualified(schema, table, name),
                    detail=f"DROP COLUMN {_ident(name)}",
                )
            )
        elif subtype == _AT_ALTER_COLUMN_TYPE:
            entries.append(
                ctx.unclassified(
                    "alter_column_type",
                    ctx.qualified(schema, table, name),
                    f"ALTER COLUMN {_ident(name)} TYPE — {_ALTER_COLUMN_TYPE_DETAIL}",
                )
            )
        elif subtype == _AT_ADD_CONSTRAINT:
            constraint = cmd.def_
            not_valid = bool(getattr(constraint, "skip_validation", False))
            conname = getattr(constraint, "conname", None)
            entries.append(
                ctx.entry(
                    "add_constraint",
                    ctx.qualified(schema, table, conname),
                    tier=tier_for_add_constraint(not_valid=not_valid),
                    detail="ADD CONSTRAINT" + (" NOT VALID" if not_valid else ""),
                )
            )
        elif subtype == _AT_DROP_CONSTRAINT:
            entries.append(
                ctx.entry(
                    "drop_constraint",
                    ctx.qualified(schema, table, name),
                    detail=f"DROP CONSTRAINT {_ident(name)}",
                )
            )
        elif subtype == _AT_COLUMN_DEFAULT:
            setting = cmd.def_ is not None
            entries.append(
                ctx.entry(
                    "set_column_default" if setting else "drop_column_default",
                    ctx.qualified(schema, table, name),
                    detail=f"ALTER COLUMN {_ident(name)} "
                    + ("SET DEFAULT" if setting else "DROP DEFAULT"),
                )
            )
        elif subtype == _AT_SET_NOT_NULL:
            entries.append(
                ctx.entry(
                    "set_not_null",
                    ctx.qualified(schema, table, name),
                    detail=f"ALTER COLUMN {_ident(name)} SET NOT NULL — scans the table",
                )
            )
        elif subtype == _AT_DROP_NOT_NULL:
            entries.append(
                ctx.entry(
                    "drop_not_null",
                    ctx.qualified(schema, table, name),
                    detail=f"ALTER COLUMN {_ident(name)} DROP NOT NULL",
                )
            )
        elif subtype == _AT_CHANGE_OWNER:
            entries.append(ctx.entry("change_owner", target, detail="OWNER TO"))
        else:
            entries.append(
                ctx.unclassified(
                    "alter_table",
                    target,
                    "ALTER TABLE subcommand confiture does not classify",
                )
            )
    return entries


def _add_column_detail(column: str | None, *, nullable: bool, has_default: bool) -> str:
    detail = f"ADD COLUMN {_ident(column)}"
    if nullable:
        return detail + " NULL"
    detail += " NOT NULL"
    if has_default:
        return detail + " DEFAULT — takes an ACCESS EXCLUSIVE lock, rewrites below PG 11"
    return detail + " without a default — fails if the table has rows"


def _ast_rename(node: object, ctx: _Context) -> list[ChangeEntry]:
    schema, table = _rel(getattr(node, "relation", None))
    old = getattr(node, "subname", None)
    new = getattr(node, "newname", None)
    if _enum_int(getattr(node, "renameType", None)) == _OBJECT_COLUMN:
        return [
            ctx.entry(
                "rename_column",
                ctx.qualified(schema, table, old),
                detail=f"RENAME COLUMN {_ident(old)} TO {_ident(new)} — "
                "readers on the old name break until they are redeployed",
            )
        ]
    return [
        ctx.entry(
            "rename_object",
            ctx.qualified(schema, table) if table else ctx.bare(new),
            detail=f"RENAME TO {_ident(new)}",
        )
    ]


def _ast_index(node: object, ctx: _Context) -> list[ChangeEntry]:
    schema, table = _rel(getattr(node, "relation", None))
    idxname = getattr(node, "idxname", None)
    concurrently = bool(getattr(node, "concurrent", False))
    return [
        ctx.entry(
            "create_index",
            ctx.qualified(schema, table, idxname),
            tier=tier_for_create_index(concurrently=concurrently),
            detail="CREATE INDEX" + (" CONCURRENTLY" if concurrently else " — blocks writes"),
        )
    ]


def _ast_create_table(node: object, ctx: _Context) -> list[ChangeEntry]:
    schema, table = _rel(getattr(node, "relation", None))
    return [ctx.entry("create_table", ctx.qualified(schema, table), detail="CREATE TABLE")]


def _ast_create_table_as(node: object, ctx: _Context) -> list[ChangeEntry]:
    into = getattr(node, "into", None)
    schema, name = _rel(getattr(into, "rel", None))
    is_matview = _enum_int(getattr(node, "objtype", None)) == _OBJECT_MATVIEW
    kind = "create_materialized_view" if is_matview else "create_table_as"
    return [ctx.entry(kind, ctx.qualified(schema, name), detail=_detail_for(kind))]


def _object_names(obj: object) -> list[str]:
    """Flatten one ``DropStmt.objects`` element into its identifier parts."""
    inner = getattr(obj, "objname", obj)  # ObjectWithArgs → its name
    sval = getattr(inner, "sval", None)
    if sval is not None:
        return [str(sval)]
    if isinstance(inner, (list, tuple)):
        return [str(getattr(part, "sval", part)) for part in inner]
    return [str(inner)]


def _ast_drop(node: object, ctx: _Context) -> list[ChangeEntry]:
    remove_type = _enum_int(getattr(node, "removeType", None))
    kind = _DROP_KIND.get(remove_type if remove_type is not None else -1)
    entries: list[ChangeEntry] = []
    for obj in getattr(node, "objects", None) or ():
        parts = _object_names(obj)
        if kind is None:
            entries.append(
                ctx.unclassified(
                    "drop_object",
                    ctx.dotted(".".join(parts)),
                    "DROP of an object type confiture does not classify",
                )
            )
            continue
        target = ctx.bare(parts[-1]) if kind in _STANDALONE_DROP_KINDS else ctx.from_parts(parts)
        entries.append(ctx.entry(kind, target, detail=_detail_for(kind)))
    return entries


def _ast_truncate(node: object, ctx: _Context) -> list[ChangeEntry]:
    return [
        ctx.entry("truncate", ctx.qualified(*_rel(relation)), detail="TRUNCATE")
        for relation in getattr(node, "relations", None) or ()
    ]


def _relation_stmt(kind: str, detail: str):
    def handler(node: object, ctx: _Context) -> list[ChangeEntry]:
        schema, name = _rel(getattr(node, "relation", None))
        return [ctx.entry(kind, ctx.qualified(schema, name), detail=detail)]

    return handler


def _ast_view(node: object, ctx: _Context) -> list[ChangeEntry]:
    schema, name = _rel(getattr(node, "view", None))
    replace = bool(getattr(node, "replace", False))
    kind = "replace_view" if replace else "create_view"
    return [
        ctx.entry(
            kind,
            ctx.qualified(schema, name),
            detail=_detail_for(kind),
        )
    ]


def _ast_function(node: object, ctx: _Context) -> list[ChangeEntry]:
    parts = [str(getattr(part, "sval", part)) for part in getattr(node, "funcname", None) or ()]
    replace = bool(getattr(node, "replace", False))
    noun = "procedure" if getattr(node, "is_procedure", False) else "function"
    kind = f"{'replace' if replace else 'create'}_{noun}"
    return [ctx.entry(kind, ctx.from_parts(parts), detail=_detail_for(kind))]


def _named_stmt(kind: str, attr: str, *, standalone: bool = False):
    """Handler for a node whose target is a plain name attribute."""

    def handler(node: object, ctx: _Context) -> list[ChangeEntry]:
        raw = getattr(node, attr, None)
        if raw is not None and hasattr(raw, "relname"):
            # CreateSeqStmt.sequence and friends carry a RangeVar, not a string.
            return [ctx.entry(kind, ctx.qualified(*_rel(raw)), detail=_detail_for(kind))]
        name = str(raw) if raw is not None else None
        target = ctx.bare(name) if standalone else ctx.dotted(name)
        return [ctx.entry(kind, target, detail=_detail_for(kind))]

    return handler


def _list_name_stmt(kind: str, attr: str):
    """Handler for a node whose target is a list of ``String`` name parts."""

    def handler(node: object, ctx: _Context) -> list[ChangeEntry]:
        parts = [str(getattr(part, "sval", part)) for part in getattr(node, attr, None) or ()]
        return [ctx.entry(kind, ctx.from_parts(parts), detail=_detail_for(kind))]

    return handler


def _ast_grant(node: object, ctx: _Context) -> list[ChangeEntry]:
    is_grant = bool(getattr(node, "is_grant", True))
    kind = "grant" if is_grant else "revoke"
    targets = []
    for obj in getattr(node, "objects", None) or ():
        schema, name = _rel(obj)
        if name:
            targets.append(ctx.qualified(schema, name))
    if not targets:
        targets = [None]
    return [ctx.entry(kind, target, detail=kind.upper()) for target in targets]


def _ast_comment(node: object, ctx: _Context) -> list[ChangeEntry]:
    parts = _object_names(getattr(node, "object", None))
    return [ctx.entry("comment", ctx.from_parts(parts), detail="COMMENT ON")]


def _ast_simple(kind: str):
    def handler(node: object, ctx: _Context) -> list[ChangeEntry]:
        del node
        return [ctx.entry(kind, None, detail=_detail_for(kind))]

    return handler


_AST_HANDLERS: Final[dict[str, Any]] = {
    "AlterTableStmt": _ast_alter_table,
    "RenameStmt": _ast_rename,
    "IndexStmt": _ast_index,
    "CreateStmt": _ast_create_table,
    "CreateTableAsStmt": _ast_create_table_as,
    "DropStmt": _ast_drop,
    "TruncateStmt": _ast_truncate,
    "DeleteStmt": _relation_stmt("delete", "DELETE"),
    "UpdateStmt": _relation_stmt("update", "UPDATE"),
    "InsertStmt": _relation_stmt("insert", "INSERT"),
    "ViewStmt": _ast_view,
    "CreateFunctionStmt": _ast_function,
    "CreateSeqStmt": _named_stmt("create_sequence", "sequence"),
    "AlterSeqStmt": _named_stmt("alter_sequence", "sequence"),
    "CreateSchemaStmt": _named_stmt("create_schema", "schemaname", standalone=True),
    "CreateExtensionStmt": _named_stmt("create_extension", "extname", standalone=True),
    "CreateEnumStmt": _list_name_stmt("create_type", "typeName"),
    "CreateRangeStmt": _list_name_stmt("create_type", "typeName"),
    "CompositeTypeStmt": _named_stmt("create_type", "typevar"),
    "CreateDomainStmt": _list_name_stmt("create_domain", "domainname"),
    "AlterEnumStmt": _list_name_stmt("alter_type", "typeName"),
    "CreateTrigStmt": _named_stmt("create_trigger", "trigname", standalone=True),
    "CreatePolicyStmt": _named_stmt("create_policy", "policy_name", standalone=True),
    "RuleStmt": _named_stmt("create_rule", "rulename", standalone=True),
    "GrantStmt": _ast_grant,
    "CommentStmt": _ast_comment,
    "AlterOwnerStmt": _ast_simple("change_owner"),
    "AlterDefaultPrivilegesStmt": _ast_simple("alter_default_privileges"),
    "RefreshMatViewStmt": _relation_stmt("refresh_materialized_view", "REFRESH MATERIALIZED VIEW"),
    "ClusterStmt": _relation_stmt("cluster", "CLUSTER"),
    "ReindexStmt": _relation_stmt("reindex", "REINDEX"),
}


# --------------------------------------------------------------------------- #
# regex backend (fallback / parity)
# --------------------------------------------------------------------------- #

_IDENT = r'(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\.(?:"[^"]+"|[A-Za-z_][\w$]*))*'
_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_]\w*)?\$")

# Statement heads that change neither schema nor data (the regex twin of _AST_SKIP).
_RE_SKIP = re.compile(
    r"^(?:BEGIN|COMMIT|END|ROLLBACK|START\s+TRANSACTION|SAVEPOINT|RELEASE\b|SET\b|RESET\b"
    r"|SHOW\b|CHECKPOINT|DISCARD\b|LOCK\b|VACUUM\b|ANALYZE\b|ANALYSE\b|LISTEN\b|NOTIFY\b"
    r"|UNLISTEN\b)",
    re.IGNORECASE,
)

_RE_ALTER_TABLE = re.compile(
    rf"^ALTER\s+(?:TABLE|MATERIALIZED\s+VIEW|VIEW|FOREIGN\s+TABLE)\s+(?:IF\s+EXISTS\s+)?"
    rf"(?:ONLY\s+)?(?P<table>{_IDENT})\s+(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_AT_ADD_COLUMN = re.compile(
    rf"^ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<col>{_IDENT})\s+(?P<tail>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_AT_DROP_COLUMN = re.compile(
    rf"^DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(?P<col>{_IDENT})", re.IGNORECASE
)
_RE_AT_RENAME_COLUMN = re.compile(
    rf"^RENAME\s+(?:COLUMN\s+)?(?P<old>{_IDENT})\s+TO\s+(?P<new>{_IDENT})", re.IGNORECASE
)
_RE_AT_RENAME_TO = re.compile(rf"^RENAME\s+TO\s+(?P<new>{_IDENT})", re.IGNORECASE)
_RE_AT_ALTER_COLUMN = re.compile(
    rf"^ALTER\s+(?:COLUMN\s+)?(?P<col>{_IDENT})\s+(?P<action>.*)$", re.IGNORECASE | re.DOTALL
)
_RE_AT_ADD_CONSTRAINT = re.compile(
    rf"^ADD\s+(?:CONSTRAINT\s+(?P<name>{_IDENT})\s+)?"
    r"(?P<body>(?:PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE).*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_AT_DROP_CONSTRAINT = re.compile(
    rf"^DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?(?P<name>{_IDENT})", re.IGNORECASE
)
_RE_AT_OWNER = re.compile(r"^OWNER\s+TO\b", re.IGNORECASE)
_RE_AT_ADD_BARE_COLUMN = re.compile(
    rf"^ADD\s+(?P<col>{_IDENT})\s+(?P<tail>.*)$", re.IGNORECASE | re.DOTALL
)

_RE_CREATE_INDEX = re.compile(
    rf"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<conc>CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:(?!ON\s)(?P<idx>{_IDENT})\s+)?ON\s+(?:ONLY\s+)?(?P<table>{_IDENT})",
    re.IGNORECASE,
)
_RE_DROP = re.compile(
    r"^DROP\s+(?P<what>TABLE|INDEX|MATERIALIZED\s+VIEW|VIEW|SEQUENCE|SCHEMA|TYPE|DOMAIN"
    r"|FUNCTION|PROCEDURE|TRIGGER|POLICY|RULE|EXTENSION)\s+"
    r"(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?(?P<names>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_TRUNCATE = re.compile(
    r"^TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?(?P<names>.+)$", re.IGNORECASE | re.DOTALL
)
_RE_GRANT = re.compile(r"^(?P<verb>GRANT|REVOKE)\b", re.IGNORECASE)
_RE_GRANT_TARGET = re.compile(
    rf"\bON\s+(?:TABLE\s+|SEQUENCE\s+|SCHEMA\s+)?(?P<obj>{_IDENT})", re.IGNORECASE
)
_RE_COMMENT = re.compile(rf"^COMMENT\s+ON\s+(?:\w+\s+)+?(?P<obj>{_IDENT})", re.IGNORECASE)

_DROP_KIND_BY_WORD: Final[dict[str, str]] = {
    "table": "drop_table",
    "index": "drop_index",
    "materialized view": "drop_materialized_view",
    "view": "drop_view",
    "sequence": "drop_sequence",
    "schema": "drop_schema",
    "type": "drop_type",
    "domain": "drop_domain",
    "function": "drop_function",
    "procedure": "drop_procedure",
    "trigger": "drop_trigger",
    "policy": "drop_policy",
    "rule": "drop_rule",
    "extension": "drop_extension",
}

# Simple `head → kind` patterns whose target is the single `name` group.
_SIMPLE_PATTERNS: Final[tuple[tuple[re.Pattern[str], str, bool], ...]] = (
    (
        re.compile(
            rf"^CREATE\s+(?:GLOBAL\s+|LOCAL\s+)?(?:UNLOGGED\s+|TEMPORARY\s+|TEMP\s+)?TABLE\s+"
            rf"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENT})",
            re.IGNORECASE,
        ),
        "create_table",
        False,
    ),
    (
        re.compile(
            rf"^CREATE\s+MATERIALIZED\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENT})",
            re.IGNORECASE,
        ),
        "create_materialized_view",
        False,
    ),
    (
        re.compile(
            rf"^CREATE\s+OR\s+REPLACE\s+(?:\w+\s+)*?VIEW\s+(?P<name>{_IDENT})", re.IGNORECASE
        ),
        "replace_view",
        False,
    ),
    (
        re.compile(rf"^CREATE\s+(?:\w+\s+)*?VIEW\s+(?P<name>{_IDENT})", re.IGNORECASE),
        "create_view",
        False,
    ),
    (
        re.compile(rf"^CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(?P<name>{_IDENT})", re.IGNORECASE),
        "replace_function",
        False,
    ),
    (
        re.compile(rf"^CREATE\s+FUNCTION\s+(?P<name>{_IDENT})", re.IGNORECASE),
        "create_function",
        False,
    ),
    (
        re.compile(rf"^CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+(?P<name>{_IDENT})", re.IGNORECASE),
        "replace_procedure",
        False,
    ),
    (
        re.compile(rf"^CREATE\s+PROCEDURE\s+(?P<name>{_IDENT})", re.IGNORECASE),
        "create_procedure",
        False,
    ),
    (
        re.compile(
            rf"^CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENT})", re.IGNORECASE
        ),
        "create_schema",
        True,
    ),
    (
        re.compile(
            rf"^CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENT})", re.IGNORECASE
        ),
        "create_sequence",
        False,
    ),
    (re.compile(rf"^CREATE\s+TYPE\s+(?P<name>{_IDENT})", re.IGNORECASE), "create_type", False),
    (re.compile(rf"^CREATE\s+DOMAIN\s+(?P<name>{_IDENT})", re.IGNORECASE), "create_domain", False),
    (
        re.compile(
            rf"^CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_IDENT})", re.IGNORECASE
        ),
        "create_extension",
        True,
    ),
    (
        re.compile(
            rf"^CREATE\s+(?:CONSTRAINT\s+)?TRIGGER\s+(?P<name>{_IDENT})",
            re.IGNORECASE,
        ),
        "create_trigger",
        True,
    ),
    (re.compile(rf"^CREATE\s+POLICY\s+(?P<name>{_IDENT})", re.IGNORECASE), "create_policy", True),
    (re.compile(rf"^CREATE\s+RULE\s+(?P<name>{_IDENT})", re.IGNORECASE), "create_rule", True),
    (
        re.compile(rf"^DELETE\s+FROM\s+(?:ONLY\s+)?(?P<name>{_IDENT})", re.IGNORECASE),
        "delete",
        False,
    ),
    (re.compile(rf"^UPDATE\s+(?:ONLY\s+)?(?P<name>{_IDENT})", re.IGNORECASE), "update", False),
    (re.compile(rf"^INSERT\s+INTO\s+(?P<name>{_IDENT})", re.IGNORECASE), "insert", False),
    (
        re.compile(
            rf"^REFRESH\s+MATERIALIZED\s+VIEW\s+(?:CONCURRENTLY\s+)?(?P<name>{_IDENT})",
            re.IGNORECASE,
        ),
        "refresh_materialized_view",
        False,
    ),
    (re.compile(rf"^CLUSTER\s+(?P<name>{_IDENT})", re.IGNORECASE), "cluster", False),
    (re.compile(rf"^REINDEX\s+(?:\w+\s+)?(?P<name>{_IDENT})", re.IGNORECASE), "reindex", False),
    (
        re.compile(rf"^ALTER\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?(?P<name>{_IDENT})", re.IGNORECASE),
        "alter_sequence",
        False,
    ),
    (re.compile(rf"^ALTER\s+TYPE\s+(?P<name>{_IDENT})", re.IGNORECASE), "alter_type", False),
    (
        re.compile(r"^ALTER\s+DEFAULT\s+PRIVILEGES\b", re.IGNORECASE),
        "alter_default_privileges",
        False,
    ),
)


def _regex_entries(sql: str, ctx: _Context) -> list[ChangeEntry]:
    entries: list[ChangeEntry] = []
    for statement in _split_statements(sql):
        entries.extend(_regex_one(statement, ctx))
    return entries


def _regex_one(statement: str, ctx: _Context) -> list[ChangeEntry]:
    text = statement.strip()
    if not text or _RE_SKIP.match(text):
        return []

    alter = _RE_ALTER_TABLE.match(text)
    if alter:
        return _regex_alter_table(alter, ctx)

    index = _RE_CREATE_INDEX.match(text)
    if index:
        concurrently = index.group("conc") is not None
        return [
            ctx.entry(
                "create_index",
                ctx.dotted(index.group("table"), index.group("idx")),
                tier=tier_for_create_index(concurrently=concurrently),
                detail="CREATE INDEX" + (" CONCURRENTLY" if concurrently else " — blocks writes"),
            )
        ]

    drop = _RE_DROP.match(text)
    if drop:
        return _regex_drop(drop, ctx)

    truncate = _RE_TRUNCATE.match(text)
    if truncate:
        return [
            ctx.entry("truncate", ctx.dotted(name), detail="TRUNCATE")
            for name in _split_object_list(truncate.group("names"))
        ]

    grant = _RE_GRANT.match(text)
    if grant:
        target = _RE_GRANT_TARGET.search(text)
        kind = grant.group("verb").lower()
        return [
            ctx.entry(
                kind,
                ctx.dotted(target.group("obj")) if target else None,
                detail=kind.upper(),
            )
        ]

    comment = _RE_COMMENT.match(text)
    if comment:
        return [ctx.entry("comment", ctx.dotted(comment.group("obj")), detail="COMMENT ON")]

    for pattern, kind, standalone in _SIMPLE_PATTERNS:
        match = pattern.match(text)
        if match:
            raw = match.groupdict().get("name")
            target = (ctx.bare(raw) if standalone else ctx.dotted(raw)) if raw else None
            return [ctx.entry(kind, target, detail=_detail_for(kind))]

    return [
        ctx.unclassified(
            "unclassified",
            None,
            f"{_command_prefix(text)} — confiture does not classify this statement",
        )
    ]


def _regex_alter_table(match: re.Match[str], ctx: _Context) -> list[ChangeEntry]:
    table = match.group("table")
    rest = match.group("rest").strip()
    target = ctx.dotted(table)

    add_column = _RE_AT_ADD_COLUMN.match(rest)
    if add_column:
        return [_regex_add_column(add_column, table, ctx)]

    drop_column = _RE_AT_DROP_COLUMN.match(rest)
    if drop_column:
        column = drop_column.group("col")
        return [
            ctx.entry(
                "drop_column",
                ctx.dotted(table, column),
                detail=f"DROP COLUMN {_ident(column)}",
            )
        ]

    rename_to = _RE_AT_RENAME_TO.match(rest)
    if rename_to:
        return [
            ctx.entry("rename_object", target, detail=f"RENAME TO {_ident(rename_to.group('new'))}")
        ]

    rename = _RE_AT_RENAME_COLUMN.match(rest)
    if rename:
        old, new = rename.group("old"), rename.group("new")
        return [
            ctx.entry(
                "rename_column",
                ctx.dotted(table, old),
                detail=f"RENAME COLUMN {_ident(old)} TO {_ident(new)} — "
                "readers on the old name break until they are redeployed",
            )
        ]

    alter_column = _RE_AT_ALTER_COLUMN.match(rest)
    if alter_column:
        entry = _regex_alter_column(alter_column, table, ctx)
        if entry is not None:
            return [entry]

    add_constraint = _RE_AT_ADD_CONSTRAINT.match(rest)
    if add_constraint:
        not_valid = "not valid" in add_constraint.group("body").lower()
        return [
            ctx.entry(
                "add_constraint",
                ctx.dotted(table, add_constraint.group("name")),
                tier=tier_for_add_constraint(not_valid=not_valid),
                detail="ADD CONSTRAINT" + (" NOT VALID" if not_valid else ""),
            )
        ]

    drop_constraint = _RE_AT_DROP_CONSTRAINT.match(rest)
    if drop_constraint:
        name = drop_constraint.group("name")
        return [
            ctx.entry(
                "drop_constraint",
                ctx.dotted(table, name),
                detail=f"DROP CONSTRAINT {_ident(name)}",
            )
        ]

    if _RE_AT_OWNER.match(rest):
        return [ctx.entry("change_owner", target, detail="OWNER TO")]

    bare_add = _RE_AT_ADD_BARE_COLUMN.match(rest)
    if bare_add:
        return [_regex_add_column(bare_add, table, ctx)]

    return [
        ctx.unclassified(
            "alter_table", target, "ALTER TABLE subcommand confiture does not classify"
        )
    ]


def _regex_add_column(match: re.Match[str], table: str, ctx: _Context) -> ChangeEntry:
    column = match.group("col")
    tail = match.group("tail").lower()
    nullable = "not null" not in tail
    has_default = "default" in tail
    return ctx.entry(
        "add_column",
        ctx.dotted(table, column),
        tier=tier_for_add_column(nullable=nullable, has_default=has_default),
        detail=_add_column_detail(column, nullable=nullable, has_default=has_default),
    )


def _regex_alter_column(match: re.Match[str], table: str, ctx: _Context) -> ChangeEntry | None:
    column = match.group("col")
    action = match.group("action").strip().lower()
    target = ctx.dotted(table, column)
    if re.match(r"^(?:set\s+data\s+)?type\b", action):
        return ctx.unclassified(
            "alter_column_type",
            target,
            f"ALTER COLUMN {_ident(column)} TYPE — {_ALTER_COLUMN_TYPE_DETAIL}",
        )
    if action.startswith("set default"):
        return ctx.entry(
            "set_column_default", target, detail=f"ALTER COLUMN {_ident(column)} SET DEFAULT"
        )
    if action.startswith("drop default"):
        return ctx.entry(
            "drop_column_default", target, detail=f"ALTER COLUMN {_ident(column)} DROP DEFAULT"
        )
    if action.startswith("set not null"):
        return ctx.entry(
            "set_not_null",
            target,
            detail=f"ALTER COLUMN {_ident(column)} SET NOT NULL — scans the table",
        )
    if action.startswith("drop not null"):
        return ctx.entry(
            "drop_not_null", target, detail=f"ALTER COLUMN {_ident(column)} DROP NOT NULL"
        )
    return None


def _regex_drop(match: re.Match[str], ctx: _Context) -> list[ChangeEntry]:
    word = re.sub(r"\s+", " ", match.group("what")).lower()
    kind = _DROP_KIND_BY_WORD[word]
    standalone = kind in _STANDALONE_DROP_KINDS
    # `DROP TRIGGER t ON tbl` scopes the name to a table; a trailing
    # CASCADE|RESTRICT belongs to neither.
    head, _, tail = _partition_on_clause(match.group("names"))
    relation = _strip_trailing_clause(tail) or None
    return [
        ctx.entry(
            kind,
            ctx.bare(name)
            if standalone
            else (ctx.dotted(relation, name) if relation else ctx.dotted(name)),
            detail=_detail_for(kind),
        )
        for name in _split_object_list(_strip_trailing_clause(head))
    ]


def _partition_on_clause(raw: str) -> tuple[str, str, str]:
    parts = re.split(r"\bON\b", raw, maxsplit=1, flags=re.IGNORECASE)
    return (parts[0], "ON", parts[1]) if len(parts) > 1 else (parts[0], "", "")


def _strip_trailing_clause(raw: str) -> str:
    return re.sub(r"\b(?:CASCADE|RESTRICT)\b.*$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()


def _split_object_list(raw: str) -> list[str]:
    """Split `a, b.c` into names, dropping any argument list or trailing clause."""
    names = []
    for chunk in raw.split(","):
        name = chunk.strip().split("(")[0].strip()
        name = name.split()[0] if name.split() else ""
        if name:
            names.append(name)
    return names


def _split_statements(sql: str) -> list[str]:
    """Split on top-level ``;``, respecting dollar-quoted bodies, literals and comments.

    The naive ``sql.split(";")`` the replica classifier uses is fine for the
    single-statement DDL its matrix covers, but it shreds a ``CREATE FUNCTION``
    body — which this module has to classify as one statement.
    """
    statements: list[str] = []
    buf: list[str] = []
    index = 0
    length = len(sql)
    tag: str | None = None

    while index < length:
        char = sql[index]
        if tag is not None:
            if sql.startswith(tag, index):
                buf.append(tag)
                index += len(tag)
                tag = None
            else:
                buf.append(char)
                index += 1
            continue
        if char == "$":
            opener = _DOLLAR_TAG.match(sql, index)
            if opener:
                tag = opener.group(0)
                buf.append(tag)
                index += len(tag)
                continue
        if char == "'":
            end = index + 1
            while end < length:
                if sql[end] == "'":
                    if end + 1 < length and sql[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            buf.append(sql[index:end])
            index = end
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline
            continue
        if sql.startswith("/*", index):
            close = sql.find("*/", index)
            index = length if close == -1 else close + 2
            continue
        if char == ";":
            statements.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1

    statements.append("".join(buf))
    return [stripped for stripped in (s.strip() for s in statements) if stripped]
