"""The one TVIEW read graph: every view, matview, TVIEW and routine the tree keeps, and its chain.

pg_tviews follows a TVIEW's query through the plain views it reads, transitively,
to the tables a write can reach it from; a materialized view and another TVIEW
store their rows, so a chain stops there. A rule asking what a TVIEW's chain
holds — a read of session state (``session_reads``), a walk of a tree
(``tree_walks``) — reads it here: each definition is read once, from both TVIEW
spellings (``CREATE TABLE tv_x AS …`` and ``pg_tviews_create_or_replace()``), as
``build_003`` resolves them, and kept as the build keeps it (``duplicates.wins``).

A holder is a view, a matview, a TVIEW or a routine: its queries (a routine has
one per statement of its body, through :mod:`~confiture.core.linting.references`),
the plain views and routines its text reads, and why some of it was not read. A
chain follows plain views, and routines when the caller asks: pg_tviews sees a
called function's tables only through ``function_reads``, not through the body.
"""

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pglast.parser

from confiture.core import sql_lexer
from confiture.core.ddl_walk import TViewCall, tview_calls, tview_query_tree, walk_nodes
from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    Inventory,
    SchemaObject,
    group_definitions,
    kept,
    object_from_statement,
    split_names,
)
from confiture.core.linting.references import routine_bodies
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import TView
from confiture.core.sql_lexer import ParsedFile

ROUTINE_KINDS = ("function", "procedure")

#: Where a node of a query is written: its offset in the query → a line of its file.
LineAt = Callable[[int | None], int]


@dataclass(frozen=True)
class Query:
    """One parse tree a holder's text holds, and how to place a node of it."""

    root: Any
    file: str | None
    line_at: LineAt


@dataclass
class Holder:
    """A view, a matview, a TVIEW or a routine: what its text holds, and reads next."""

    obj: SchemaObject
    queries: list[Query] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    routines: list[str] = field(default_factory=list)
    #: Why some of its text was not read, or ``None``.
    unread: str | None = None


@dataclass(frozen=True)
class Target:
    """A TVIEW (family ``tview``) or a view or matview (``view``) whose chain is judged."""

    obj: SchemaObject
    family: str
    declared: TView | None = None
    spelled_as_call: bool = False


#: The holders that lead from a target to a holder, in order.
Path = tuple[Holder, ...]


def key(obj: SchemaObject) -> str:
    """A holder's key: a relation by schema and name, a routine by its identity (overloads apart)."""
    if obj.kind in ROUTINE_KINDS:
        return f"routine:{obj.identity}"
    return f"{(obj.folded_schema or DEFAULT_SCHEMA).lower()}.{obj.folded_name}"


