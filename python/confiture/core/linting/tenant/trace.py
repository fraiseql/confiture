"""Where one output column of a view comes from, traced as a plain column (``tenant_003``).

The tracer reads pglast's tree of the view's query — never ``pg_get_viewdef``
text, never a pattern — and follows an output column back through what the query
reads until it names a column of a relation. It answers one of three things:

- :class:`Origin`: the column *is* a column of a relation, unchanged — through
  ``FROM`` aliases, ``JOIN … USING``/``NATURAL`` merged columns, subqueries in
  ``FROM``, CTEs (recursive ones included), ``*`` and ``t.*``, and set operations,
  where the column at the same position traces in every branch and the origin is
  all of them;
- ``None``: it is not a plain column — an expression, a ``COALESCE``, a cast, an
  aggregate, a literal. A value computed from the discriminator is not the
  discriminator;
- :class:`Unread`: the tracer could not tell, and says why — a set-returning
  function in ``FROM``, a relation the model lacks. Never "no origin", never clean.

It is the only module that walks a ``SELECT``'s target list to say where an output
column comes from (``tests/unit/test_one_column_tracer.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from confiture.core._pglast_enums import member as _pg_member

#: ``(schema, relation, column)``, each as the parser folds it.
ColumnId = tuple[str, str, str]

_SETOP_NONE = _pg_member("SetOperation", "SETOP_NONE")
_JOIN_FULL = _pg_member("JoinType", "JOIN_FULL")
_JOIN_RIGHT = _pg_member("JoinType", "JOIN_RIGHT")


@dataclass(frozen=True)
class Origin:
    """The relation columns an output column is, unchanged: one, or one per branch."""

    columns: frozenset[ColumnId]


@dataclass(frozen=True)
class Unread:
    """The tracer could not follow the column, and why."""

    reason: str


#: Where an output column comes from: a plain column, not one (``None``), or unknown.
Source = Origin | Unread | None


@dataclass(frozen=True)
class Output:
    """One output column: the name PostgreSQL gives it, and where it comes from.

    ``name`` is ``None`` for a ``*`` over something unread, whose columns are unknown.
    """

    name: str | None
    source: Source


class Relations(Protocol):
    """What a relation named in ``FROM`` outputs: a table's columns, a view's outputs."""

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | Unread:
        """The relation's output columns in order, or why they are unknown."""
        ...


#: A range's columns, or why they are unknown.
Columns = Sequence[Output] | Unread


@dataclass(frozen=True)
class _Entry:
    """One ``FROM`` element: the ranges a qualified reference can name, and its ``*``."""

    ranges: Mapping[str, Columns]
    star: Columns


class _Scope:
    """The ``FROM`` of one ``SELECT``, and the query around it (a ``LATERAL`` read)."""

    def __init__(self, entries: Sequence[_Entry], parent: _Scope | None) -> None:
        self.entries = entries
        self.parent = parent

    def column(self, name: str) -> Source:
        unread: Unread | None = None
        for entry in self.entries:
            if isinstance(entry.star, Unread):
                unread = unread or entry.star
                continue
            found = next((c for c in entry.star if c.name == name), None)
            if found is not None:
                return found.source
        if unread is not None:
            return unread
        if self.parent is not None:
            return self.parent.column(name)
        return Unread(f"no relation it reads has a column {name}")

    def star(self) -> list[Output]:
        """``*``: every entry's columns in ``FROM`` order; an unread one as one unknown."""
        return [column for entry in self.entries for column in _expanded(entry.star)]

    def star_of(self, qualifier: str) -> list[Output]:
        """``t.*``: the columns of the range named *qualifier*."""
        for entry in self.entries:
            if qualifier in entry.ranges:
                return _expanded(entry.ranges[qualifier])
        if self.parent is not None:
            return self.parent.star_of(qualifier)
        return [Output(None, Unread(f"{qualifier}.* names no relation the query reads"))]

    def qualified(self, qualifier: str, name: str) -> Source:
        for entry in self.entries:
            if qualifier in entry.ranges:
                columns = entry.ranges[qualifier]
                if isinstance(columns, Unread):
                    return columns
                found = next((c for c in columns if c.name == name), None)
                return (
                    found.source
                    if found is not None
                    else Unread(f"{qualifier} has no column {name} in the model")
                )
        if self.parent is not None:
            return self.parent.qualified(qualifier, name)
        return Unread(f"{qualifier}.{name} names no relation the query reads")


