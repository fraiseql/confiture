"""The pglast walk: one handler per statement kind, producing change entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import (
    column_has_default as _column_has_default,
)
from confiture.core.ddl_walk import (
    column_is_not_null as _column_is_not_null,
)
from confiture.core.ddl_walk import (
    enum_int as _enum_int,
)
from confiture.core.ddl_walk import (
    relation_parts as _rel,
)
from confiture.core.ddl_walk import (
    type_name as _type_name,
)
from confiture.core.type_lattice import (
    canonical_type,
)

if TYPE_CHECKING:
    pass
from confiture.core.change_set.models import (
    ChangeEntry,
    _detail_for,
    tier_for_add_column,
    tier_for_add_constraint,
    tier_for_create_index,
)
from confiture.core.change_set.naming import _command_prefix, _Context, _ident

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


def _ast_alter_table(node: object, ctx: _Context) -> list[ChangeEntry]:
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
                    tier=tier_for_add_column(
                        nullable=nullable,
                        has_default=has_default,
                        server_version=ctx.server_version,
                    ),
                    detail=_add_column_detail(column, nullable=nullable, has_default=has_default),
                    has_default=has_default,
                    nullable=nullable,
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
                ctx.alter_column_type(
                    ctx.qualified(schema, table, name),
                    name,
                    canonical_type(_type_name(getattr(cmd.def_, "typeName", None))),
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
                    not_valid=not_valid,
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
            concurrently=concurrently,
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