class ReadGraph:
    """Every holder's queries and edges, read once; then each target's chain."""

    def __init__(self, files: Sequence[ParsedFile], inventory: Inventory) -> None:
        self.files = files
        self.inventory = inventory
        self.holders: dict[str, Holder] = {}
        self.targets: list[Target] = []

    @classmethod
    def read(cls, files: Sequence[ParsedFile], inventory: Inventory) -> ReadGraph:
        graph = cls(files, inventory)
        built = {(obj.file, obj.offset) for obj in map(kept, group_definitions(inventory.objects))}
        for parsed in files:
            graph._read_file(parsed, built)
        return graph

    def routines_called(self, node: Any) -> list[SchemaObject]:
        """The routines of the tree a ``FuncCall`` may call; a ``pg_catalog`` call calls none."""
        schema, name = split_names(node.funcname)
        if schema == "pg_catalog":
            return []
        return self.inventory.find_all(ROUTINE_KINDS, schema, identifier_identity(name))

    def views_named(self, schema: str | None, name: str) -> list[Holder]:
        """The plain views of the tree a relation name may read, as a ``RangeVar`` holds it."""
        return [
            holder
            for view in self.inventory.find_all(("view",), schema, identifier_identity(name))
            if (holder := self.holders.get(key(view))) is not None
        ]

    def waivers(self, directive: str) -> dict[tuple[str | None, int], list[str] | None]:
        """``-- confiture:<directive> <name>[, <name>]: <why>``, by the statement it sits above.

        The names are folded; a waiver with no reason maps to ``None``: it waives nothing.
        """
        found: dict[tuple[str | None, int], list[str] | None] = {}
        for parsed in self.files:
            for written in sql_lexer.directives(parsed.text):
                if written.name != directive or written.statement_line is None:
                    continue
                names, _, reason = (written.argument or "").partition(":")
                spelled = [folded(n) for n in names.split(",") if n.strip()]
                found[(parsed.label, written.statement_line)] = spelled if reason.strip() else None
        return found

    # -- Reading ---------------------------------------------------------------

    def _read_file(self, parsed: ParsedFile, built: set[tuple[str | None, int]]) -> None:
        text = parsed.text
        for raw in parsed.statements:
            obj = object_from_statement(text, raw)
            if obj is not None and obj.kind in ("view", "matview", "tview"):
                if (parsed.label, parsed.base + obj.offset) not in built:
                    continue
                self._add_query(parsed, obj, raw.stmt.query, lambda at: line(text, at))
            elif obj is None:
                self._add_calls(parsed, raw)
        for body in routine_bodies(parsed):
            if (parsed.label, parsed.base + body.obj.offset) not in built:
                continue
            holder = self._holder(parsed, body.obj)
            if body.refused is not None or body.unread:
                holder.unread = body.refused or "; ".join(reason for _, reason in body.unread)
            for statement in body.statements:
                self._add_tree(holder, Query(statement.root, parsed.label, statement.line_at))

    def _add_calls(self, parsed: ParsedFile, raw: Any) -> None:
        """Each TVIEW a ``SELECT pg_tviews_create…(…)`` creates, its query read where written."""
        for call in tview_calls(raw.stmt):
            if call.action == "drop" or call.name is None or call.written is None:
                continue
            obj = next(
                (
                    o
                    for o in self.inventory.find_all(("tview",), call.schema, call.name)
                    if o.file == parsed.label
                ),
                None,
            )
            if obj is not None:
                self._add_call(parsed, obj, call)

    def _add_call(self, parsed: ParsedFile, obj: SchemaObject, call: TViewCall) -> None:
        written = call.written or ""
        try:
            root = tview_query_tree(written)
        except pglast.parser.ParseError, IndexError:
            # Not read, so not judged: unread() names it.
            self._holder(parsed, obj).unread = "its query does not parse"
            self.targets.append(Target(obj, "tview", obj.tview, spelled_as_call=True))
        else:
            first = line(parsed.text, call.written_at)
            self._add_query(
                parsed,
                obj,
                root,
                lambda at: first + written.count("\n", 0, at or 0),
                call=call,
            )

    def _add_query(
        self,
        parsed: ParsedFile,
        obj: SchemaObject,
        root: Any,
        line_at: LineAt,
        call: TViewCall | None = None,
    ) -> None:
        holder = self._holder(parsed, obj)
        self._add_tree(holder, Query(root, parsed.label, line_at))
        if obj.kind == "tview":
            self.targets.append(
                Target(holder.obj, "tview", obj.tview, spelled_as_call=call is not None)
            )
        else:
            self.targets.append(Target(holder.obj, "view"))

    def _holder(self, parsed: ParsedFile, obj: SchemaObject) -> Holder:
        obj.file = parsed.label
        return self.holders.setdefault(key(obj), Holder(obj))

    def _add_tree(self, holder: Holder, query: Query) -> None:
        """Keep *query* on *holder*, with the plain views and routines it reads."""
        holder.queries.append(query)
        nodes = list(walk_nodes(query.root))
        local = {n.ctename for n in nodes if type(n).__name__ == "CommonTableExpr"}
        for node in nodes:
            kind = type(node).__name__
            if kind == "RangeVar":
                if node.schemaname is None and node.relname in local:
                    continue
                holder.views.extend(
                    key(o)
                    for o in self.inventory.find_all(
                        ("view",), node.schemaname, identifier_identity(node.relname)
                    )
                )
            elif kind == "FuncCall":
                holder.routines.extend(key(r) for r in self.routines_called(node))

    # -- Chains ----------------------------------------------------------------

    def chain(self, target: Target, *, routines: bool = True) -> Iterator[tuple[Holder, Path]]:
        """Each holder *target* reaches, once, with the holders that lead to it first.

        A TVIEW's chain follows the plain views it reads, and the routines they
        call when *routines*; a view's, only the routines its own definition calls.
        """
        seen: set[int] = set()
        pending: deque[tuple[Holder, Path]] = deque([(self.holders[key(target.obj)], ())])
        while pending:
            holder, path = pending.popleft()
            if id(holder) in seen:
                continue
            seen.add(id(holder))
            yield holder, path
            follow = (holder.views if target.family == "tview" else []) + (
                holder.routines if routines else []
            )
            pending.extend(
                (found, (*path, found))
                for found in (self.holders.get(k) for k in follow)
                if found is not None
            )

    def unread(self, targets: Iterable[Target], *, routines: bool = True) -> set[str]:
        """What the chains of *targets* reach and could not read, each named with why."""
        return {
            f"{spelled(holder.obj)} ({holder.unread})"
            for target in targets
            for holder, _ in self.chain(target, routines=routines)
            if holder.unread is not None
        }


def spelled(obj: SchemaObject) -> str:
    """An object as a finding names it: a routine with ``()``."""
    return f"{obj.qualified}()" if obj.kind in ROUTINE_KINDS else obj.qualified


def folded(name: str) -> str:
    """A name as a waiver compares it."""
    return name.strip().lower()


def line(text: str, location: int | None) -> int:
    """The line of *text* an offset falls on; an unknown offset is line 1."""
    if location is None or location < 0:
        return 1
    return text.count("\n", 0, min(location, len(text))) + 1
