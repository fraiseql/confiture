"""A key cannot cross tenants, nor collide across them (``tenant_004``, ``tenant_005``).

``tenant_004`` reads every foreign key between two tables whose scope
:func:`~confiture.core.linting.tenant.scope.classify` decided. Between two tenant
tables the key carries the discriminator on both sides, at the same position —
``(tenant_id, fk_order) REFERENCES tb_order (tenant_id, id)`` — so PostgreSQL itself
refuses a row pointing at another tenant's row. The root plays the same part with
its tenant id — :func:`~confiture.core.linting.tenant.scope.tenant_id_column`, the
column the discriminator references, which need not be its primary key:
``tenant_id REFERENCES tb_organization (id)`` is the discriminator referencing the
tenant, and any other column referencing the root names a tenant that is not the
row's own. A global table points at no tenant's row; a tenant table
may point at a global one. A table whose tenancy nobody decided is ``tenant_002``'s.

``tenant_005`` reads every key of a tenant table: its primary key, each ``UNIQUE``
and each unique index lead with the discriminator, or one tenant's row blocks
another's and the error tells the second the value exists. A unique index — never
an inline ``UNIQUE`` — may be declared platform-wide with ``-- confiture:tenant-global
<reason>`` above its ``CREATE UNIQUE INDEX``; the directive on one that already leads
with the discriminator is stale.

Every fact is read from the model: :class:`~confiture.core.schema_model.Constraint`
as ``ddl_walk.read_constraint`` left it, ``ALTER TABLE … ADD CONSTRAINT`` folded in.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from confiture.core.linting.tenant.scope import (
    GLOBAL_DIRECTIVE,
    Scope,
    TableScope,
    TenancyFinding,
    TenantScopes,
    finding,
    primary_key,
)
from confiture.core.schema_identity import quote_identifier

if TYPE_CHECKING:
    from confiture.core.schema_model import Constraint, Index

#: The scopes whose rows belong to one tenant.
_TENANT_SIDE = frozenset({Scope.TENANT, Scope.ROOT})


def _columns(columns: tuple[str, ...]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def _unique_on(table: TableScope, columns: tuple[str, ...]) -> bool:
    """Whether a primary key, UNIQUE or whole unique index covers exactly *columns*."""
    wanted = set(columns)
    return any(
        c.kind in ("primary_key", "unique") and set(c.columns) == wanted
        for c in table.table.constraints
    ) or any(
        ix.unique and ix.where is None and set(ix.columns) == wanted for ix in table.table.indexes
    )


def _carries_tenant(
    fk: Constraint, refs: tuple[str, ...], source_key: str, target_key: str
) -> bool:
    return any(
        column == source_key and ref == target_key
        for column, ref in zip(fk.columns, refs, strict=False)
    )


def _line(source: TableScope, fk: Constraint) -> int | None:
    """Where the key's first column is written, else ``None`` (the table's own line)."""
    first = next((c for c in fk.columns if c != source.key), None)
    return next((c.line for c in source.table.columns if c.folded == first), None)


def _crossing(
    source: TableScope, target: TableScope, fk: Constraint, refs: tuple[str, ...]
) -> TenancyFinding:
    """A foreign key between two tenant tables that does not carry the discriminator."""
    source_key, target_key = source.key or "", target.key or ""
    held = (source_key, *(c for c in fk.columns if c != source_key))
    referenced = (target_key, *(r for r in refs if r != target_key))
    fix = (
        f"FOREIGN KEY ({_columns(held)}) REFERENCES {target.table.qualified} "
        f"({_columns(referenced)})"
    )
    if not _unique_on(target, referenced):
        fix += (
            f"; {target.table.qualified} needs PRIMARY KEY ({_columns(referenced)}) "
            f"or UNIQUE ({_columns(referenced)})"
        )
    message = (
        f"{source.table.qualified}'s foreign key ({_columns(fk.columns)}) → "
        f"{target.table.qualified} ({_columns(refs)}) can point at another tenant's row: "
        f"it does not carry {source_key} on both sides"
    )
    return finding(source.table, message, fix, _line(source, fk))


def _root_crossing(
    source: TableScope,
    target: TableScope,
    fk: Constraint,
    refs: tuple[str, ...],
    tenancy_column: str,
) -> TenancyFinding:
    """A column other than the discriminator referencing the table of tenants.

    It is one of two things, and the schema cannot say which. The row's own
    tenant, written a second time, duplicates the discriminator and can disagree
    with it: a row whose two columns name two tenants is visible to the wrong one.
    Another organisation is a counterparty — a provider, a partner — and a pointer
    into another tenant's space is how one tenant's rows come to reveal another's;
    a counterparty is a relation of the tenant's own, over a global directory of
    companies. Neither is an exception to declare, so there is no directive: a
    schema moving to the design records today's findings in a ``--baseline``.
    """
    columns = _columns(fk.columns)
    return finding(
        source.table,
        f"{source.table.qualified}'s foreign key ({columns}) → "
        f"{target.table.qualified} ({_columns(refs)}): only {tenancy_column} references "
        f"the table of tenants. If {columns} is the row's own tenant, it duplicates "
        f"{tenancy_column} and can disagree with it; if it is another organisation, "
        "it is a counterparty pointing into another tenant's space",
        f"the row's own tenant: drop {columns} and reference "
        f"{target.table.qualified} ({_columns((target.key or '',))}) through "
        f"{tenancy_column}; a counterparty: a tenant table of its own "
        f"({tenancy_column}, id, …) over a global directory of companies, referenced "
        f"as ({tenancy_column}, fk_…)",
        _line(source, fk),
    )


def _global_to_tenant(source: TableScope, target: TableScope, fk: Constraint) -> TenancyFinding:
    return finding(
        source.table,
        f"{source.table.qualified} is global, yet its foreign key ({_columns(fk.columns)}) "
        f"→ {target.table.qualified} points at one tenant's row",
        f"move the reference to a tenant table, or make {source.table.qualified} tenant-scoped",
        _line(source, fk),
    )


def _judge(
    scopes: TenantScopes, source: TableScope, target: TableScope, fk: Constraint
) -> TenancyFinding | None:
    """``tenant_004``'s verdict on one foreign key whose two ends are decided."""
    if target.scope not in _TENANT_SIDE or (source.scope is target.scope is Scope.ROOT):
        return None
    if source.scope is Scope.GLOBAL:
        return _global_to_tenant(source, target, fk)
    refs = fk.ref_columns or primary_key(target.table)
    if source.key is None or target.key is None or not refs:
        return None
    if _carries_tenant(fk, refs, source.key, target.key):
        return None
    if target.scope is Scope.ROOT:
        return _root_crossing(source, target, fk, refs, scopes.tenancy.discriminator)
    return _crossing(source, target, fk, refs)


