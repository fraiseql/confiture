"""Does an ``INSERT`` into a tenant table supply the discriminator (``tenant_001``)?

A routine that writes a row into a tenant table decides which tenant the row
belongs to — or, when its column list leaves the discriminator out and the column
has no default, decides nothing, and the row is refused (``NOT NULL``) or lands
with no tenant. A default is a legitimate answer:
``tenant_id uuid NOT NULL DEFAULT current_setting('app.tenant_id')::uuid`` scopes
every write the session makes.

Which table is a tenant table is what
:func:`~confiture.core.linting.tenant.scope.classify` decided for every rule of the
family — never inferred here. Each routine body is read by
:func:`~confiture.core.linting.references.routine_bodies`, which reads PL/pgSQL
through the one fragment reader.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

from confiture.core.ddl_walk import walk_nodes
from confiture.core.linting.references import routine_bodies
from confiture.core.linting.tenant.scope import Scope, TableScope, TenancyFinding, TenantScopes
from confiture.core.schema_identity import DEFAULT_SCHEMA

if TYPE_CHECKING:
    from confiture.core.linting.inventory import SchemaObject
    from confiture.core.linting.references import BodyStatement, RoutineBody


def _target(scopes: TenantScopes, relation: Any) -> TableScope | None:
    """The tenant table an ``INSERT`` writes into, or ``None`` for any other table."""
    entry = scopes.tables.get((relation.schemaname or DEFAULT_SCHEMA, relation.relname))
    return entry if entry is not None and entry.scope is Scope.TENANT else None


def _has_default(entry: TableScope) -> bool:
    column = entry.column
    return column is not None and (
        column.default is not None or column.identity is not None or column.generated is not None
    )


def _judge(
    routine: SchemaObject, statement: BodyStatement, insert: Any, scopes: TenantScopes
) -> TenancyFinding | None:
    entry = _target(scopes, insert.relation)
    if entry is None or entry.key is None or _has_default(entry):
        return None
    columns = [target.name for target in insert.cols or ()]
    if not columns or entry.key in columns:
        return None
    table, column = entry.table.qualified, scopes.tenancy.discriminator
    return TenancyFinding(
        routine.qualified,
        routine.file,
        statement.line_at(insert.relation.location),
        f"{routine.qualified} inserts into {table} without {column}, which has no "
        "default: the row belongs to no tenant",
        f"add {column} to the INSERT's column list, or give {table}.{column} a default "
        f"(DEFAULT current_setting('app.{column}'))",
    )


def _body_findings(body: RoutineBody, scopes: TenantScopes) -> Iterator[TenancyFinding]:
    for statement in body.statements:
        for node in walk_nodes(statement.root):
            if type(node).__name__ == "InsertStmt":
                finding = _judge(body.obj, statement, node, scopes)
                if finding is not None:
                    yield finding


def insert_findings(
    scopes: TenantScopes, sources: Sequence[tuple[str | None, str]]
) -> Iterator[TenancyFinding]:
    """``tenant_001``: every routine ``INSERT`` into a tenant table that leaves the discriminator out.

    Args:
        scopes: Every table's scope, as the family decided it.
        sources: ``(file label, text)`` per schema file; each routine is read from its file.
    """
    for label, text in sources:
        for body in routine_bodies(text):
            body.obj.file = label
            yield from _body_findings(body, scopes)
