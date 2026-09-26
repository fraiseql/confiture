"""Does a view publish the tenant discriminator, or is it declared global (``tenant_003``)?

A view's scope is decided in this order:

1. **declared global** — its schema is in ``tenancy.global_schemas``, or a
   ``-- confiture:tenant-global <reason>`` line sits above its ``CREATE``;
2. **tenant-scoped** — it outputs a column named the discriminator that
   :mod:`~confiture.core.linting.tenant.trace` follows, as a plain column, to the
   discriminator of a tenant relation (or the root's tenant id,
   :func:`~confiture.core.linting.tenant.scope.tenant_id_column`);
3. otherwise, if it **reads a tenant relation** — a tenant table, the root, or a
   view that is itself tenant data, directly or through a routine it calls — it is
   the finding;
4. otherwise it reads only global relations and is global without a declaration.

Which table is tenant data is what :func:`~confiture.core.linting.tenant.scope.classify`
decided for every rule of the family; what a view reads is what
:mod:`~confiture.core.linting.references` collects, function bodies included. This
module adds no reader of its own. Views over views are
resolved inner view first, each view's scope computed once. A materialized view is a
view here.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import pglast
import pglast.parser

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.linting.inventory import object_from_statement
from confiture.core.linting.references import RELATION, ROUTINE, read_references
from confiture.core.linting.tenant.scope import (
    GLOBAL_DIRECTIVE,
    Scope,
    TenancyFinding,
    TenantScopes,
    declared_global,
    object_identity,
)
from confiture.core.linting.tenant.trace import (
    Origin,
    Output,
    Source,
    Unread,
    outputs,
    source_of,
)
from confiture.core.schema_identity import identifier_identity

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.linting.references import Reference, ReferenceScan

_MATVIEW = _pg_member("ObjectType", "OBJECT_MATVIEW")
_RELATION_KINDS = ("table", "view", "matview")
_ROUTINE_KINDS = ("function", "procedure")
#: The table scopes whose rows are tenant data.
_TENANT_DATA = frozenset({Scope.TENANT, Scope.ROOT})

Key = tuple[str, str]


@dataclass(frozen=True)
class ViewDefinition:
    """A ``CREATE [MATERIALIZED] VIEW``: the object, its query's tree, its column list."""

    obj: SchemaObject
    query: Any
    aliases: tuple[str, ...] = ()


def view_definitions(label: str | None, text: str) -> list[ViewDefinition]:
    """Every view and materialized view *text* creates, located in file *label*.

    A text pglast rejects yields none: lint reports it once, as ``UNPARSEABLE``.
    """
    try:
        raws = list(pglast.parse_sql(text) or [])
    except pglast.parser.ParseError:
        return []
    found: list[ViewDefinition] = []
    for raw in raws:
        stmt: Any = raw.stmt
        kind = type(stmt).__name__
        if kind == "ViewStmt":
            aliases = stmt.aliases
        elif kind == "CreateTableAsStmt" and int(stmt.objtype) == _MATVIEW:
            aliases = stmt.into.colNames
        else:
            continue
        obj = object_from_statement(text, raw)
        if obj is not None:
            obj.file = label
            found.append(ViewDefinition(obj, stmt.query, tuple(a.sval for a in aliases or ())))
    return found


class Verdict(Enum):
    """What a view is, for tenancy."""

    TRACED = "publishes the discriminator"
    GLOBAL = "global"
    UNPUBLISHED = "reads tenant data without publishing the discriminator"


