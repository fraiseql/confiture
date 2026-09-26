"""Is a table tenant-scoped, global, or undecided — and why (``tenant_002``).

Tenancy is a column, never an inference. A table is **tenant-scoped** because it
carries the discriminator (``tenancy.discriminator``, ``tenant_id`` by default),
``NOT NULL`` and referencing the table of tenants (``tenancy.root``). It is
**global** because ``db/project.yaml`` names its schema in
``tenancy.global_schemas``, or its ``CREATE`` says so: a
``-- confiture:tenant-global <reason>`` line above it. The root is neither — one
of its columns *is* the tenant id (:func:`tenant_id_column`). Anything else is a
decision nobody made, and that is the finding; a declaration is honest or it is a
finding too (a reason is required, and a table declared global cannot also carry
the discriminator).

:func:`classify` decides each table's :class:`Scope` and its tenant-id column once,
and every rule of the family reads that answer: ``tenant_002`` here, ``tenant_003``
in ``views.py``, ``tenant_004`` and ``tenant_005`` in ``keys.py``.

A partition follows its parent: it is judged with the table it belongs to, never
on its own. A table defined twice is judged once, by its first definition
(:func:`~confiture.core.linting.inventory.distinct`); ``build_001`` reports the
duplicate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING

from confiture.core.linting.inventory import distinct
from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_identity

if TYPE_CHECKING:
    from confiture.config.project import TenancyConfig
    from confiture.core.linting.inventory import SchemaColumn, SchemaObject
    from confiture.core.schema_model import Constraint

#: The directive that declares one relation global.
GLOBAL_DIRECTIVE = "tenant-global"

#: ``(file, statement line)`` of each ``tenant-global`` directive, with its reason
#: (``None`` when it gives none).
Declarations = Mapping[tuple[str | None, int], str | None]


class Scope(Enum):
    """What one table is, as far as tenancy goes."""

    #: It carries the discriminator: every row belongs to one tenant.
    TENANT = "tenant"
    #: Its schema is global, or its ``CREATE`` declares it so: shared by every tenant.
    GLOBAL = "global"
    #: ``tenancy.root``, the table of tenants: its key is the tenant id.
    ROOT = "root"
    #: Neither, or both at once — ``tenant_002``'s finding; nothing else judges it.
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class TableScope:
    """One table's scope, and the facts it was decided from."""

    table: SchemaObject
    scope: Scope
    #: The discriminator column, when the table carries it.
    column: SchemaColumn | None
    #: A ``tenant-global`` directive stands above its ``CREATE TABLE``.
    declared: bool
    #: The reason that directive gives.
    reason: str | None
    #: The column that *is* the tenant id: a tenant table's discriminator, the
    #: root's :func:`tenant_id_column`; ``None`` for every other table, and for a
    #: root whose tenant id is undecided.
    key: str | None = None


@dataclass(frozen=True)
class TenantScopes:
    """Every table's scope under one ``tenancy:`` block, keyed by ``(schema, name)``."""

    tenancy: TenancyConfig
    tables: Mapping[tuple[str, str], TableScope]
    declarations: Declarations
    #: ``(file, line)`` of a line of the text the inventory read.
    locate: Callable[[int], tuple[str | None, int]] = lambda line: (None, line)

    def of(self, held: str | None) -> TableScope | None:
        """The scope of the table a foreign key names, as the parser holds it."""
        return self.tables.get(_held_identity(held)) if held is not None else None

    @property
    def root(self) -> TableScope | None:
        """``tenancy.root``, when the tree declares it."""
        return next((entry for entry in self if entry.scope is Scope.ROOT), None)

    def __iter__(self) -> Iterator[TableScope]:
        return iter(self.tables.values())


@dataclass(frozen=True)
class TenancyFinding:
    """A table whose tenancy is undecided or wrong: where, and what to do."""

    table: str
    file: str | None
    line: int
    message: str
    fix: str


