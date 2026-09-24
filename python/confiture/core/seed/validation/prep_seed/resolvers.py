"""The resolution functions a schema defines: found by name, never by file name (#385).

A resolver is a routine whose own name starts ``fn_resolve`` — folded, so
``Fn_Resolve_X`` is one and so is a quoted ``"Fn_resolve_X"`` — wherever its
``CREATE`` is written. A tree that names its files ``019201004_fn_resolve_tb_x.sql``,
or keeps every resolver in one file, holds the same resolvers as one that names
each file after its function.

Each resolver carries the file and line it is written on, which every level
that reports on it names, and its identity as PostgreSQL holds it: pglast has
already folded an unquoted name and kept a quoted one's case, so
:attr:`Resolver.identifier` calls exactly the routine the DDL created.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import sql

from confiture.core.introspection.dependency_graph import dependency_order
from confiture.core.linting import references
from confiture.core.schema_sources import SchemaRead
from confiture.exceptions import SchemaError

#: What a resolver's name starts with.
PREFIX = "fn_resolve"

#: What a resolver's name starts with once its table is named: ``fn_resolve_tb_x``.
TABLE_PREFIX = f"{PREFIX}_"

#: The inventory kinds a resolver can be.
_ROUTINE_KINDS = frozenset({"function", "procedure"})


@dataclass(frozen=True)
class Resolver:
    """One resolution function, where it is written, and its body as read.

    Attributes:
        schema: The schema its ``CREATE`` names, or ``None`` when it names none.
        name: Its name as PostgreSQL holds it.
        file: The file it is written in; empty for DDL handed in as text.
        line: The line of that file its ``CREATE`` begins on.
        body: Its body, read by :func:`~confiture.core.linting.references.read_body`.
            The body's lines count the schema's joined text; :meth:`where`
            places one on :attr:`file`.
    """

    schema: str | None
    name: str
    file: str
    line: int
    body: references.RoutineBody
    _shift: int = field(default=0, repr=False)

    @property
    def table(self) -> str:
        """The table it fills, by the ``fn_resolve_<table>`` convention."""
        return self.name.lower().removeprefix(TABLE_PREFIX)

    @property
    def identifier(self) -> sql.Identifier:
        """The routine as SQL names it: schema-qualified when its ``CREATE`` was."""
        parts = (self.schema, self.name) if self.schema else (self.name,)
        return sql.Identifier(*parts)

    def where(self, line: int | None = None) -> tuple[str, int]:
        """``(file, line)`` for a finding at *line* of the body, or at the ``CREATE``.

        A body whose lines are its own rather than the file's (its opening
        quote could not be found) is placed at the ``CREATE``: the routine's
        line is a worse answer than the statement's, and a much better one than
        a wrong line.
        """
        if line is None or not self.body.exact:
            return self.file, self.line
        return self.file, line - self._shift


def find_resolvers(read: SchemaRead, *, catalog_schema: str) -> list[Resolver]:
    """Every resolver *read*'s schema defines, parents first.

    ``fn_resolve_<table>`` fills ``<catalog>.<table>`` and joins the tables that
    table references, so it runs after their resolvers: the catalog tables'
    foreign-key order decides, and a resolver of no catalog table follows in name
    order. Keys that form a cycle leave the name order.
    """
    found: list[Resolver] = []
    for definition in read.definitions:
        obj = definition.obj
        if obj.kind not in _ROUTINE_KINDS or not obj.folded_name.lower().startswith(PREFIX):
            continue
        found.append(
            Resolver(
                schema=obj.folded_schema,
                name=obj.folded_name,
                file="" if definition.file is None else str(definition.file),
                line=definition.line,
                body=references.read_body(read.text, definition.statement, obj),
                _shift=obj.statement_line - definition.line,
            )
        )
    return _parents_first(found, read, catalog_schema)


def _parents_first(resolvers: list[Resolver], read: SchemaRead, catalog: str) -> list[Resolver]:
    by_name = sorted(resolvers, key=lambda resolver: resolver.name)
    try:
        order = dependency_order(read.model)
    except SchemaError:
        return by_name
    rank = {ref.name: position for position, ref in enumerate(order) if ref.schema == catalog}
    return sorted(by_name, key=lambda resolver: rank.get(resolver.table, len(rank)))