class ViewScopes:
    """Every view's scope, each computed once, inner views first."""

    def __init__(
        self,
        scopes: TenantScopes,
        inventory: Inventory,
        views: Iterable[ViewDefinition],
        scans: Iterable[ReferenceScan],
    ) -> None:
        self.scopes = scopes
        self.inventory = inventory
        self.tenancy = scopes.tenancy
        self.discriminator = identifier_identity(scopes.tenancy.discriminator)
        self.views = {object_identity(v.obj): v for v in views}
        self.references: dict[str, list[Reference]] = {}
        #: Routines whose body, or a statement in it, no parser returned.
        self.unread_bodies: set[str] = set()
        for scan in scans:
            self.unread_bodies.update(scan.unread)
            self.unread_bodies.update(f.referrer for f in scan.unread_fragments)
            for reference in scan.references:
                self.references.setdefault(reference.referrer, []).append(reference)
        self._outputs: dict[Key, list[Output] | Unread] = {}
        self._verdicts: dict[Key, Verdict] = {}
        self._findings: list[TenancyFinding] = []

    # -- Relations ------------------------------------------------------------

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | Unread:
        """A table's columns, or a view's outputs, as the tracer reads them."""
        found = self.inventory.find_all(_RELATION_KINDS, schema, name)
        if not found:
            return Unread(f"{_spelled(schema, name)} is not in the model")
        key = object_identity(found[0])
        if key in self.views:
            return self._view_outputs(key)
        return [Output(c.folded, Origin(frozenset({(*key, c.folded)}))) for c in found[0].columns]

    def _view_outputs(self, key: Key) -> list[Output] | Unread:
        if key not in self._outputs:
            self._outputs[key] = Unread(f"{_spelled(*key)} reads itself")
            view = self.views[key]
            self._outputs[key] = outputs(view.query, self, view.aliases)
        return self._outputs[key]

    # -- Scope ----------------------------------------------------------------

    def findings(self) -> list[TenancyFinding]:
        """Every view whose tenancy is undecided, or declared in a way that cannot hold."""
        for key in self.views:
            self.verdict(key)
        return sorted(self._findings, key=lambda f: (f.file or "", f.line))

    def verdict(self, key: Key) -> Verdict:
        """The scope of view *key*, computed once; a finding is recorded on the way."""
        if key not in self._verdicts:
            # A view that reads itself through another is judged as global while
            # its own verdict is pending, so the cycle ends.
            self._verdicts[key] = Verdict.GLOBAL
            self._verdicts[key] = self._judge(self.views[key])
        return self._verdicts[key]

    def _judge(self, view: ViewDefinition) -> Verdict:
        read, routines = self._relations_read(view.obj)
        tenant_reads = self._tenant_reads(view.obj, read)
        unread = sorted(routines & self.unread_bodies)
        source = self._discriminator_source(view)
        traced = isinstance(source, Origin) and all(
            self._is_discriminator(column) for column in source.columns
        )
        if declared_global(view.obj, self.tenancy, self.scopes.declarations):
            finding = self._declaration(view, tenant_reads or unread, traced=traced)
            if finding is not None:
                self._findings.append(finding)
            return Verdict.GLOBAL
        if traced:
            return Verdict.TRACED
        if not tenant_reads:
            if unread:
                self._findings.append(self._unread_bodies(view, unread))
            return Verdict.GLOBAL
        self._findings.append(self._unpublished(view, tenant_reads, source))
        return Verdict.UNPUBLISHED

    def _discriminator_source(self, view: ViewDefinition) -> Source:
        found = self._view_outputs(object_identity(view.obj))
        return found if isinstance(found, Unread) else source_of(found, self.discriminator)

    def _is_discriminator(self, column: tuple[str, str, str]) -> bool:
        """Whether *column* is the tenant id of the tenant table (or root) it belongs to."""
        entry = self.scopes.tables.get(column[:2])
        return entry is not None and entry.scope in _TENANT_DATA and column[2] == entry.key

    def _is_tenant(self, key: Key) -> bool:
        if key in self.views:
            return self.verdict(key) is not Verdict.GLOBAL
        entry = self.scopes.tables.get(key)
        return entry is not None and entry.scope in _TENANT_DATA

    def _tenant_reads(self, obj: SchemaObject, read: set[Key]) -> list[str]:
        """The tenant relations among *read*, what *obj* reads."""
        return sorted(
            {_spelled(*key) for key in read if key != object_identity(obj) and self._is_tenant(key)}
        )

    def _relations_read(self, obj: SchemaObject) -> tuple[set[Key], set[str]]:
        """The relations *obj* reads, directly or through the routines it calls; and those routines."""
        read: set[Key] = set()
        seen: set[str] = set()
        pending = [obj.identity]
        while pending:
            referrer = pending.pop()
            if referrer in seen:
                continue
            seen.add(referrer)
            for reference in self.references.get(referrer, ()):
                if reference.kind == RELATION:
                    kinds = _RELATION_KINDS
                elif reference.kind == ROUTINE:
                    kinds = _ROUTINE_KINDS
                else:
                    continue
                for found in self.inventory.find_all(kinds, reference.schema, reference.name):
                    if reference.kind == RELATION:
                        read.add(object_identity(found))
                    else:
                        pending.append(found.identity)
        return read, seen - {obj.identity}

    # -- Findings -------------------------------------------------------------

    def _declaration(
        self, view: ViewDefinition, tenant_reads: list[str], *, traced: bool
    ) -> TenancyFinding | None:
        """A global declaration that cannot hold: no reason, contradicted, or stale."""
        obj, column = view.obj, self.tenancy.discriminator
        declarations = self.scopes.declarations
        directive = (obj.file, obj.statement_line) in declarations
        name, drop = obj.qualified, f"drop the `confiture:{GLOBAL_DIRECTIVE}` line"
        if directive and not declarations[(obj.file, obj.statement_line)]:
            message = f"{name} is declared global without a reason"
            fix = f"write why: `-- confiture:{GLOBAL_DIRECTIVE} <reason>`"
        elif traced:
            where = (
                "`confiture:tenant-global` declares it"
                if directive
                else ("its schema is in tenancy.global_schemas")
            )
            message = f"{name} is declared global ({where}) yet publishes {column}"
            fix = f"drop the declaration, or stop publishing {column}"
        elif directive and not tenant_reads:
            message = (
                f"{name} is declared global but reads no tenant relation: the declaration is stale"
            )
            fix = drop
        else:
            return None
        return TenancyFinding(name, obj.file, obj.statement_line, message, fix)

    def _unpublished(
        self, view: ViewDefinition, tenant_reads: list[str], source: Source
    ) -> TenancyFinding:
        name, column = view.obj.qualified, self.tenancy.discriminator
        reads = ", ".join(tenant_reads)
        if isinstance(source, Unread):
            message = f"{name}.{column} could not be traced ({source.reason}); it reads {reads}"
        elif isinstance(source, Origin):
            message = f"{name}.{column} is {self._not_the_discriminator(source)}; it reads {reads}"
        elif source is None and self._outputs_named(view, self.discriminator):
            message = (
                f"{name}.{column} is not a plain column (an expression over what it "
                f"reads); it reads {reads}"
            )
        else:
            message = f"{name} reads {reads} but publishes no {column} column"
        return TenancyFinding(
            name,
            view.obj.file,
            view.obj.statement_line,
            message,
            f"publish {column} as a plain column of a tenant relation it reads; or declare "
            f"it global — a `-- confiture:{GLOBAL_DIRECTIVE} <reason>` line above the "
            "CREATE VIEW, or its schema in tenancy.global_schemas in db/project.yaml",
        )

    def _unread_bodies(self, view: ViewDefinition, routines: list[str]) -> TenancyFinding:
        obj = view.obj
        return TenancyFinding(
            obj.qualified,
            obj.file,
            obj.statement_line,
            f"{obj.qualified}.{self.tenancy.discriminator} could not be traced (it calls "
            f"{', '.join(routines)}, whose body could not be read, so what it reads is "
            "unknown)",
            "make the routine's body parse, or declare the view global — a "
            f"`-- confiture:{GLOBAL_DIRECTIVE} <reason>` line above the CREATE VIEW",
        )

    def _not_the_discriminator(self, source: Origin) -> str:
        origins = ", ".join(sorted(".".join(c) for c in source.columns))
        root = self.scopes.root
        if root is None or all(c[:2] != object_identity(root.table) for c in source.columns):
            return f"{origins}, which is not the {self.tenancy.discriminator} of a tenant relation"
        key = (
            f"{_spelled(*object_identity(root.table))}.{root.key}"
            if root.key is not None
            else "undecided: the discriminators reference different columns of the root, "
            "or none does and it has no single-column primary key"
        )
        return (
            f"{origins}, which is not the tenant id: the tenant id is {key} (the column "
            f"{self.tenancy.discriminator} references, or else the root's primary key)"
        )

    def _outputs_named(self, view: ViewDefinition, name: str) -> bool:
        found = self._view_outputs(object_identity(view.obj))
        return not isinstance(found, Unread) and any(c.name == name for c in found)


def _spelled(schema: str | None, name: str) -> str:
    return f"{schema}.{name}" if schema else name


def view_findings(
    scopes: TenantScopes,
    inventory: Inventory,
    sources: Sequence[tuple[str | None, str]],
) -> Iterator[TenancyFinding]:
    """Every view that reads tenant data without publishing the discriminator.

    Args:
        scopes: Every table's scope, as the family decided it.
        inventory: The tables and views the tree declares, ``ALTER``s folded in.
        sources: ``(file label, text)`` per schema file: each view's definition and
            what each routine and view body references are read from them.
    """
    views = [v for label, text in sources for v in view_definitions(label, text)]
    scans = [read_references(text) for _label, text in sources]
    yield from ViewScopes(scopes, inventory, views, scans).findings()
