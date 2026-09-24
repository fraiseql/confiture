"""Every SQL fragment in a compiled PL/pgSQL body, read by the statement it sits in (#363).

:func:`confiture.core.plpgsql_parse.parse_body` returns the compiler's tree, and
the tree holds each embedded piece of SQL as a ``PLpgSQL_expr`` string. A string
alone does not say how to read it. ``SELECT count(*) FROM t`` is a statement,
``v > 0`` an expression, ``v := core.x(p)`` an assignment, ``'SELECT ' || t`` a
statement that only exists at run time. The compiler *does* say which: it puts
each fragment in a named slot of a named node (``cond`` of ``PLpgSQL_stmt_if``,
``sqlstmt`` of ``PLpgSQL_stmt_execsql``). :data:`SLOTS` maps each slot to a
:class:`Mode`, and the mode is how the fragment is parsed. Nothing is tried to
see whether it parses: trying was how every ``v := f(…)`` went unread, because
neither ``v := f()`` nor ``SELECT v := f()`` is SQL.

An assignment is split at its top-level ``:=`` or ``=`` — the first one outside
parentheses and brackets, found in the scanner's tokens, so one inside a string
constant or a comment is not an assignment — and its right-hand side is read as
an expression. The target is kept as written.

What cannot be read is a :attr:`Fragment.finding`, never a dropped fragment: a
slot :data:`SLOTS` does not name, an assignment with no assignment token, or
text pglast rejects. Each consumer reports it in its own terms.

What the compiler does not serialise cannot be read here: a ``record``
variable's default (``r record := f()``) comes back with no ``default_val`` on
every supported pglast, so a call written only there is not seen.

This module is the one walker of a compiled PL/pgSQL tree:
:func:`nodes` yields every node and :func:`fragments` every fragment, and
``tests/unit/test_one_fragment_reader.py`` fails on a module elsewhere that
reads a ``PLpgSQL_expr`` or its ``query``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

import pglast
import pglast.parser

from confiture.core import sql_lexer
from confiture.core.plpgsql_parse import Compiled

#: The key the compiler gives every embedded SQL fragment.
_EXPR = "PLpgSQL_expr"

#: Every node the compiler writes is keyed ``PLpgSQL_<something>``.
_NODE = "PLpgSQL_"

#: The prefix that makes an expression a statement pglast will parse.
_SELECT = "SELECT "


class Mode(StrEnum):
    """How a fragment is parsed, decided by where it sits."""

    #: A whole statement: ``SELECT … INTO``'s query, ``PERFORM``, ``CALL``, a cursor's query.
    STATEMENT = "statement"
    #: A value: a condition, a ``RETURN`` value, a default, a ``USING`` parameter.
    EXPRESSION = "expression"
    #: ``target := value`` (or ``=``): the value is read, the target kept as written.
    ASSIGNMENT = "assignment"
    #: A string ``EXECUTE`` builds at run time: there is nothing to parse until then.
    DYNAMIC = "dynamic"


_S, _E, _A, _D = Mode.STATEMENT, Mode.EXPRESSION, Mode.ASSIGNMENT, Mode.DYNAMIC

#: ``(node, slot)`` → how the fragment in that slot is read. Measured against
#: libpg_query's serialisation on pglast 6.16, 7.18 and 8.4, which agree.
SLOTS: Mapping[tuple[str, str], Mode] = {
    ("PLpgSQL_var", "default_val"): _E,
    ("PLpgSQL_var", "cursor_explicit_expr"): _S,
    ("PLpgSQL_stmt_assign", "expr"): _A,
    ("PLpgSQL_stmt_if", "cond"): _E,
    ("PLpgSQL_if_elsif", "cond"): _E,
    ("PLpgSQL_stmt_case", "t_expr"): _E,
    ("PLpgSQL_case_when", "expr"): _E,
    ("PLpgSQL_stmt_while", "cond"): _E,
    ("PLpgSQL_stmt_exit", "cond"): _E,
    ("PLpgSQL_stmt_fori", "lower"): _E,
    ("PLpgSQL_stmt_fori", "upper"): _E,
    ("PLpgSQL_stmt_fori", "step"): _E,
    ("PLpgSQL_stmt_fors", "query"): _S,
    ("PLpgSQL_stmt_forc", "argquery"): _E,
    ("PLpgSQL_stmt_foreach_a", "expr"): _E,
    ("PLpgSQL_stmt_dynfors", "query"): _D,
    ("PLpgSQL_stmt_dynfors", "params"): _E,
    ("PLpgSQL_stmt_return", "expr"): _E,
    ("PLpgSQL_stmt_return_next", "expr"): _E,
    ("PLpgSQL_stmt_return_query", "query"): _S,
    ("PLpgSQL_stmt_return_query", "dynquery"): _D,
    ("PLpgSQL_stmt_return_query", "params"): _E,
    ("PLpgSQL_stmt_raise", "params"): _E,
    ("PLpgSQL_raise_option", "expr"): _E,
    ("PLpgSQL_stmt_assert", "cond"): _E,
    ("PLpgSQL_stmt_assert", "message"): _E,
    ("PLpgSQL_stmt_execsql", "sqlstmt"): _S,
    ("PLpgSQL_stmt_dynexecute", "query"): _D,
    ("PLpgSQL_stmt_dynexecute", "params"): _E,
    ("PLpgSQL_stmt_perform", "expr"): _S,
    ("PLpgSQL_stmt_call", "expr"): _S,
    ("PLpgSQL_stmt_open", "query"): _S,
    ("PLpgSQL_stmt_open", "dynquery"): _D,
    ("PLpgSQL_stmt_open", "params"): _E,
    ("PLpgSQL_stmt_open", "argquery"): _E,
    ("PLpgSQL_stmt_fetch", "expr"): _E,
}

#: The scanner's names for the tokens that nest and the two that assign.
_OPENERS = frozenset({"ASCII_40", "ASCII_91"})
_CLOSERS = frozenset({"ASCII_41", "ASCII_93"})
_ASSIGNS = frozenset({"COLON_EQUALS", "ASCII_61"})


@dataclass(frozen=True)
class Node:
    """One node of a compiled PL/pgSQL tree: its kind, its fields, its line.

    ``line`` is the node's own ``lineno`` or, for a node the compiler gives
    none (a ``PLpgSQL_case_when``, a raise option), the nearest enclosing one —
    counted from the body's first line.
    """

    kind: str
    fields: Mapping[str, Any]
    line: int


@dataclass(frozen=True)
class Fragment:
    """One SQL fragment, the statement and slot it sits in, and what it parsed to.

    Attributes:
        kind: The node that holds the fragment (``PLpgSQL_stmt_assign``,
            ``PLpgSQL_var``, ``PLpgSQL_case_when`` …).
        slot: The node's field the fragment is in (``expr``, ``cond`` …).
        text: The fragment as the compiler wrote it.
        line: The enclosing statement's line, counted from the body's first.
        node: The holding node's fields, for what else a consumer reads off it
            (``into`` and ``target`` of a ``SELECT … INTO``, a ``then_body``).
        mode: How it was read; ``None`` when :data:`SLOTS` names no reading.
        sql: The text handed to pglast. Locations in :attr:`tree` index into it;
            :meth:`text_offset` and :meth:`line_of` place them in :attr:`text`.
        tree: pglast's ``RawStmt`` list, or ``None`` when nothing was parsed.
        finding: Why nothing was parsed, for a fragment that should have been.
            ``None`` for a parsed fragment and for a dynamic one.
        target: An assignment's target as written (``v``, ``r.x``, ``a[1]``).
    """

    kind: str
    slot: str
    text: str
    line: int
    node: Mapping[str, Any] = field(default_factory=dict, repr=False)
    mode: Mode | None = None
    sql: str | None = None
    tree: tuple[Any, ...] | None = field(default=None, repr=False)
    finding: str | None = None
    target: str | None = None
    _shift: int = field(default=0, repr=False)

    @property
    def dynamic(self) -> bool:
        """Whether the fragment is a string built at run time."""
        return self.mode is Mode.DYNAMIC

    def text_offset(self, location: int) -> int:
        """Where a location in :attr:`tree` falls in :attr:`text`."""
        return location + self._shift

    def line_of(self, location: int | None) -> int:
        """The body line a location in :attr:`tree` is on."""
        if location is None or location < 0:
            return self.line
        return self.line + self.text.count("\n", 0, max(self.text_offset(location), 0))

    @classmethod
    def read(
        cls, *, kind: str, slot: str, text: str, line: int, node: Mapping[str, Any]
    ) -> Fragment:
        """Read one fragment the way its slot says it is written."""
        base = cls(kind=kind, slot=slot, text=text, line=line, node=node)
        mode = SLOTS.get((kind, slot))
        if mode is None:
            return replace(base, finding=f"no reading for {kind}.{slot}")
        if mode is Mode.DYNAMIC:
            return replace(base, mode=mode)
        if mode is Mode.STATEMENT:
            return _parsed(replace(base, mode=mode), text, shift=0)
        if mode is Mode.EXPRESSION:
            return _parsed(replace(base, mode=mode), _SELECT + text, shift=-len(_SELECT))
        split = _assignment(text)
        if split is None:
            return replace(base, mode=mode, finding="no top-level := or = in the assignment")
        target, value_at = split
        read = replace(base, mode=mode, target=target)
        return _parsed(read, _SELECT + text[value_at:], shift=value_at - len(_SELECT))


def nodes(tree: Any, *, line: int = 1) -> Iterator[Node]:
    """Every ``PLpgSQL_*`` node under ``tree``, depth first, in source order."""
    if isinstance(tree, list):
        for item in tree:
            yield from nodes(item, line=line)
        return
    if not isinstance(tree, dict):
        return
    for key, value in tree.items():
        if key.startswith(_NODE) and key != _EXPR and isinstance(value, dict):
            at = value.get("lineno", line)
            yield Node(key, value, at)
            for child in value.values():
                yield from nodes(child, line=at)
        elif isinstance(value, dict | list):
            yield from nodes(value, line=line)


def fragments(compiled: Compiled) -> Iterator[Fragment]:
    """Every SQL fragment in a compiled body, each read by the slot it sits in."""
    for node in nodes(compiled.tree):
        for slot, value in node.fields.items():
            for text in _expressions(value):
                yield Fragment.read(
                    kind=node.kind, slot=slot, text=text, line=node.line, node=node.fields
                )


def _expressions(value: Any) -> Iterator[str]:
    """The query strings a slot holds directly: one ``PLpgSQL_expr`` or a list of them."""
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict) and isinstance(item.get(_EXPR), dict):
            query = item[_EXPR].get("query")
            if query:
                yield query


def _parsed(fragment: Fragment, sql: str, *, shift: int) -> Fragment:
    """``fragment`` with ``sql``'s parse tree, or with pglast's refusal as its finding."""
    try:
        tree = tuple(pglast.parse_sql(sql) or ())
    except pglast.parser.ParseError as refused:
        return replace(fragment, sql=sql, finding=str(refused), _shift=shift)
    return replace(fragment, sql=sql, tree=tree, _shift=shift)


def _assignment(text: str) -> tuple[str, int] | None:
    """``(target as written, offset of the value)``, or ``None`` with no assignment token.

    The first ``:=`` or ``=`` outside parentheses and brackets. The target
    comes first and cannot hold one at that depth (``a[i = 1]`` is inside a
    bracket), so the first is the assignment and any later ``=`` is the value's.
    """
    depth = 0
    for token in sql_lexer.tokens(text):
        if token.name in _OPENERS:
            depth += 1
        elif token.name in _CLOSERS:
            depth -= 1
        elif depth == 0 and token.name in _ASSIGNS:
            return text[: token.start].strip(), token.end + 1
    return None