def primary_key(table: SchemaObject) -> tuple[str, ...]:
    """The columns of *table*'s primary key, ``()`` when it declares none."""
    return next((c.columns for c in table.constraints if c.kind == "primary_key"), ())


def written_identity(qualified: str) -> tuple[str, str]:
    """``(schema, name)`` of a written ``schema.name`` (or bare ``name``), folded."""
    schema, _, name = qualified.rpartition(".")
    return (identifier_identity(schema) if schema else DEFAULT_SCHEMA, identifier_identity(name))


def _held_identity(held: str) -> tuple[str, str]:
    """``(schema, name)`` of a ``schema.name`` the parser holds: already folded."""
    schema, _, name = held.rpartition(".")
    return (schema or DEFAULT_SCHEMA, name)


def object_identity(obj: SchemaObject) -> tuple[str, str]:
    """``(schema, name)`` of a relation the tree declares, a missing schema defaulted."""
    return (obj.folded_schema or DEFAULT_SCHEMA, obj.folded_name)


def root_identity(tenancy: TenancyConfig) -> tuple[str, str] | None:
    """``(schema, name)`` of the table of tenants, when the project names one."""
    return written_identity(tenancy.root) if tenancy.root else None


def declared_global(obj: SchemaObject, tenancy: TenancyConfig, declarations: Declarations) -> bool:
    """Whether *obj* — a table or a view — is declared global, by its schema or its directive."""
    global_schemas = {identifier_identity(s) for s in tenancy.global_schemas}
    return (
        object_identity(obj)[0] in global_schemas or (obj.file, obj.statement_line) in declarations
    )


def _scope(
    table: SchemaObject,
    column: SchemaColumn | None,
    tenancy: TenancyConfig,
    declarations: Declarations,
) -> Scope:
    if object_identity(table) == root_identity(tenancy):
        return Scope.ROOT
    if declared_global(table, tenancy, declarations):
        return Scope.UNDECIDED if column is not None else Scope.GLOBAL
    return Scope.TENANT if column is not None else Scope.UNDECIDED


def classify(
    tables: Iterable[SchemaObject],
    tenancy: TenancyConfig,
    declarations: Declarations,
    locate: Callable[[int], tuple[str | None, int]] = lambda line: (None, line),
) -> TenantScopes:
    """Every table's scope — partitions and temporary tables left out.

    Args:
        tables: The tables the tree declares, ``ALTER``s folded in.
        tenancy: ``db/project.yaml``'s ``tenancy`` block.
        declarations: The ``tenant-global`` directives, by where they stand.
        locate: ``(file, line)`` of a line of the text *tables* were read from.
    """
    discriminator = identifier_identity(tenancy.discriminator)
    scopes: dict[tuple[str, str], TableScope] = {}
    for table in distinct(tables):
        if table.is_partition or table.is_temporary:
            continue
        column = next((c for c in table.columns if c.folded == discriminator), None)
        scope = _scope(table, column, tenancy, declarations)
        site = (table.file, table.statement_line)
        key = column.folded if scope is Scope.TENANT and column is not None else None
        scopes[object_identity(table)] = TableScope(
            table, scope, column, site in declarations, declarations.get(site), key
        )
    root = root_identity(tenancy)
    if root is not None and root in scopes:
        scopes[root] = replace(scopes[root], key=tenant_id_column(scopes[root].table, scopes))
    return TenantScopes(tenancy, scopes, declarations, locate)


def _root_references(
    table: SchemaObject, column: str, root: tuple[str, str]
) -> Iterator[Constraint]:
    """Each foreign key of *table* that references *root* from *column* alone."""
    for constraint in table.constraints:
        if (
            constraint.kind == "foreign_key"
            and constraint.columns == (column,)
            and constraint.ref_table is not None
            and _held_identity(constraint.ref_table) == root
        ):
            yield constraint