def _expanded(columns: Columns) -> list[Output]:
    return [Output(None, columns)] if isinstance(columns, Unread) else list(columns)


#: The CTEs in scope: each name, and its columns.
_Ctes = Mapping[str, Columns]


class _Tracer:
    """One query's walk: its CTEs, its ``FROM``, its target list, its set operations."""

    def __init__(self, relations: Relations) -> None:
        self.relations = relations

    def select(self, stmt: Any, ctes: _Ctes, parent: _Scope | None = None) -> list[Output]:
        ctes = self.with_clause(stmt.withClause, ctes, parent)
        if int(stmt.op) != _SETOP_NONE:
            return _set_operation(
                self.select(stmt.larg, ctes, parent), self.select(stmt.rarg, ctes, parent)
            )
        if stmt.valuesLists:
            return [Output(f"column{i + 1}", None) for i in range(len(stmt.valuesLists[0]))]
        entries: list[_Entry] = []
        for item in stmt.fromClause or ():
            # Each item sees the ones before it: what a LATERAL reference reads.
            entries.append(self.from_item(item, ctes, _Scope(entries, parent)))
        scope = _Scope(entries, parent)
        return [out for target in stmt.targetList or () for out in _target(target, scope)]

    def with_clause(self, clause: Any, ctes: _Ctes, parent: _Scope | None) -> _Ctes:
        if clause is None:
            return ctes
        scoped = dict(ctes)
        for cte in clause.ctes:
            query, names = cte.ctequery, [n.sval for n in cte.aliascolnames or ()]
            if type(query).__name__ != "SelectStmt":
                scoped[cte.ctename] = Unread(f"CTE {cte.ctename} is not a SELECT")
                continue
            if clause.recursive and int(query.op) != _SETOP_NONE:
                # The non-recursive term says what the recursive one reads of itself.
                scoped[cte.ctename] = _renamed(self.select(query.larg, scoped, parent), names)
            scoped[cte.ctename] = _renamed(self.select(query, scoped, parent), names)
        return scoped

    def from_item(self, node: Any, ctes: _Ctes, scope: _Scope) -> _Entry:
        kind = type(node).__name__
        if kind == "RangeVar":
            return self.range_var(node, ctes)
        if kind == "RangeSubselect":
            columns = _renamed(self.select(node.subquery, ctes, scope), _colnames(node))
            return _Entry({_alias(node) or "": columns}, columns)
        if kind == "JoinExpr":
            return self.join(node, ctes, scope)
        reason = _UNREAD_FROM.get(kind, f"a {kind} in FROM")
        return _Entry({_alias(node) or kind: Unread(reason)}, Unread(reason))

    def range_var(self, node: Any, ctes: _Ctes) -> _Entry:
        if node.schemaname is None and node.relname in ctes:
            columns = ctes[node.relname]
        else:
            columns = self.relations.columns(node.schemaname, node.relname)
        if not isinstance(columns, Unread):
            columns = _renamed(columns, _colnames(node))
        return _Entry({_alias(node) or node.relname: columns}, columns)

    def join(self, node: Any, ctes: _Ctes, scope: _Scope) -> _Entry:
        left = self.from_item(node.larg, ctes, scope)
        right = self.from_item(node.rarg, ctes, _Scope([*scope.entries, left], scope.parent))
        star = _joined(left.star, right.star, node)
        if node.alias is None:
            return _Entry({**left.ranges, **right.ranges}, star)
        if not isinstance(star, Unread):
            star = _renamed(star, _colnames(node))
        return _Entry({node.alias.aliasname: star}, star)


#: Why a ``FROM`` item other than a relation, a subquery or a join is not read.
_UNREAD_FROM = {
    "RangeFunction": "a set-returning function in FROM",
    "RangeTableFunc": "an XMLTABLE in FROM",
    "RangeTableSample": "a TABLESAMPLE in FROM",
}


def _joined(left: Columns, right: Columns, node: Any) -> Columns:
    """What ``*`` over a join yields: the merged columns first, then each side's others."""
    if isinstance(left, Unread):
        return left
    if isinstance(right, Unread):
        return right
    if node.isNatural:
        right_names = {c.name for c in right}
        merged = [c.name for c in left if c.name in right_names]
    else:
        merged = [n.sval for n in node.usingClause or ()]
    first = {c.name: c for c in left}
    second = {c.name: c for c in right}
    return [
        *(Output(name, _merged_source(first, second, name, node)) for name in merged),
        *(c for c in left if c.name not in merged),
        *(c for c in right if c.name not in merged),
    ]


