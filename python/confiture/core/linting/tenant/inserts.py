"""Does an ``INSERT`` into a tenant table supply the discriminator (``tenant_001``)?

A routine that writes a row into a tenant table decides which tenant the row
belongs to — or, when the columns it writes leave the discriminator out and the
column has no default, decides nothing, and the row is refused (``NOT NULL``) or
lands with no tenant. A default is a legitimate answer:
``tenant_id uuid NOT NULL DEFAULT current_setting('app.tenant_id')::uuid`` scopes
every write the session makes.

The columns an ``INSERT`` writes are its column list — for ``INSERT … VALUES`` and
``INSERT … SELECT`` alike. Without one, it writes the table's first *N* columns in
the model's order, *N* being what its ``VALUES`` row or its query outputs, counted
by the one column tracer (:func:`~confiture.core.linting.tenant.trace.outputs`), so a
``SELECT *`` over a table the model holds is counted too. ``DEFAULT VALUES`` writes
none.

Which table is a tenant table is what
:func:`~confiture.core.linting.tenant.scope.classify` decided for every rule of the
family — never inferred here. Each routine body is read by
:func:`~confiture.core.linting.references.routine_bodies`, which reads PL/pgSQL
through the one fragment reader. What it cannot read is a finding, never a pass: a
body the compiler refuses, a statement pglast rejects, a string ``EXECUTE`` builds
at run time, a query whose outputs cannot be counted. Each says the ``INSERT`` in it
is not judged.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any

from confiture.core.ddl_walk import walk_nodes
from confiture.core.linting.references import routine_bodies
from confiture.core.linting.tenant.scope import (
    Scope,
    TableScope,
    TenancyFinding,
    TenantScopes,
    object_identity,
)
from confiture.core.linting.tenant.trace import Unread, outputs
from confiture.core.linting.tenant.views import ViewScopes, view_definitions

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.linting.references import BodyStatement, RoutineBody

#: Said of every statement that was not read: what the finding means.
_NOT_JUDGED = "so an INSERT in it is not judged"

#: How a finding names the routine and the table it writes, as ``build_003`` names
#: a referrer and what it names: one baseline entry per pair, not per routine.
_PAIR = " -> "


@dataclass
class _Tree:
    """What judging one ``INSERT`` reads: the scopes, and the tree's relations."""

    scopes: TenantScopes
    inventory: Inventory
    sources: Sequence[tuple[str | None, str]]

    @cached_property
    def relations(self) -> ViewScopes:
        """Each table's columns and each view's outputs, for counting a query's outputs.

        Built on the first ``INSERT`` with no column list into a tenant table: most
        trees have none, and reading every view definition is not free.
        """
        views = [v for label, text in self.sources for v in view_definitions(label, text)]
        return ViewScopes(self.scopes, self.inventory, views, ())

    def target(self, relation: Any) -> TableScope | None:
        """The tenant table an ``INSERT`` writes into, or ``None`` for any other table.

        A missing qualifier matches the table in any schema, as a view's
        references are resolved; a name several schemas hold is judged only when
        every one of them is a tenant table with the same discriminator position.
        """
        found = self.inventory.find_all(("table",), relation.schemaname, relation.relname)
        entries = [self.scopes.tables.get(object_identity(obj)) for obj in found]
        tenant = [e for e in entries if e is not None and e.scope is Scope.TENANT]
        if not tenant or len(tenant) != len(entries):
            return None
        return tenant[0] if len({_position(e) for e in tenant}) == 1 else None


def _position(entry: TableScope) -> int:
    """The discriminator's 0-based position in its table's columns."""
    return next(i for i, c in enumerate(entry.table.columns) if c.folded == entry.key)


def _has_default(entry: TableScope) -> bool:
    """Whether the discriminator fills itself when an ``INSERT`` leaves it out."""
    column = entry.column
    return column is not None and (
        column.default is not None or column.identity is not None or column.generated is not None
    )


def _supplied(insert: Any, tree: _Tree) -> int | Unread:
    """How many leading columns an ``INSERT`` with no column list writes, or why it is unknown."""
    if insert.selectStmt is None:
        return 0
    found = outputs(insert.selectStmt, tree.relations)
    unread = next((c.source for c in found if c.name is None), None)
    if isinstance(unread, Unread):
        return unread
    return len(found)


