"""Compiling a PL/pgSQL body with a compiler that has no catalogue (issues #270, #272).

``pglast.parse_plpgsql`` is the only thing that reads a PL/pgSQL body, and it
is the wrong shape twice: the compiler behind it refuses a routine it should
read, and the serialiser behind *that* writes a body it did read as JSON that
does not decode. Both are pglast 8's alone — 6.16 and 7.18, which the ``[ast]``
extra equally accepts, have neither — and both ended in the same place, a
routine ``build_003`` never looked at. So both are answered here, and
:func:`parse_body` is the one place either is.

The catalogue, first.

The ``libpg_query`` build behind ``parse_plpgsql`` is PostgreSQL's own compiler
with the catalogue stubbed out. The stub's ``LookupExplicitNamespace`` resolves ``pg_catalog`` and
``public``; every other schema is ``Not implemented``. So a type name written
``app.mutation_response`` — in a parameter, a return type, a ``SETOF``, a
``RETURNS TABLE`` column or a ``DECLARE`` — makes it refuse the **whole
routine**, before a line of the body is read.

That is not an exotic shape. ``fn(uuid, app.type_x_input, jsonb) RETURNS
app.mutation_response`` is the convention for every mutation in a FraiseQL
schema: 233 of 297 plpgsql routines on the one #270 was filed from, and the 64
that were analysable were the ones without write logic in them.

Nothing downstream of the parse reads a type. :mod:`confiture.core.linting.references`
wants the tree's ``lineno``s and its ``PLpgSQL_expr`` query strings, and a datum's
``typname`` is never consulted by anything. The qualifier is the only part the
compiler looks up, so the qualifier is **blanked with spaces** — every offset and
every line number preserved to the character — and the routine compiles.

Which qualifiers to blank is decided by the compiler, not by a model of
PL/pgSQL's declaration grammar:

- a qualifier it **refuses** is a type, and blanking it costs nothing;
- a qualifier it **accepts** is a reference, and blanking one would turn
  ``app.tv_summary`` into a bare name that ``build_003`` declines to judge —
  #270's silent miss, moved one step along.

Only the compiler can tell those apart with certainty, so only the compiler is
asked. A guess — the signature, plus every ``DECLARE … BEGIN`` region — narrows
the search, and then every blank in it is **tested by putting it back**: if the
statement still compiles without it, it was never needed. The guess is a
performance hint and never the decision, which is what keeps a future change in
where PL/pgSQL writes a type from re-opening this issue.

Finding the candidates is :mod:`confiture.core.sql_lexer`'s work and nobody
else's. A qualified name inside a string literal or a comment must not be
touched, and the scanner is what knows where those end.

The serialiser, second (#272).

A trigger function's implicit ``TG_*`` datums are written ``{}}`` — one closing
brace too many each — so ``json.loads`` never reaches the tree, and *every*
``RETURNS TRIGGER`` and ``RETURNS event_trigger`` body was unread whatever it
contained. Trigger functions are where a schema keeps its audit writes and its
cross-table invariants, so that was not a corner: 5 of the 8 plpgsql routines
in this repository's own corpora.

The same rule decides the repair. The decoder stops at the first character it
cannot accept, so it names the stray brace exactly and nothing has to be
guessed at — see :func:`_compile`, and note that a global replace of those
three characters corrupts an ordinary ``RETURNS void`` body, because that is
also how a legitimate implicit ``RETURN`` is written.

What the two repairs share is the failure they refuse to become. A qualifier
blanked too eagerly, or a brace deleted on a hunch, hands back a tree that is
missing something without saying so — and a routine reported as clean because
it was never read is the bug both of these issues are.

Both are pglast 8's, both are reported upstream as
https://github.com/pganalyze/libpg_query/issues/337, and neither is repaired
here for want of a better place: the ``[ast]`` extra accepts ``pglast>=6.0``
uncapped and confiture cannot ship libpg_query, so a fix that lands upstream
lands in a future wheel and never in the one an installed environment already
has. Both repairs are written to retire themselves rather than to be removed —
a qualifier is blanked only after the compiler refuses the statement as
written, and a brace is deleted only after the decode fails — so on a
libpg_query that has neither defect this module compiles once and returns
``Compiled(tree, statement, (), 0)``.

That issue lists a **third** regression which is deliberately *not* repaired
here: ``RETURN <bare variable>`` comes back with no ``expr`` and no
``retvarno``. Nothing is lost by it — a bare variable is a local, and the
consumers of this module read fragments to find the objects they name — so
there is nothing to reconstruct and no guess worth making. It is written down
because the next reader deserves to know it was looked at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pglast
import pglast.parser

from confiture.core import sql_lexer

#: Schemas the stub resolves. A qualifier naming one of them is never in the way.
RESOLVABLE_SCHEMAS: frozenset[str] = frozenset({"pg_catalog", "public"})

#: The scanner's names for the three tokens a schema qualifier is written with,
#: and for the two that bound a PL/pgSQL declaration section.
_IDENT = "IDENT"
_DOT = "ASCII_46"
_DECLARE = "DECLARE"
_BEGIN = "BEGIN_P"
_STRING = "SCONST"
_AS = "AS"

#: The three characters a mis-serialised datum ends with: an empty object and
#: one closing brace too many. Only ever deleted at the position the JSON
#: decoder stopped at — the same three characters are how *valid* output
#: writes an implicit ``RETURN``, and a global replace corrupts those.
_STRAY = "{}}"

#: A span of the statement text: ``[start, end)``.
Span = tuple[int, int]


@dataclass(frozen=True)
class Compiled:
    """One routine's PL/pgSQL tree, and what the compiler had to be given to get it.

    Attributes:
        tree: What ``pglast.parse_plpgsql`` returned.
        text: The statement as it was finally handed over — equal to the
            statement passed in whenever nothing had to be rewritten.
        neutralised: The schema qualifiers blanked, in source order. Empty on
            every routine the compiler accepts as written, which is what makes
            "nothing was rewritten, so nothing was lost" checkable.
        repaired: Stray closing braces deleted from ``libpg_query``'s
            serialisation before it would decode — one per implicit datum it
            mis-writes. Zero on every routine whose JSON is well formed, which
            is what makes "nothing was deleted, so nothing was invented"
            checkable. Each repaired datum decodes to ``{}``, so the array
            keeps its length and its positions but those entries carry
            nothing: **a datum index is not a fact this tree holds.**
    """

    tree: Any
    text: str
    neutralised: tuple[Span, ...]
    repaired: int = 0


def parse_body(statement: str, *, body_at: int | None = None) -> Compiled:
    """Compile one ``CREATE FUNCTION``/``PROCEDURE`` statement's PL/pgSQL body.

    Args:
        statement: The whole ``CREATE`` statement, which is what the compiler
            needs: a body alone has no signature to declare its parameters.
        body_at: Offset within *statement* of the ``AS`` clause, which the
            caller has from the ``DefElem``'s location. Optional: without it
            the ``AS`` is found in the token stream, which is the same answer
            by a longer route.

    Returns:
        The tree, the text it came from, the qualifiers blanked to get it, and
        the stray braces deleted from the serialisation to decode it.

    Raises:
        pglast.parser.ParseError: The body is unreadable for a reason blanking
            a qualifier does not address. The **first** error is re-raised, not
            the rewritten run's: it is the one that describes the real body.
        json.JSONDecodeError: The serialisation is malformed somewhere that is
            not the stray brace described above, so what it holds is unknown
            and the caller is told rather than handed a guess.
    """
    try:
        tree, repaired = _compile(statement)
    except pglast.parser.ParseError as first:
        refused = first
    else:
        return Compiled(tree, statement, (), repaired)

    candidates = _qualifier_spans(statement, body_at)
    if not candidates:
        raise refused

    blanked = _first_compiling(statement, [_guess(statement, candidates, body_at), candidates])
    if blanked is None:
        raise refused

    kept = _minimised(statement, blanked)
    text = _blank(statement, kept)
    tree, repaired = _compile(text)
    return Compiled(tree, text, tuple(kept), repaired)


def _compile(text: str) -> tuple[Any, int]:
    """*text*'s PL/pgSQL tree, and the stray braces deleted to decode it.

    ``pglast.parse_plpgsql`` is ``json.loads`` over ``libpg_query``'s
    serialisation, and that serialisation is not always valid JSON: a trigger
    function's implicit ``TG_`` datums are written ``{}}``, one closing brace
    too many each, so every ``RETURNS TRIGGER`` and ``RETURNS event_trigger``
    body failed to decode (issue #272, pglast 8 only — 6.16 and 7.18 do not
    write those datums at all).

    The decoder is what says where the defect is. It stops at the first
    character it cannot accept, so ``JSONDecodeError.pos`` names a stray brace
    exactly, and the three characters ending there are checked before one byte
    is deleted. That check is the whole design: ``{"PLpgSQL_stmt_return":{}}``
    — the implicit ``RETURN`` appended to a body that falls off its end — is a
    legitimate ``{}}`` in the output of very nearly every routine, and a global
    replace corrupts an ordinary ``RETURNS void`` function outright.

    A serialisation that decodes never enters the loop, so it is returned
    byte-for-byte whatever it contains. One that does not, and whose defect is
    not this one, raises: half a tree is not a body this module will hand back.
    """
    raw = pglast.parser.parse_plpgsql_json(text)
    repaired = 0
    while True:
        try:
            return json.loads(raw), repaired
        except json.JSONDecodeError as malformed:
            at = malformed.pos
            if at < len(_STRAY) - 1 or raw[at - len(_STRAY) + 1 : at + 1] != _STRAY:
                raise
            raw = raw[:at] + raw[at + 1 :]
            repaired += 1


def _first_compiling(statement: str, attempts: list[list[Span]]) -> list[Span] | None:
    """The first blank set that compiles, or ``None`` when none does.

    The guess first because it is small, then every candidate — so a type
    written somewhere the guess does not look still compiles, one parse later.
    """
    for spans in attempts:
        if spans and _compiles(statement, spans):
            return spans
    return None


def _minimised(statement: str, blanked: list[Span]) -> list[Span]:
    """The blanks that are actually needed, tested one by one by putting them back.

    Every span dropped here is a qualifier the compiler accepts — a reference,
    which must reach the caller written the way its author wrote it. The guess
    over-blanks on purpose and this is where that is paid back.
    """
    kept = list(blanked)
    for span in blanked:
        without = [other for other in kept if other != span]
        if _compiles(statement, without):
            kept = without
    return kept


def _compiles(statement: str, spans: list[Span]) -> bool:
    """Whether blanking *spans* yields a tree — which is the only question here.

    Both exceptions mean the same thing to the oracle: no tree came back, so
    this blank set is not the one. Blanking a qualifier cannot repair a
    serialisation, so a :class:`json.JSONDecodeError` here is a body that will
    not be read whatever is blanked, and :func:`parse_body` re-raises the
    compiler's first refusal — the error that describes the real body.
    """
    try:
        _compile(_blank(statement, spans))
    except (pglast.parser.ParseError, json.JSONDecodeError):
        return False
    return True


def _blank(statement: str, spans: list[Span]) -> str:
    """*statement* with each span replaced by as many spaces as it held.

    Spaces rather than a deletion: ``parse_plpgsql`` numbers a body from its own
    first line and the caller turns those numbers into file lines, so a rewrite
    that moved a single newline would move every finding below it.
    """
    text = list(statement)
    for start, end in spans:
        text[start:end] = " " * (end - start)
    return "".join(text)


def _qualifier_spans(statement: str, body_at: int | None) -> list[Span]:
    """Every ``schema.`` prefix in the statement and in its body, in source order.

    A prefix is an identifier, a dot and an identifier, where the identifier is
    not itself the tail of a longer chain — in ``app.tbl.col`` only ``app.`` is
    removable, and removing it leaves ``tbl.col``, which still means what it
    said. Qualifiers naming a schema the stub resolves are not candidates: they
    are not in the way, and blanking one would be a rewrite with no purpose.
    """
    spans = _prefixes(statement)
    body = _body_span(statement, body_at)
    if body is not None:
        start, end = body
        spans += [(s + start, e + start) for s, e in _prefixes(statement[start:end])]
    return sorted(spans)


def _prefixes(text: str) -> list[Span]:
    tokens = sql_lexer.tokens(text)
    found: list[Span] = []
    for index in range(len(tokens) - 2):
        name, dot, tail = tokens[index : index + 3]
        if name.name != _IDENT or dot.name != _DOT or tail.name != _IDENT:
            continue
        if index and tokens[index - 1].name == _DOT:
            continue
        if _folded(text, name) in RESOLVABLE_SCHEMAS:
            continue
        found.append((name.start, dot.end + 1))
    return found


def _folded(text: str, token: Any) -> str:
    """A schema name as PostgreSQL would compare it."""
    written = text[token.start : token.end + 1]
    return written[1:-1] if written.startswith('"') else written.lower()


def _guess(statement: str, candidates: list[Span], body_at: int | None) -> list[Span]:
    """The candidates worth blanking first: the ones a type can be written in.

    The signature — everything before the body — and every declaration section,
    which is what runs from a ``DECLARE`` to the ``BEGIN`` that ends it, at the
    top of the routine and at the top of each of its sub-blocks. Over-inclusive
    on purpose: an initialiser's ``:= app.fn_default()`` and a cursor's ``FOR
    SELECT … FROM app.tv`` are in a declaration section too, and
    :func:`_minimised` puts those back rather than a rule here guessing at
    where a declaration's type ends.
    """
    body = _body_span(statement, body_at)
    if body is None:
        return candidates
    start, end = body
    regions = [(0, start), *_declaration_regions(statement[start:end], start)]
    return [span for span in candidates if any(low <= span[0] < high for low, high in regions)]


def _declaration_regions(body: str, offset: int) -> list[Span]:
    """``[DECLARE, BEGIN)`` for the body's own block and for each sub-block.

    The body opens in a declaration section — a routine may write its first
    ``DECLARE`` or go straight to ``BEGIN`` — and each ``DECLARE`` below opens
    another. Which token is which is the scanner's answer, so a ``DECLARE``
    inside a string constant or a comment is not one.
    """
    regions: list[Span] = []
    start: int | None = 0
    for token in sql_lexer.tokens(body):
        if token.name == _BEGIN:
            if start is not None:
                regions.append((start + offset, token.start + offset))
                start = None
        elif token.name == _DECLARE:
            start = token.end + 1
    if start is not None:
        regions.append((start + offset, len(body) + offset))
    return regions


def _body_span(statement: str, body_at: int | None) -> Span | None:
    """``[start, end)`` of the body's own text inside *statement*.

    The first string constant at or after the ``AS`` clause, less its
    delimiters — ``'``, ``E'``, ``$$``, ``$tag$``. How long an opening
    delimiter is, is a lexical question with one answer, and it is
    ``sql_lexer``'s.

    Without a *body_at* the ``AS`` is found in the token stream instead. The
    caller's offset is a precision hint, not a prerequisite: a routine's
    declarations are where most of #270's type names are written, and a missing
    argument must not quietly put them out of reach.
    """
    tokens = sql_lexer.tokens(statement)
    at = _as_offset(tokens, body_at)
    if at is None:
        return None
    token = next((t for t in tokens if t.name == _STRING and t.start >= at), None)
    opening = next(
        (start for start_of, start in sql_lexer.string_constants(statement) if start_of >= at),
        None,
    )
    if token is None or opening is None:
        return None
    return (opening, token.end + 1 - (opening - token.start))


def _as_offset(tokens: list[Any], body_at: int | None) -> int | None:
    """Where to start looking for the body: the caller's offset, or the ``AS``."""
    if body_at is not None:
        return body_at if body_at >= 0 else None
    return next(
        (
            token.start
            for token, following in pairwise(tokens)
            if token.name == _AS and following.name == _STRING
        ),
        None,
    )