def _merged_source(
    left: Mapping[str | None, Output], right: Mapping[str | None, Output], name: str, node: Any
) -> Source:
    """A ``USING`` column: the left side's, the right's for a ``RIGHT`` join, neither for ``FULL``.

    A ``FULL`` join's merged column is ``COALESCE(left, right)`` — not a plain column.
    """
    kind = int(node.jointype)
    if kind == _JOIN_FULL:
        return None
    side = right if kind == _JOIN_RIGHT else left
    column = side.get(name)
    return column.source if column is not None else Unread(f"no side of the join has {name}")


def _set_operation(left: Sequence[Output], right: Sequence[Output]) -> list[Output]:
    """A ``UNION``/``INTERSECT``/``EXCEPT``: a column traces only if it does in every branch."""
    if len(left) != len(right):
        unread = next(
            (c.source for c in (*left, *right) if isinstance(c.source, Unread)),
            Unread("the branches of a set operation output different columns"),
        )
        return [Output(c.name, unread) for c in left]
    return [Output(a.name, _both(a.source, b.source)) for a, b in zip(left, right, strict=True)]


def _both(left: Source, right: Source) -> Source:
    if left is None or right is None:
        return None
    if isinstance(left, Unread):
        return left
    if isinstance(right, Unread):
        return right
    return Origin(left.columns | right.columns)


def _colnames(node: Any) -> list[str]:
    alias = getattr(node, "alias", None)
    return [n.sval for n in (alias.colnames if alias is not None else None) or ()]


def _alias(node: Any) -> str | None:
    alias = getattr(node, "alias", None)
    return alias.aliasname if alias is not None else None


def _target(target: Any, scope: _Scope) -> list[Output]:
    """The output column(s) one target-list entry yields: ``*`` expands to many."""
    value = target.val
    if type(value).__name__ != "ColumnRef":
        return [Output(target.name or _figure_name(value), None)]
    fields = value.fields
    last = fields[-1]
    if type(last).__name__ == "A_Star":
        return scope.star() if len(fields) == 1 else scope.star_of(fields[-2].sval)
    name = last.sval
    source = scope.column(name) if len(fields) == 1 else scope.qualified(fields[-2].sval, name)
    return [Output(target.name or name, source)]


def _figure_name(node: Any) -> str | None:
    """The name PostgreSQL gives an unaliased expression (``FigureColname``), where it gives one."""
    kind = type(node).__name__
    if kind == "TypeCast":
        return _figure_name(node.arg)
    if kind == "ColumnRef" and type(node.fields[-1]).__name__ == "String":
        return node.fields[-1].sval
    if kind == "FuncCall":
        return node.funcname[-1].sval
    return None


def outputs(query: Any, relations: Relations, aliases: Sequence[str] = ()) -> list[Output]:
    """Every output column of *query*, in order, each with where it comes from.

    Args:
        query: The view's ``SelectStmt``, as pglast parsed it.
        relations: The columns of each relation the query may read.
        aliases: The view's column list (``CREATE VIEW v (a, b) AS …``), which
            renames the first outputs.
    """
    return _renamed(_Tracer(relations).select(query, {}), aliases)


def _renamed(columns: Sequence[Output], names: Sequence[str]) -> list[Output]:
    return [
        Output(names[i], column.source) if i < len(names) else column
        for i, column in enumerate(columns)
    ]


def trace(query: Any, column: str, relations: Relations, aliases: Sequence[str] = ()) -> Source:
    """Where *query*'s output column *column* comes from.

    ``None`` when it is not a plain column — or when the query outputs no column of
    that name and every output is known; :class:`Unread` when an output the tracer
    could not expand might be it.
    """
    return source_of(outputs(query, relations, aliases), column)


def source_of(found: Sequence[Output], column: str) -> Source:
    """Where the output named *column* comes from, among *found* (see :func:`trace`)."""
    named = next((c for c in found if c.name == column), None)
    if named is not None:
        return named.source
    return next((c.source for c in found if c.name is None), None)
