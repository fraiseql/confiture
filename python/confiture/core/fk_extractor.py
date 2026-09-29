"""Two-pass foreign keys: every table first, then every foreign key (``build.two_pass``).

A key written in its ``CREATE TABLE`` fails when the table it references comes
later in the build, and across schemas no file order satisfies every key. Two
passes do: each foreign key is taken out of its ``CREATE TABLE`` and added at
the end with ``ALTER TABLE … ADD``, once every table exists.

A key is read by the one reader (``ddl_walk.read_constraint``) and written by
the one writer (``ddl_clauses.constraint_body``), so the key added at the end is
the key the author wrote. It is cut out of the table by the parser's node
locations, never by matching its text, so a string literal that spells
``REFERENCES`` is a string literal and the comments around the key stay put. A
key the model cannot hold whole (``ddl_walk.model_holds``) stays where it was
written, as does every key of a statement the parser rejects.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pglast
import pglast.parser

from confiture.core import sql_lexer
from confiture.core.ddl_clauses import constraint_body, named, relation
from confiture.core.ddl_walk import (
    CONSTRAINT_READERS,
    enum_int,
    model_holds,
    read_column_constraints,
    read_constraint,
    relation_name,
)
from confiture.core.parser_info import ascii_shadow, is_ascii
from confiture.core.schema_model import Constraint, RelationName

_OPEN, _CLOSE, _COMMA = "ASCII_40", "ASCII_41", "ASCII_44"
_COMMENTS = frozenset({"SQL_COMMENT", "C_COMMENT"})
#: A column constraint node that qualifies the one written before it.
_ATTRIBUTE_PREFIX = "CONSTR_ATTR_"


@dataclass(frozen=True)
class MovedForeignKey:
    """A foreign key taken out of its ``CREATE TABLE``: the table it is on, and the key."""

    table: RelationName
    constraint: Constraint


@dataclass(frozen=True)
class _Cut:
    """One foreign key in a ``CREATE TABLE``: where it starts, and how its text ends."""

    node: Any
    constraint: Constraint
    location: int
    #: The element's index in ``tableElts``, for a table-level key; ``None`` on a column.
    element: int | None
    #: A column key's end: where the next clause on its column starts, or ``None`` for
    #: the end of the column's element.
    until: int | None = None


def _is_attribute(node: Any) -> bool:
    return getattr(node.contype, "name", "").startswith(_ATTRIBUTE_PREFIX)


def _column_cuts(element: Any, *, every: bool) -> Iterator[_Cut]:
    """The foreign keys on one column that move, with the attributes that qualify them.

    *every* takes a key the model cannot hold whole as well.
    """
    clauses = list(element.constraints or ())
    keys = iter(c for c in read_column_constraints(element)[1] if c.kind == "foreign_key")
    for i, node in enumerate(clauses):
        read = read_constraint(node, column=element.colname)
        if not (isinstance(read, Constraint) and read.kind == "foreign_key"):
            continue
        # The column's reader folds the attributes after the key into it.
        key = next(keys)
        after = i + 1
        while after < len(clauses) and _is_attribute(clauses[after]):
            after += 1
        attributes = clauses[i + 1 : after]
        whole = model_holds(node) and all(
            enum_int(a.contype) in CONSTRAINT_READERS for a in attributes
        )
        if not (whole or every):
            continue
        until = clauses[after].location if after < len(clauses) else None
        yield _Cut(node, key, node.location, None, until)


def _cuts(stmt: Any, *, every: bool = False) -> list[_Cut]:
    cuts: list[_Cut] = []
    for index, element in enumerate(stmt.tableElts or ()):
        kind = type(element).__name__
        if kind == "ColumnDef":
            cuts.extend(_column_cuts(element, every=every))
        elif kind == "Constraint" and (every or model_holds(element)):
            read = read_constraint(element)
            if isinstance(read, Constraint) and read.kind == "foreign_key":
                cuts.append(_Cut(element, read, element.location, index))
    return cuts


def movable_keys(stmt: Any) -> list[Any]:
    """The foreign-key nodes of a ``CreateStmt`` that two passes move to the end."""
    if type(stmt).__name__ != "CreateStmt":
        return []
    return [cut.node for cut in _cuts(stmt)]


class _Statement:
    """One ``CREATE TABLE``'s text and tokens, and the spans that take its keys out."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = [t for t in sql_lexer.tokens(text) if t.name not in _COMMENTS]

    def _index_at(self, offset: int) -> int:
        return next(i for i, t in enumerate(self.tokens) if t.start >= offset)

    def _boundary(self, start: int) -> int:
        """The index of the ``,`` or ``)`` that ends the element holding token *start*."""
        depth = 0
        for i in range(start, len(self.tokens)):
            name = self.tokens[i].name
            if name == _OPEN:
                depth += 1
            elif name in (_CLOSE, _COMMA) and depth == 0:
                return i
            elif name == _CLOSE:
                depth -= 1
        return len(self.tokens)

    def _last_end(self, before: int) -> int:
        """Where the last token before token index *before* ends."""
        return self.tokens[before - 1].end + 1

    def _elements(self, stmt: Any) -> list[tuple[int, int]]:
        """Each element's first token index, and the index of the ``,`` or ``)`` after it."""
        first = self._index_at(stmt.relation.location)
        opening = next(i for i in range(first, len(self.tokens)) if self.tokens[i].name == _OPEN)
        spans: list[tuple[int, int]] = []
        start = opening + 1
        while start < len(self.tokens) and self.tokens[start].name != _CLOSE:
            end = self._boundary(start)
            spans.append((start, end))
            if end >= len(self.tokens) or self.tokens[end].name == _CLOSE:
                break
            start = end + 1
        return spans

    def removals(self, stmt: Any, cuts: list[_Cut]) -> list[tuple[int, int]]:
        """The character spans to delete: each key, and the commas its element leaves behind."""
        spans: list[tuple[int, int]] = []
        elements = self._elements(stmt)
        gone = {cut.element for cut in cuts if cut.element is not None}
        kept = [i for i in range(len(elements)) if i not in gone]
        for i, (first, last) in enumerate(elements):
            if i in gone:
                spans.append((self.tokens[first].start, self._last_end(last)))
            separator = last
            if separator < len(self.tokens) and self.tokens[separator].name == _COMMA:
                keeps_comma = i not in gone and any(k > i for k in kept)
                if not keeps_comma:
                    spans.append((self.tokens[separator].start, self.tokens[separator].end + 1))
        for cut in cuts:
            if cut.element is not None:
                continue
            first = self._index_at(cut.location)
            stop = self._index_at(cut.until) if cut.until is not None else self._boundary(first)
            spans.append((cut.location, self._last_end(stop)))
        return [self._tidy(start, end) for start, end in _merged(spans)]

    def _tidy(self, start: int, end: int) -> tuple[int, int]:
        """*start*..*end* with the blanks before it, and its whole line when nothing else is on it."""
        text = self.text
        while start > 0 and text[start - 1] in " \t":
            start -= 1
        if start == 0 or text[start - 1] == "\n":
            rest = end
            while rest < len(text) and text[rest] in " \t":
                rest += 1
            if rest == len(text) or text[rest] == "\n":
                end = min(rest + 1, len(text))
        return start, end


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """*spans* in order, those that touch or overlap joined into one."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _without(text: str, spans: list[tuple[int, int]]) -> str:
    out: list[str] = []
    pos = 0
    for start, end in _merged(spans):
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _parse(text: str) -> Any | None:
    try:
        raws = pglast.parse_sql(text)
    except pglast.parser.ParseError:
        return None
    return raws[0].stmt if len(raws) == 1 else None


def _statement(real: str, shadow: str, *, every: bool) -> tuple[str, list[MovedForeignKey]]:
    """One statement with its movable keys (or *every* key) taken out, and the keys."""
    if "references" not in shadow.lower():
        return real, []
    stmt = _parse(real)
    located = _parse(shadow)
    if stmt is None or located is None or type(stmt).__name__ != "CreateStmt":
        return real, []
    table = relation_name(stmt.relation)
    cuts = _cuts(located, every=every)
    if table is None or not cuts:
        return real, []
    moved = [
        MovedForeignKey(table, cut.constraint)
        for cut in _cuts(stmt, every=every)
        if every or constraint_body(cut.constraint) is not None
    ]
    if len(moved) != len(cuts):
        return real, []
    return _without(real, _Statement(shadow).removals(located, cuts)), moved


def extract_and_strip_fks(sql: str) -> tuple[str, list[MovedForeignKey]]:
    """*sql* with every movable foreign key taken out of its ``CREATE TABLE``, and the keys.

    Everything that is not such a key is kept byte for byte, comments included.
    """
    return _taken_out(sql, every=False)


def without_foreign_keys(sql: str) -> str:
    """*sql* with every foreign key of every ``CREATE TABLE`` gone, movable or not.

    The mutation that asks whether a migration's tests notice a missing key.
    """
    return _taken_out(sql, every=True)[0]


def _taken_out(sql: str, *, every: bool) -> tuple[str, list[MovedForeignKey]]:
    blanked = sql_lexer.blank_copy_blocks(sql)
    shadow = blanked if is_ascii(blanked) else ascii_shadow(blanked)
    out: list[str] = []
    moved: list[MovedForeignKey] = []
    pos = 0
    for span in sql_lexer.statement_spans(blanked):
        out.append(sql[pos : span.start])
        text, keys = _statement(sql[span], shadow[span], every=every)
        out.append(text)
        moved.extend(keys)
        pos = span.stop
    out.append(sql[pos:])
    return "".join(out), moved


def generate_alter_statements(fks: list[MovedForeignKey]) -> str:
    """One ``ALTER TABLE … ADD`` per key, written as the schema model holds it.

    A key the author left unnamed stays unnamed: PostgreSQL names it as it would
    have named it in the ``CREATE TABLE``.
    """
    if not fks:
        return ""
    lines = [
        "-- ============================================",
        "-- Pass 2: Foreign Key Constraints",
        "-- ============================================",
        "",
    ]
    for fk in fks:
        body = constraint_body(fk.constraint) or ""
        lines.append(
            f"ALTER TABLE {relation(fk.table)}\n    ADD {named(fk.constraint.name, body)};\n"
        )
    return "\n".join(lines)
