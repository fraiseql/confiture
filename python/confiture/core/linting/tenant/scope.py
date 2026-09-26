"""Is a table tenant-scoped, global, or undecided — and why (``tenant_002``).

Tenancy is a column, never an inference. A table is **tenant-scoped** because it
carries the discriminator (``tenancy.discriminator``, ``tenant_id`` by default),
``NOT NULL`` and referencing the table of tenants (``tenancy.root``). It is
**global** because ``db/project.yaml`` names its schema in
``tenancy.global_schemas``, or its ``CREATE`` says so: a
``-- confiture:tenant-global <reason>`` line above it. The root is neither — its
key *is* the tenant id. Anything else is a decision nobody made, and that is the
finding; a declaration is honest or it is a finding too (a reason is required, and
a table declared global cannot also carry the discriminator).

A partition follows its parent: it is judged with the table it belongs to, never
on its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_identity

if TYPE_CHECKING:
    from confiture.config.project import TenancyConfig
    from confiture.core.linting.inventory import SchemaObject

#: The directive that declares one relation global.
GLOBAL_DIRECTIVE = "tenant-global"


@dataclass(frozen=True)
class TenancyFinding:
    """A table whose tenancy is undecided or wrong: where, and what to do."""

    table: str
    file: str | None
    line: int
    message: str
    fix: str


def _identity(qualified: str) -> tuple[str, str]:
    """``(schema, name)`` of a written ``schema.name`` (or bare ``name``), folded."""
    schema, _, name = qualified.rpartition(".")
    return (identifier_identity(schema) if schema else DEFAULT_SCHEMA, identifier_identity(name))


def _table_identity(table: SchemaObject) -> tuple[str, str]:
    return (table.folded_schema or DEFAULT_SCHEMA, table.folded_name)


def _references_root(table: SchemaObject, column: str, root: tuple[str, str]) -> bool:
    return any(
        constraint.kind == "foreign_key"
        and tuple(identifier_identity(c) for c in constraint.columns) == (column,)
        and constraint.ref_table is not None
        and _identity(constraint.ref_table) == root
        for constraint in table.constraints
    )


def _finding(
    table: SchemaObject, message: str, fix: str, line: int | None = None
) -> TenancyFinding:
    return TenancyFinding(table.qualified, table.file, line or table.line, message, fix)


def table_findings(
    tables: Iterable[SchemaObject],
    tenancy: TenancyConfig,
    declarations: Mapping[tuple[str | None, int], str | None],
) -> Iterator[TenancyFinding]:
    """Every table whose tenancy is undecided, or declared in a way that cannot hold.

    Args:
        tables: The tables the tree declares, ``ALTER``s folded in.
        tenancy: ``db/project.yaml``'s ``tenancy`` block.
        declarations: ``(file, statement line)`` of each ``tenant-global``
            directive, with its reason (``None`` when it gives none).
    """
    discriminator = identifier_identity(tenancy.discriminator)
    root = _identity(tenancy.root) if tenancy.root else None
    global_schemas = {identifier_identity(s) for s in tenancy.global_schemas}
    fix_scoped = f"add {tenancy.discriminator} NOT NULL" + (
        f" REFERENCES {tenancy.root}" if tenancy.root else ""
    )
    for table in tables:
        if table.is_partition or table.is_temporary or _table_identity(table) == root:
            continue
        column = next((c for c in table.columns if c.folded == discriminator), None)
        declared = (table.file, table.statement_line) in declarations
        reason = declarations.get((table.file, table.statement_line))
        name = table.qualified
        if _table_identity(table)[0] in global_schemas or declared:
            if declared and not reason:
                yield _finding(
                    table,
                    f"{name} is declared global without a reason",
                    f"write why: `-- confiture:{GLOBAL_DIRECTIVE} <reason>`",
                )
            elif column is not None:
                where = (
                    "its schema is in tenancy.global_schemas"
                    if not declared
                    else (f"`confiture:{GLOBAL_DIRECTIVE}` declares it")
                )
                yield _finding(
                    table,
                    f"{name} is declared global ({where}) yet carries {tenancy.discriminator}",
                    f"drop the declaration, or the {tenancy.discriminator} column",
                )
            continue
        if column is None:
            yield _finding(
                table,
                f"{name} has no {tenancy.discriminator} column and is not declared global",
                f"{fix_scoped}; or declare it global — a `-- confiture:{GLOBAL_DIRECTIVE} "
                "<reason>` line above the CREATE TABLE, or its schema in "
                "tenancy.global_schemas in db/project.yaml",
            )
        elif not column.not_null:
            yield _finding(
                table,
                f"{name}.{tenancy.discriminator} is nullable; it must be NOT NULL: a "
                "tenant-scoped row always has a tenant",
                f"make {tenancy.discriminator} NOT NULL",
                line=column.line,
            )
        elif root is not None and not _references_root(table, discriminator, root):
            yield _finding(
                table,
                f"{name}.{tenancy.discriminator} does not reference {tenancy.root}, the "
                "table of tenants",
                f"add FOREIGN KEY ({tenancy.discriminator}) REFERENCES {tenancy.root}",
                line=column.line,
            )