def tenant_id_column(
    root: SchemaObject, tables: Mapping[tuple[str, str], TableScope]
) -> str | None:
    """Which column of the root *is* the tenant id — the one answer the family reads.

    It is the column the discriminator's foreign keys reference: a root may keep a
    surrogate primary key (``id bigint``) beside the tenant id it publishes as a
    ``UNIQUE`` column, and ``tenant_id … REFERENCES root (tenant_uuid)`` says which
    one a tenant row carries. While no discriminator references the root yet, it is
    the root's single-column primary key. ``None`` when the discriminators reference
    different columns of the root, or when there is no reference and no
    single-column primary key: which column is the tenant id is then undecided, and
    is not guessed.
    """
    primary = primary_key(root)
    referenced = {
        ref
        for entry in tables.values()
        if entry.scope is Scope.TENANT and entry.column is not None
        for fk in _root_references(entry.table, entry.column.folded, object_identity(root))
        for ref in fk.ref_columns or primary
    }
    if referenced:
        return referenced.pop() if len(referenced) == 1 else None
    return primary[0] if len(primary) == 1 else None


def finding(table: SchemaObject, message: str, fix: str, line: int | None = None) -> TenancyFinding:
    """A finding on *table*, at *line* or where its name is written."""
    return TenancyFinding(table.qualified, table.file, line or table.line, message, fix)


def _declaration_findings(entry: TableScope, tenancy: TenancyConfig) -> Iterator[TenancyFinding]:
    name = entry.table.qualified
    if entry.declared and not entry.reason:
        yield finding(
            entry.table,
            f"{name} is declared global without a reason",
            f"write why: `-- confiture:{GLOBAL_DIRECTIVE} <reason>`",
        )
    elif entry.column is not None:
        where = (
            f"`confiture:{GLOBAL_DIRECTIVE}` declares it"
            if entry.declared
            else "its schema is in tenancy.global_schemas"
        )
        yield finding(
            entry.table,
            f"{name} is declared global ({where}) yet carries {tenancy.discriminator}",
            f"drop the declaration, or the {tenancy.discriminator} column",
        )


def _column_findings(entry: TableScope, tenancy: TenancyConfig) -> Iterator[TenancyFinding]:
    name, column = entry.table.qualified, entry.column
    if column is None:
        root = f" REFERENCES {tenancy.root}" if tenancy.root else ""
        yield finding(
            entry.table,
            f"{name} has no {tenancy.discriminator} column and is not declared global",
            f"add {tenancy.discriminator} NOT NULL{root}; or declare it global — a "
            f"`-- confiture:{GLOBAL_DIRECTIVE} <reason>` line above the CREATE TABLE, or "
            "its schema in tenancy.global_schemas in db/project.yaml",
        )
    elif not column.not_null:
        yield finding(
            entry.table,
            f"{name}.{tenancy.discriminator} is nullable; it must be NOT NULL: a "
            "tenant-scoped row always has a tenant",
            f"make {tenancy.discriminator} NOT NULL",
            line=column.line,
        )
    elif tenancy.root and not any(
        _root_references(entry.table, column.folded, written_identity(tenancy.root))
    ):
        yield finding(
            entry.table,
            f"{name}.{tenancy.discriminator} does not reference {tenancy.root}, the "
            "table of tenants",
            f"add FOREIGN KEY ({tenancy.discriminator}) REFERENCES {tenancy.root}",
            line=column.line,
        )


def table_findings(scopes: TenantScopes) -> Iterator[TenancyFinding]:
    """``tenant_002``: every table whose tenancy is undecided, or declared in a way that cannot hold."""
    for entry in scopes:
        if entry.scope is Scope.ROOT:
            continue
        if declared_global(entry.table, scopes.tenancy, scopes.declarations):
            yield from _declaration_findings(entry, scopes.tenancy)
        else:
            yield from _column_findings(entry, scopes.tenancy)
