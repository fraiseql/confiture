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
PostgreSQL resolves it. Naming the column in the target list is no test. A read is
tested, too, when a qualification that restricts it equates its key — a one-column
primary key or UNIQUE — with the same key of reads of the same table that are all
tested: ``JOIN tb_item cat ON cat.pk = live.pk``, where ``live`` is a filtered CTE (a
recursive one included), reaches only live rows, and so does an aggregate CTE grouped
by the key and joined back on it to a filtered read, and a view whose output column is
that key of a read it tests (#662). A ``LEFT JOIN``'s preserved side is not restricted
by its ``ON``. A view's reads of other views are not judged: the inner view is, on its
own reads. A view defined twice is judged as the build leaves it (``duplicates.wins``).

A read whose rows reach nothing the view outputs is not reported (#662): the nullable
side of an outer join that no output, aggregate or qualification names but the ``ON``
of another such join, in a ``SELECT`` that a duplicated row cannot change —
``GROUP BY`` or ``DISTINCT`` without a counting aggregate, or every such join on its
own one-column key.

An anti-join (``LEFT JOIN t … WHERE t.pk IS NULL``) leaks the other way: a deleted
row still matches and hides the live row it should keep, and the finding says so.

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
    ColumnId,
    Columns,
    Origin,
    Output,
    Source,
    Unread,
    conjuncts,
    outputs,
)
from confiture.core.linting.tenant.views import ViewDefinition, view_definitions
from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_identity
from confiture.core.sql_lexer import ParsedFile

#: The directive that keeps a view reading deleted rows on purpose.
KEEPS_DELETED = "softdel-keeps-deleted"

_JOIN_LEFT = _pg_member("JoinType", "JOIN_LEFT")
_JOIN_RIGHT = _pg_member("JoinType", "JOIN_RIGHT")
_IS_NULL = _pg_member("NullTestType", "IS_NULL")
_AEXPR_OP = _pg_member("A_Expr_Kind", "AEXPR_OP")

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
    views: _Views | None = None
    reads: list[_Read] = field(default_factory=list)
    #: A read's number, by its ``RangeVar`` (and, through a view, the table it keys):
    #: a CTE walked twice is still one read.
    numbers: dict[tuple[int, int], int] = field(default_factory=dict)
    #: Each key-shaped equality a qualification asserts: (restricted side, other side).
    equalities: list[tuple[Origin, Origin]] = field(default_factory=list)

    def relation(self, node: Any, columns: Columns) -> Columns:
        """Tag a soft-deleting table's columns with this read's number."""
        if isinstance(columns, Unread):
            return columns
        found = self.tables.find_all(("table",), node.schemaname, node.relname)
        table = found[0] if found else None
        if table is None:
            return self._through_view(node, columns)
        if not any(
            c.folded == self.deleting.column for c in table.columns
        ) or not self.deleting.judges(table):
            return columns
        tag = self._tag(node, table)
        return [
            Output(c.name, Origin(frozenset({(tag, table.folded_name, c.name or "")})))
            for c in columns
        ]

    def _tag(self, node: Any, table: SchemaObject, *, tested: bool = False) -> str:
        """The tag of the read *node* makes of *table*, numbered on first sight."""
        key = (id(node), id(table))
        if key not in self.numbers:
            self.numbers[key] = len(self.reads)
            self.reads.append(_Read(table, node, tested=tested))
        return f"{_TAG}{self.numbers[key]}"

    def _through_view(self, node: Any, columns: Sequence[Output]) -> Columns:
        """A view's column that is a live key of a table is a tested read of that table.

        The view is judged on its own reads; here it only says which of its outputs
        name live rows, so a key equality to it carries the test (#662).
        """
        live = self.views.live_keys(node.schemaname, node.relname) if self.views else {}
        return [
            Output(
                c.name,
                Origin(
                    frozenset(
                        {
                            (
                                self._tag(node, key.table, tested=True),
                                key.table.folded_name,
                                key.column,
                            )
                        }
                    )
                ),
            )
            if (key := live.get(c.name or "")) is not None
            else c
            for c in columns
        ]

    def qualifies(self, source: Source) -> None:
        """Mark every read whose tombstone a qualification names."""
        if not isinstance(source, Origin):
            return
        for schema, _table, column in source.columns:
            if schema.startswith(_TAG) and column == self.deleting.column:
                self.reads[int(schema.removeprefix(_TAG))].tested = True

    def equal(self, target: Source, through: Source) -> None:
        """Keep an equality between two plain columns; :meth:`carry` judges it."""
        if isinstance(target, Origin) and isinstance(through, Origin):
            self.equalities.append((target, through))

    def carry(self) -> None:
        """Mark each read a key equality ties to tested reads of its table, to a fixpoint.

        An equality ``a = b`` keeps rows whose ``a`` is ``b``: when ``b`` is a live key,
        so is ``a``, and so is every column ``a`` is in turn held equal to — an ``ON``
        inside a CTE says its grouping column is the key of the read it joined. A
        column reached that is that same key of a read of that table is a live row.
        """
        changed = True
        while changed:
            changed = False
            for target, through in self.equalities:
                live = self._key(through)
                if live is None or not all(self.reads[n].tested for n in live.reads):
                    continue
                for n in self._reached(target.columns, live.key):
                    if not self.reads[n].tested:
                        self.reads[n].tested = changed = True

    def _reached(self, start: frozenset[ColumnId], key: tuple[int, str]) -> set[int]:
        """The reads whose *key* column the equalities from *start* hold one value with."""
        reached, frontier = set(start), list(start)
        while frontier:
            column = frontier.pop()
            for target, through in self.equalities:
                if target.columns == {column} and len(through.columns) == 1:
                    (other,) = through.columns
                    if other not in reached:
                        reached.add(other)
                        frontier.append(other)
        reads: set[int] = set()
        for schema, _table, column in reached:
            if schema.startswith(_TAG):
                n = int(schema.removeprefix(_TAG))
                if (id(self.reads[n].table), column) == key:
                    reads.add(n)
        return reads

    def live_key(self, source: Source) -> _LiveKey | None:
        """The table key *source* is, when every read it comes from is tested."""
        if not isinstance(source, Origin):
            return None
        key = self._key(source)
        if key is None or not all(self.reads[n].tested for n in key.reads):
            return None
        return _LiveKey(self.reads[next(iter(key.reads))].table, key.key[1])

    def _key(self, source: Origin) -> _KeyReads | None:
        """The reads *source* is, when each is the same one-column key of one table."""
        tagged = [(s, c) for s, _t, c in source.columns if s.startswith(_TAG)]
        if len(tagged) != len(source.columns):
            return None
        reads = frozenset(int(s.removeprefix(_TAG)) for s, _c in tagged)
        keys = {(id(self.reads[n].table), c) for n in reads for _s, c in tagged}
        if len(keys) != 1:
            return None
        (key,) = keys
        if key[1] not in _keys(self.reads[next(iter(reads))].table):
            return None
        return _KeyReads(reads, key)


@dataclass(frozen=True)
class _KeyReads:
    """Reads of one table whose column, at this point of the query, is one key of it."""

    reads: frozenset[int]
    #: The table (by identity) and the key column.
    key: tuple[int, str]


@dataclass(frozen=True)
class _LiveKey:
    """A one-column key of a soft-deleting table, holding only live rows' values."""

    table: SchemaObject
    column: str


@dataclass(frozen=True)
class _Walk:
    """One view's query, walked: its outputs, and each read the observer saw."""

    outputs: list[Output]
    reads: _Reads


class _Views:
    """The views the build keeps, each walked once, and what each says of its outputs."""

    def __init__(self, tables: Inventory, deleting: SoftDeleting, kept: Sequence[ViewDefinition]):
        self.tables = tables
        self.deleting = deleting
        self.kept = kept
        self.walks: dict[int, _Walk | None] = {}

    def find(self, schema: str | None, name: str) -> ViewDefinition | None:
        """The one kept view a ``RangeVar`` names, a missing schema matching any."""
        found = [
            v
            for v in self.kept
            if v.obj.folded_name == name
            and (schema is None or v.obj.folded_schema in (None, schema))
        ]
        return found[0] if len(found) == 1 else None

    def walked(self, view: ViewDefinition) -> _Walk | None:
        """*view*'s walk, carried to a fixpoint; ``None`` while it is being walked (a cycle)."""
        if id(view) not in self.walks:
            self.walks[id(view)] = None
            reads = _Reads(self.tables, self.deleting, self)
            found = outputs(view.query, _Columns(self.tables, self), view.aliases, reads)
            reads.carry()
            self.walks[id(view)] = _Walk(found, reads)
        return self.walks[id(view)]

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | None:
        """A view's output columns, each its own; ``None`` when it is not one view."""
        view = self.find(schema, name)
        walked = self.walked(view) if view is not None else None
        if view is None or walked is None:
            return None
        key = (view.obj.folded_schema or DEFAULT_SCHEMA, view.obj.folded_name)
        return [
            Output(c.name, Origin(frozenset({(*key, c.name)})) if c.name else c.source)
            for c in walked.outputs
        ]

    def live_keys(self, schema: str | None, name: str) -> dict[str, _LiveKey]:
        """The view's output columns that are a key of a table, holding live rows only."""
        view = self.find(schema, name)
        walked = self.walked(view) if view is not None else None
        if walked is None:
            return {}
        return {
            c.name: key
            for c in walked.outputs
            if c.name and (key := walked.reads.live_key(c.source)) is not None
        }


def _keys(table: SchemaObject) -> set[str]:
    """The table's one-column primary key and UNIQUE columns: each names one row."""
    return {
        identifier_identity(c.columns[0])
        for c in table.constraints
        if c.kind in ("primary_key", "unique") and len(c.columns) == 1
    }


class _Columns:
    """What a relation outputs, for the tracer: a table's columns, a view's own outputs.

    A view is not traced through: its reads are judged on their own.
    """

    def __init__(self, tables: Inventory, views: _Views) -> None:
        self.tables = tables
        self.views = views

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | Unread:
        found = self.tables.find_all(("table",), schema, name)
        if not found:
            viewed = self.views.columns(schema, name)
            if viewed is not None:
                return viewed
            return Unread(f"{name} is not a table: its own reads are judged on their own")
        table = found[0]
        key = (table.folded_schema or DEFAULT_SCHEMA, table.folded_name)
        return [Output(c.folded, Origin(frozenset({(*key, c.folded)}))) for c in table.columns]


def _alias(node: Any) -> str:
    return node.alias.aliasname if node.alias is not None else node.relname


def _nullable_in(query: Any, node: Any) -> Any:
    """The ``SELECT`` whose outer join *node* is the nullable side of, or ``None``."""
    found = None
    for select in (n for n in walk_nodes(query) if type(n).__name__ == "SelectStmt"):
        for join in (
            n
            for item in select.fromClause or ()
            for n in walk_nodes(item)
            if type(n).__name__ == "JoinExpr"
        ):
            if {_JOIN_LEFT: join.rarg, _JOIN_RIGHT: join.larg}.get(int(join.jointype)) is node:
                found = select  # the innermost SELECT holding the join is walked last
    return found


def _anti_join(query: Any, node: Any) -> bool:
    """Whether the ``SELECT`` that outer-joins *node* keeps only rows it did not match."""
    select = _nullable_in(query, node)
    if select is None or select.whereClause is None:
        return False
    alias = _alias(node)
    return any(
        type(term).__name__ == "NullTest"
        and int(term.nulltesttype) == _IS_NULL
        and type(term.arg).__name__ == "ColumnRef"
        and len(term.arg.fields) == 2  # noqa: PLR2004 — ``alias.column``
        and term.arg.fields[0].sval == alias
        for term in conjuncts(select.whereClause)
    )


#: PostgreSQL's own aggregates, measured on 18.4 (``pg_proc``, ``prokind = 'a'``, in
#: ``pg_catalog``): a call by another name is a scalar function, unless the tree
#: creates an aggregate of that name.
_BUILTIN_AGGREGATES = frozenset(
    [
        "any_value",
        "array_agg",
        "avg",
        "bit_and",
        "bit_or",
        "bit_xor",
        "bool_and",
        "bool_or",
        "corr",
        "count",
        "covar_pop",
        "covar_samp",
        "cume_dist",
        "dense_rank",
        "every",
        "json_agg",
        "json_agg_strict",
        "json_object_agg",
        "json_object_agg_strict",
        "json_object_agg_unique",
        "json_object_agg_unique_strict",
        "jsonb_agg",
        "jsonb_agg_strict",
        "jsonb_object_agg",
        "jsonb_object_agg_strict",
        "jsonb_object_agg_unique",
        "jsonb_object_agg_unique_strict",
        "max",
        "min",
        "mode",
        "percent_rank",
        "percentile_cont",
        "percentile_disc",
        "range_agg",
        "range_intersect_agg",
        "rank",
        "regr_avgx",
        "regr_avgy",
        "regr_count",
        "regr_intercept",
        "regr_r2",
        "regr_slope",
        "regr_sxx",
        "regr_sxy",
        "regr_syy",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "string_agg",
        "sum",
        "var_pop",
        "var_samp",
        "variance",
        "xmlagg",
    ]
)
#: Aggregates whose result a duplicated input row does not change.
_DUPLICATE_BLIND = frozenset(
    {"any_value", "min", "max", "bool_and", "bool_or", "every", "bit_and", "bit_or"}
)


def _counts_duplicates(call: Any, tables: Inventory) -> bool:
    """Whether *call* is a window function or an aggregate a duplicated row changes."""
    name = call.funcname[-1].sval
    schema = call.funcname[-2].sval if len(call.funcname) > 1 else None
    aggregate = (
        name in _BUILTIN_AGGREGATES
        or bool(tables.find_all(("aggregate",), schema, name))
        or bool(call.agg_star or call.agg_order or call.agg_filter or call.agg_within_group)
    )
    return call.over is not None or (
        aggregate and not call.agg_distinct and name not in _DUPLICATE_BLIND
    )


def _collapses(select: Any, tables: Inventory) -> bool:
    """Whether *select* outputs a row once however many joined rows produce it.

    ``GROUP BY`` or a plain ``DISTINCT`` (not ``DISTINCT ON``, which keeps one row of
    each set), and no window function nor aggregate a duplicated row changes —
    ``count``, ``sum``, ``jsonb_agg`` do; ``min``, ``max`` and a ``DISTINCT``
    aggregate do not.
    """
    distinct = bool(select.distinctClause) and all(d is None for d in select.distinctClause)
    if not (select.groupClause or distinct):
        return False
    return not any(
        _counts_duplicates(call, tables)
        for clause in (select.targetList, select.havingClause)
        for call in walk_nodes(clause)
        if type(call).__name__ == "FuncCall"
    )


def _outer_joins(item: Any) -> Iterator[tuple[str, Any, Any]]:
    """Each outer join in a ``FROM`` item whose nullable side is a relation: alias, it, the join."""
    if type(item).__name__ != "JoinExpr":
        return
    yield from _outer_joins(item.larg)
    yield from _outer_joins(item.rarg)
    nullable = {_JOIN_LEFT: item.rarg, _JOIN_RIGHT: item.larg}.get(int(item.jointype))
    if type(nullable).__name__ == "RangeVar":
        yield _alias(nullable), nullable, item


def _names(ref: Any, columns: dict[str, frozenset[str] | None]) -> set[str]:
    """The ranges among *columns* a ``ColumnRef`` may read: by qualifier, whole row or name."""
    fields = ref.fields
    if len(fields) > 1:
        return {fields[-2].sval} & columns.keys()
    last = fields[-1]
    if type(last).__name__ != "String":
        return set(columns)  # ``*``: every range
    return {
        alias
        for alias, names in columns.items()
        if alias == last.sval or names is None or last.sval in names
    }


def _on_its_key(alias: str, nullable: Any, join: Any, tables: Inventory) -> bool:
    """Whether the join's ``ON`` equates a one-column key of *nullable* with another range.

    Each outer row then matches one row of it at most: the join multiplies nothing.
    """
    found = tables.find_all(("table",), nullable.schemaname, nullable.relname)
    keys = _keys(found[0]) if found else set()
    for term in conjuncts(join.quals):
        if (
            type(term).__name__ != "A_Expr"
            or int(term.kind) != _AEXPR_OP
            or [n.sval for n in term.name] not in (["="], ["pg_catalog", "="])
        ):
            continue
        sides = [term.lexpr, term.rexpr]
        if any(type(side).__name__ != "ColumnRef" for side in sides):
            continue
        mine = [
            len(side.fields) > 1 and side.fields[-2].sval == alias and side.fields[-1].sval in keys
            for side in sides
        ]
        theirs = [len(side.fields) > 1 and side.fields[-2].sval != alias for side in sides]
        if (mine[0] and theirs[1]) or (mine[1] and theirs[0]):
            return True
    return False


def _without_effect(query: Any, node: Any, tables: Inventory) -> bool:
    """Whether the rows of the outer-joined read *node* reach nothing the view outputs (#662).

    Measured on PostgreSQL 18.4: a relation on the nullable side of an outer join,
    whose columns no output, aggregate or qualification names — but the ``ON`` of
    another such join — only multiplies the rows of the ``SELECT``. Tombstoning its
    rows changes nothing when that ``SELECT`` collapses duplicates, or when it and
    every such join that reads it is on its own one-column key, so none multiplies.
    """
    select = _nullable_in(query, node)
    if select is None:
        return False
    joins = {
        alias: (nullable, join)
        for item in select.fromClause or ()
        for alias, nullable, join in _outer_joins(item)
    }
    alias = _alias(node)
    if alias not in joins or joins[alias][0] is not node:
        return False
    columns: dict[str, frozenset[str] | None] = {}
    for name, (nullable, _join) in joins.items():
        found = tables.find_all(("table",), nullable.schemaname, nullable.relname)
        columns[name] = frozenset(c.folded for c in found[0].columns) if found else None
    within = {id(n): name for name, (_n, join) in joins.items() for n in walk_nodes(join.quals)}
    reads = [
        (within.get(id(n)), _names(n, columns))
        for n in walk_nodes(select)
        if type(n).__name__ == "ColumnRef"
    ]
    free = set(joins)
    changed = True
    while changed:
        changed = False
        for reader, names in reads:
            if reader not in free and names & free:
                free -= names
                changed = True
    if alias not in free:
        return False
    if _collapses(select, tables):
        return True
    chain, frontier = {alias}, [alias]
    while frontier:
        read = frontier.pop()
        for reader, names in reads:
            if read in names and reader is not None and reader not in chain:
                chain.add(reader)
                frontier.append(reader)
    return all(_on_its_key(name, *joins[name], tables) for name in chain)


def _where_the_test_belongs(query: Any, node: Any) -> str:
    """The driving table's ``WHERE``, the nullable side's ``ON``, or inside the sub-select."""
    if _nullable_in(query, node) is not None:
        if _anti_join(query, node):
            return "in the LEFT JOIN's ON clause, so only a live row matches"
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
    kept = _kept([view for parsed in files for view in view_definitions(parsed)])
    views = _Views(tables, deleting, kept)
    for view in sorted(kept, key=lambda v: (v.obj.file or "", v.obj.line)):
        walked = views.walked(view)
        parsed = texts.get(view.obj.file)
        for read in walked.reads.reads if walked is not None else ():
            if (
                read.tested
                or _without_effect(view.query, read.node, tables)
                or _waived(waivers.get(view.obj.file, {}), view.obj.line, read.table)
            ):
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
    leak = (
        f"a row deleted from {table} still matches and hides the live row it should keep"
        if _anti_join(view.query, read.node)
        else f"it shows the rows deleted from {table}"
    )
    return SoftDeleteFinding(
        view.obj.qualified,
        view.obj.file,
        line,
        f"{kind} {view.obj.qualified} reads {table} ({alias}) and never tests "
        f"{alias}.{column}: {leak}",
        f"test {alias}.{column} IS NULL {where}. A view that keeps deleted rows on "
        f"purpose: `-- confiture:{KEEPS_DELETED} {read.table.folded_name}: <why>` above it",
    )