def foreign_key_findings(scopes: TenantScopes) -> Iterator[TenancyFinding]:
    """``tenant_004``: every foreign key that can reach across tenants."""
    for source in scopes:
        if source.scope is Scope.UNDECIDED:
            continue
        for fk in source.table.constraints:
            if fk.kind != "foreign_key":
                continue
            target = scopes.of(fk.ref_table)
            if target is None or target.scope is Scope.UNDECIDED:
                continue
            verdict = _judge(scopes, source, target, fk)
            if verdict is not None:
                yield verdict


def _key_text(entry: TableScope, keys: tuple[str, ...]) -> str:
    """Index or constraint keys as SQL: a column quoted if it must be, an expression as rendered."""
    columns = {c.folded for c in entry.table.columns}
    return ", ".join(quote_identifier(k) if k in columns else k for k in keys)


def _leading(entry: TableScope, keys: tuple[str, ...]) -> tuple[str, ...]:
    """*keys* led by the discriminator: what a key of a tenant table is."""
    key = entry.key or ""
    return (key, *(k for k in keys if k != key))


def _constraint_findings(entry: TableScope) -> Iterator[TenancyFinding]:
    for constraint in entry.table.constraints:
        if constraint.kind not in ("primary_key", "unique") or not constraint.columns:
            continue
        if constraint.columns[0] == entry.key:
            continue
        kind = "PRIMARY KEY" if constraint.kind == "primary_key" else "UNIQUE"
        yield finding(
            entry.table,
            f"{entry.table.qualified}'s {kind} ({_key_text(entry, constraint.columns)}) does "
            f"not lead with {entry.key}: one tenant's row can collide with another's",
            f"{kind} ({_key_text(entry, _leading(entry, constraint.columns))})",
            next((c.line for c in entry.table.columns if c.folded == constraint.columns[0]), None),
        )


def _index_finding(
    scopes: TenantScopes, entry: TableScope, index: Index, site: tuple[str | None, int]
) -> TenancyFinding | None:
    """``tenant_005``'s verdict on one unique index, *site* where its statement begins."""
    declared = site in scopes.declarations
    reason = scopes.declarations.get(site)
    name = index.name or f"the unique index on ({_key_text(entry, index.columns)})"
    directive = f"-- confiture:{GLOBAL_DIRECTIVE}"
    if index.columns[:1] == (entry.key,):
        if not declared:
            return None
        message = f"`{directive}` on {name} is stale: it already leads with {entry.key}"
        fix = "drop the directive"
    elif declared and reason:
        return None
    elif declared:
        message = f"{name} is declared global without a reason"
        fix = f"write why: `{directive} <reason>`"
    else:
        message = (
            f"{name} on {entry.table.qualified} does not lead with {entry.key}: one "
            "tenant's row can collide with another's"
        )
        fix = (
            f"lead with it: ({_key_text(entry, _leading(entry, index.columns))}); or, for a "
            f"uniqueness that is platform-wide on purpose, write `{directive} <reason>` "
            "above the CREATE UNIQUE INDEX"
        )
    return TenancyFinding(entry.table.qualified, site[0], site[1], message, fix)


def _index_findings(scopes: TenantScopes, entry: TableScope) -> Iterator[TenancyFinding]:
    for index in entry.table.indexes:
        if not index.unique or index.backs_constraint or not index.columns:
            continue
        line = entry.table.index_lines.get(index)
        site = scopes.locate(line) if line is not None else (entry.table.file, entry.table.line)
        verdict = _index_finding(scopes, entry, index, site)
        if verdict is not None:
            yield verdict


def unique_key_findings(scopes: TenantScopes) -> Iterator[TenancyFinding]:
    """``tenant_005``: every key of a tenant table that does not lead with the discriminator."""
    for entry in scopes:
        if entry.scope is Scope.TENANT and entry.key is not None:
            yield from _constraint_findings(entry)
            yield from _index_findings(scopes, entry)
