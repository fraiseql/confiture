"""A view over a soft-deleting table that never tests its tombstone (``softdel_003``, #632).

A deleted row stays in its table. A view or materialized view that reads such a
table and never tests the tombstone column lists deleted rows, embeds them in live
ones, or counts them. The test is per *read*: every relation a view's query reads
— its ``FROM``, a join, a ``LATERAL`` or ``FROM`` subquery, a CTE, a sub-select in
any clause, every branch of a set operation — that is a soft-deleting table must
have its tombstone column named through that read by a *qualification*: ``WHERE``,
``JOIN … ON``, ``HAVING``, or a sub-select's own. A view that filters its driving
table and embeds a joined one unfiltered still leaks, so a check of the view's text
as a whole would pass what this reports.

Which reference reaches which read is the column tracer's answer
(:mod:`~confiture.core.linting.tenant.trace`): ``FROM (SELECT * FROM t) x WHERE
x.deleted_at IS NULL`` tests ``t``, and a correlated reference resolves outward as
PostgreSQL resolves it. Naming the column in the target list is no test. A view's
reads of other views are not judged: the inner view is, on its own reads. A view
defined twice is judged as the build leaves it (``duplicates.wins``).

A view that keeps deleted rows on purpose — an audit trail, an id resolver — is
waived above its statement, naming the tables the waiver covers, so a later join to
another soft-deleting table is still judged:
``-- confiture:softdel-keeps-deleted tb_order_line, app.tb_order: an audit trail``.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from confiture.core import sql_lexer
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import walk_nodes
from confiture.core.linting.inventory import Inventory, SchemaObject, group_definitions
from confiture.core.linting.soft_delete import SoftDeleteFinding, SoftDeleting
from confiture.core.linting.tenant.trace import (
    Columns,
    Origin,
    Output,
    Source,
    Unread,
    outputs,
)
from confiture.core.linting.tenant.views import ViewDefinition, view_definitions
from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_identity
from confiture.core.sql_lexer import ParsedFile

#: The directive that keeps a view reading deleted rows on purpose.
KEEPS_DELETED = "softdel-keeps-deleted"

_JOIN_LEFT = _pg_member("JoinType", "JOIN_LEFT")
_JOIN_RIGHT = _pg_member("JoinType", "JOIN_RIGHT")

#: Where a tag in an origin's schema slot marks one read of a table: ``@<n>``.
_TAG = "@"


@dataclass
class _Read:
    """One read of a soft-deleting table in a view's query."""

    table: SchemaObject
    node: Any
    tested: bool = False


@dataclass
class _Reads:
    """The tracer's observer: each read of a soft-deleting table, and which are tested."""

    tables: Inventory
    deleting: SoftDeleting
    reads: list[_Read] = field(default_factory=list)
    #: A read's number, by its ``RangeVar``: a CTE walked twice is still one read.
    numbers: dict[int, int] = field(default_factory=dict)

    def relation(self, node: Any, columns: Columns) -> Columns:
        """Tag a soft-deleting table's columns with this read's number."""
        if isinstance(columns, Unread):
            return columns
        found = self.tables.find_all(("table",), node.schemaname, node.relname)
        table = found[0] if found else None
        if (
            table is None
            or not any(c.folded == self.deleting.column for c in table.columns)
            or not self.deleting.judges(table)
        ):
            return columns
        if id(node) not in self.numbers:
            self.numbers[id(node)] = len(self.reads)
            self.reads.append(_Read(table, node))
        tag = f"{_TAG}{self.numbers[id(node)]}"
        return [
            Output(c.name, Origin(frozenset({(tag, table.folded_name, c.name or "")})))
            for c in columns
        ]

    def qualifies(self, source: Source) -> None:
        """Mark every read whose tombstone a qualification names."""
        if not isinstance(source, Origin):
            return
        for schema, _table, column in source.columns:
            if schema.startswith(_TAG) and column == self.deleting.column:
                self.reads[int(schema.removeprefix(_TAG))].tested = True


class _Columns:
    """What a relation outputs, for the tracer: a table's columns; a view is not traced through."""

    def __init__(self, tables: Inventory) -> None:
        self.tables = tables

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | Unread:
        found = self.tables.find_all(("table",), schema, name)
        if not found:
            return Unread(f"{name} is not a table: its own reads are judged on their own")
        table = found[0]
        key = (table.folded_schema or DEFAULT_SCHEMA, table.folded_name)
        return [Output(c.folded, Origin(frozenset({(*key, c.folded)}))) for c in table.columns]


def _alias(node: Any) -> str:
    return node.alias.aliasname if node.alias is not None else node.relname