def _missing(insert: Any, entry: TableScope, tree: _Tree) -> str | None:
    """How the ``INSERT`` leaves the discriminator out, or ``None`` when it supplies it."""
    column = tree.scopes.tenancy.discriminator
    if insert.cols:
        names = [target.name for target in insert.cols]
        return (
            None
            if entry.key in names
            else f"without {column}, which has no default: the row belongs to no tenant"
        )
    supplied = _supplied(insert, tree)
    if isinstance(supplied, Unread):
        return (
            "without a column list, and the columns its query supplies cannot be "
            f"counted ({supplied.reason}), {_NOT_JUDGED}"
        )
    at = _position(entry)
    if supplied > at:
        return None
    return (
        f"without a column list, supplying {supplied} columns by position; {column} is "
        f"column {at + 1} and has no default: the row belongs to no tenant"
    )


def _finding(
    routine: SchemaObject, line: int, message: str, fix: str, table: str | None = None
) -> TenancyFinding:
    name = routine.qualified if table is None else f"{routine.qualified}{_PAIR}{table}"
    return TenancyFinding(name, routine.file, line, message, fix)


def _judge(
    routine: SchemaObject, statement: BodyStatement, insert: Any, tree: _Tree
) -> TenancyFinding | None:
    entry = tree.target(insert.relation)
    if entry is None or entry.key is None or _has_default(entry):
        return None
    why = _missing(insert, entry, tree)
    if why is None:
        return None
    table, column = entry.table.qualified, tree.scopes.tenancy.discriminator
    line = statement.line_at(insert.relation.location) if statement.exact else None
    return _finding(
        routine,
        line or routine.statement_line,
        f"{routine.qualified} inserts into {table} {why}",
        f"name {column} in the INSERT's column list, or give {table}.{column} a default "
        f"(DEFAULT current_setting('app.{column}'))",
        table,
    )


def _unread(body: RoutineBody) -> Iterator[TenancyFinding]:
    """What of *body* was not read: each is a finding, never a pass."""
    routine = body.obj
    fix = "make the statement one pglast reads, or record the finding in a --baseline"
    if body.refused is not None:
        yield _finding(
            routine,
            routine.statement_line,
            f"{routine.qualified}: its body could not be read ({body.refused}), so its "
            "INSERTs are not judged",
            fix,
        )
    for line, _text in body.dynamic:
        yield _finding(
            routine,
            line if body.exact else routine.statement_line,
            f"{routine.qualified}: EXECUTE builds a statement at run time, {_NOT_JUDGED}",
            "write the INSERT as a static statement, or record the finding in a --baseline "
            "once it is reviewed",
        )
    for line, reason in body.unread:
        yield _finding(
            routine,
            line if body.exact else routine.statement_line,
            f"{routine.qualified}: a statement could not be read ({reason}), {_NOT_JUDGED}",
            fix,
        )


def _body_findings(body: RoutineBody, tree: _Tree) -> Iterator[TenancyFinding]:
    yield from _unread(body)
    for statement in body.statements:
        for node in walk_nodes(statement.root):
            if type(node).__name__ == "InsertStmt":
                finding = _judge(body.obj, statement, node, tree)
                if finding is not None:
                    yield finding


def insert_findings(
    scopes: TenantScopes,
    inventory: Inventory,
    sources: Sequence[tuple[str | None, str]],
) -> Iterator[TenancyFinding]:
    """``tenant_001``: every routine ``INSERT`` into a tenant table that leaves the discriminator out.

    Args:
        scopes: Every table's scope, as the family decided it.
        inventory: The tables and views the tree declares, ``ALTER``s folded in.
        sources: ``(file label, text)`` per schema file; each routine is read from its file.
    """
    tree = _Tree(scopes, inventory, sources)
    found: list[TenancyFinding] = []
    for label, text in sources:
        for body in routine_bodies(text):
            body.obj.file = label
            found.extend(_body_findings(body, tree))
    yield from sorted(found, key=lambda f: (f.file or "", f.line))