def _where_the_test_belongs(query: Any, node: Any) -> str:
    """The driving table's ``WHERE``, the nullable side's ``ON``, or inside the sub-select."""
    for join in (n for n in walk_nodes(query) if type(n).__name__ == "JoinExpr"):
        nullable = {_JOIN_LEFT: join.rarg, _JOIN_RIGHT: join.larg}.get(int(join.jointype))
        if nullable is node:
            return (
                "in the LEFT JOIN's ON clause, so the outer row survives with a null embed "
                "(in WHERE it would turn the join into an inner join)"
            )
    top = {id(n) for item in query.fromClause or () for n in walk_nodes(item)}
    sub = {
        id(n)
        for item in query.fromClause or ()
        for s in walk_nodes(item)
        if type(s).__name__ == "RangeSubselect"
        for n in walk_nodes(s.subquery)
    }
    if id(node) in top and id(node) not in sub:
        return "in the view's WHERE"
    return "inside the sub-select or subquery that reads it"


def _waived(directives: dict[int, list[str]], line: int, table: SchemaObject) -> bool:
    """Whether a ``softdel-keeps-deleted`` above the view names *table*."""
    for written in directives.get(line, ()):
        names, _, _reason = written.partition(":")
        for name in names.split(","):
            parts = [identifier_identity(p) for p in sql_lexer.name_parts(name.strip()) or ()]
            if parts[-1:] == [table.folded_name] and (
                len(parts) == 1 or parts[0] == (table.folded_schema or DEFAULT_SCHEMA)
            ):
                return True
    return False


def _keeps_deleted(parsed: ParsedFile) -> dict[int, list[str]]:
    """Statement line → the argument of each ``softdel-keeps-deleted`` above it."""
    found: dict[int, list[str]] = {}
    for directive in sql_lexer.directives(parsed.text):
        if directive.name == KEEPS_DELETED and directive.statement_line is not None:
            found.setdefault(directive.statement_line, []).append(directive.argument or "")
    return found


def _kept(views: Sequence[ViewDefinition]) -> list[ViewDefinition]:
    """Each view as the build leaves it: the definition ``duplicates.wins`` keeps."""
    # Reason: import cycle (duplicates imports schema_linter, which imports this module)
    from confiture.core.linting.duplicates import wins

    by_object = {id(v.obj): v for v in views}
    kept: list[ViewDefinition] = []
    for group in group_definitions(v.obj for v in views):
        verdict = wins(group)
        chosen = group[-1] if verdict == "last" else group[0]
        kept.append(by_object[id(chosen)])
    return kept


def _line(parsed_text: str, location: int) -> int:
    return parsed_text.count("\n", 0, max(location, 0)) + 1


def view_findings(
    inventory: Inventory, files: Sequence[ParsedFile], deleting: SoftDeleting
) -> Iterator[SoftDeleteFinding]:
    """``softdel_003``: every read of a soft-deleting table a view never tests the tombstone of."""
    tables = _inherited(inventory)
    texts = {parsed.label: parsed for parsed in files}
    waivers = {parsed.label: _keeps_deleted(parsed) for parsed in files}
    views = [view for parsed in files for view in view_definitions(parsed)]
    for view in sorted(_kept(views), key=lambda v: (v.obj.file or "", v.obj.line)):
        observer = _Reads(tables, deleting)
        outputs(view.query, _Columns(tables), view.aliases, observer)
        parsed = texts.get(view.obj.file)
        for read in observer.reads:
            if read.tested or _waived(waivers.get(view.obj.file, {}), view.obj.line, read.table):
                continue
            yield _finding(view, read, deleting.column, parsed)


def _inherited(inventory: Inventory) -> Inventory:
    # Reason: a child table reads with the columns it inherits, as softdel_001 reads it
    from confiture.core.linting.inventory import inherit_columns

    return inherit_columns(inventory)


def _finding(
    view: ViewDefinition, read: _Read, column: str, parsed: ParsedFile | None
) -> SoftDeleteFinding:
    alias = _alias(read.node)
    table = read.table.qualified
    kind = "materialized view" if view.obj.kind == "matview" else "view"
    where = _where_the_test_belongs(view.query, read.node)
    line = view.obj.line
    if parsed is not None and read.node.location is not None:
        line = _line(parsed.text, read.node.location)
    return SoftDeleteFinding(
        view.obj.qualified,
        view.obj.file,
        line,
        f"{kind} {view.obj.qualified} reads {table} ({alias}) and never tests "
        f"{alias}.{column}: it shows the rows deleted from {table}",
        f"test {alias}.{column} IS NULL {where}. A view that keeps deleted rows on "
        f"purpose: `-- confiture:{KEEPS_DELETED} {read.table.folded_name}: <why>` above it",
    )
