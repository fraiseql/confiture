"""What a body names, so the build can be asked whether it creates it (#246).

``build_001`` proves confiture holds a complete inventory of what a build
*creates* — it has to, to know that something is created twice. Nothing ever
read it in the other direction: a routine that selects from a table no file
creates, or calls a function no file creates, builds and lints in silence.

This module is the missing half — the objects a body *references*:

- a PL/pgSQL body through ``pglast.parse_plpgsql``, which hands back every
  embedded SQL fragment as a ``PLpgSQL_expr.query`` string together with the
  line it is written on, each fragment going back through
  ``pglast.parser.parse_sql``;
- a ``LANGUAGE sql`` body and a view definition directly, because they are SQL
  already.

One walker then collects ``RangeVar`` (a relation) and ``FuncCall`` (a routine)
from whatever came back. The issue that asked for this says of its own
hand-rolled regex version that it "is crude and misses plenty", and that the
value of doing it here is the parser and the inventory — so what a parser
cannot resolve is *declared* unresolvable rather than guessed at: an
``EXECUTE`` of a string built at run time comes back as a reference marked
:attr:`Reference.dynamic`, which the rule drops explicitly.

Lines are counted in the frame of the text handed to
:func:`referenced_objects`. A body is the one place that needs work:
``parse_plpgsql`` counts from the body's own first line, so the body's opening
delimiter is located through ``sql_lexer.string_constants`` and its line added
back. Where that fails, the reference is marked inexact rather than pointed at
the wrong line — the routine's own line is a worse answer than the statement's
and a much better one than a line three short of it.

That conversion is not only this rule's problem: ``plpgsql_check`` numbers its
diagnoses from the body's first line too (#245). So the two halves of it are
public — :func:`body_locations` says where each routine's body starts in its
file, and :func:`file_line` places a body-relative line on that file — and
there is one answer to "which line is this, really", not two.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pglast
import pglast.parser

from confiture.core import sql_lexer
from confiture.core.ddl_walk import routine_body, walk_nodes
from confiture.core.linting.inventory import SchemaObject, object_from_statement, split_names

#: A relation: a table, view, materialized view or sequence a statement reads
#: or writes. ``RangeVar`` is how every one of them appears.
RELATION = "relation"

#: A routine: a function, procedure or aggregate a statement calls.
ROUTINE = "routine"

#: Not an object at all — a statement built at run time, kept so the rule can
#: decline it out loud instead of missing it quietly.
DYNAMIC = "dynamic"

#: The languages whose bodies are SQL confiture can parse. Everything else —
#: ``c``, ``internal``, ``plpython3u``, ``plperl`` — has a body that is not SQL.
_SQL_LANGUAGES = frozenset({"sql", "plpgsql"})

#: PL/pgSQL statements whose query is a string assembled at run time.
_DYNAMIC_STATEMENTS = frozenset({"PLpgSQL_stmt_dynexecute", "PLpgSQL_stmt_dynfors"})

#: The key libpg_query's PL/pgSQL parser gives every embedded SQL fragment.
_EXPR = "PLpgSQL_expr"

#: Inventory kinds whose ``CREATE`` carries a body written in a string constant.
_ROUTINE_KINDS = frozenset({"function", "procedure"})


@dataclass(frozen=True)
class Reference:
    """One object a body names, and where it names it.

    ``schema`` is ``None`` when the author wrote no qualifier — which is most
    of what a body contains (``now()``, a record variable, a local), and why
    resolving an unqualified name needs a declared ``search_path`` rather than
    a guess. ``line`` is 1-based in the frame described in the module
    docstring; ``line_is_exact`` is false when the line is counted in a body's
    own frame rather than the file's, and ``referrer_line`` — where the
    referring ``CREATE`` begins — is then the only line a reader can open.
    """

    schema: str | None
    name: str
    kind: str
    line: int
    referrer: str
    referrer_kind: str
    referrer_line: int = 1
    dynamic: bool = False
    line_is_exact: bool = True

    @property
    def qualified(self) -> str:
        """``schema.name`` as written, or the bare name when none was."""
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass(frozen=True)
class BodyLocation:
    """A routine, and the file line its body starts on.

    ``first_line`` is ``None`` when the opening delimiter could not be found,
    which is what makes a line derived from it inexact rather than wrong.
    """

    obj: SchemaObject
    first_line: int | None


def body_locations(sql: str) -> list[BodyLocation]:
    """Every routine ``sql`` creates, with the file line its body starts on.

    The same walk :func:`referenced_objects` makes, stopping at the question
    "where is this body written" — which is what a diagnosis counted from the
    body's first line needs in order to name a file line.
    """
    try:
        raws = list(pglast.parse_sql(sql) or [])
    except pglast.parser.ParseError:
        return []
    constants = _string_constants(sql)
    found: list[BodyLocation] = []
    for raw in raws:
        obj = object_from_statement(sql, raw)
        if obj is not None and obj.kind in _ROUTINE_KINDS:
            found.append(BodyLocation(obj, _body_line(sql, raw.stmt, constants)))
    return found


def file_line(body_line: int, first: int | None) -> int:
    """A line counted from a body's first line, placed on the file it is written in.

    ``parse_plpgsql`` and ``plpgsql_check`` both number a body from its own
    first line — the one after the opening delimiter — so both need the same
    single addition, and neither should carry its own copy of it. Without a
    known first line the body's own number is the best available answer, and the
    caller says so rather than implying the file.
    """
    return body_line if first is None else body_line + first - 1


def referenced_objects(sql: str) -> list[Reference]:
    """Every object the routine and view bodies in ``sql`` name, in source order.

    A text pglast rejects yields nothing: the linter already reports a parse
    failure once, as its ``UNPARSEABLE`` notice, and a second report of the
    same fact from every rule would be noise.
    """
    try:
        raws = list(pglast.parse_sql(sql) or [])
    except pglast.parser.ParseError:
        return []
    # Scanned once for the whole text: a body's first line is a lexical
    # question, and asking it per routine would make the cost quadratic.
    constants = _string_constants(sql)
    found: list[Reference] = []
    for raw in raws:
        obj = object_from_statement(sql, raw)
        reader = None if obj is None else _READERS.get(obj.kind)
        if obj is not None and reader is not None:
            found.extend(reader(sql, raw, obj, constants))
    return found


def _string_constants(sql: str) -> list[tuple[int, int]]:
    try:
        return sql_lexer.string_constants(sql)
    except (ValueError, IndexError):
        return []


def _body_line(sql: str, stmt: Any, constants: list[tuple[int, int]]) -> int | None:
    """The file line the routine's body starts on, or ``None`` when it cannot be found.

    ``parse_plpgsql`` numbers a body from its first line, which is whatever
    follows the opening ``$$`` — so the line to add back is the line of the
    first string constant at or after the ``AS`` clause.
    """
    at = next(
        (opt.location for opt in getattr(stmt, "options", None) or () if opt.defname == "as"),
        None,
    )
    if at is None or at < 0:
        return None
    content = next((start for token, start in constants if token >= at), None)
    return None if content is None else _line_of(sql, content)


def _statement_text(sql: str, raw: Any) -> str:
    """The one statement's own text: what ``parse_plpgsql`` has to be given.

    ``stmt_len`` is 0 for a final statement written without its semicolon.
    """
    start = raw.stmt_location or 0
    length = raw.stmt_len or 0
    return sql[start : start + length] if length else sql[start:]


def _routine_references(
    sql: str, raw: Any, obj: SchemaObject, constants: list[tuple[int, int]]
) -> list[Reference]:
    """A function or procedure body, read by whichever parser its language needs."""
    stmt = raw.stmt
    language, body = routine_body(stmt)
    if getattr(stmt, "sql_body", None) is not None:
        # `BEGIN ATOMIC … END`: parsed with the statement, so its locations are
        # already offsets into `sql`.
        return _from_nodes(sql, stmt.sql_body, obj)
    if language not in _SQL_LANGUAGES or body is None:
        return []
    first = _body_line(sql, stmt, constants)
    if language == "sql":
        # The body is one SQL text: each reference keeps its own line in it,
        # shifted onto the file by where the body starts.
        return _from_text(body, obj, shift=(first - 1) if first else 0, exact=first is not None)
    return _plpgsql_references(_statement_text(sql, raw), obj, first=first)


def _query_references(
    sql: str, raw: Any, obj: SchemaObject, _constants: list[tuple[int, int]]
) -> list[Reference]:
    """A view or materialized view: its query was parsed with the statement."""
    return _from_nodes(sql, raw.stmt.query, obj)


#: Which reader each inventory kind needs. A kind that is absent has no body.
_READERS: dict[str, Callable[[str, Any, SchemaObject, list[tuple[int, int]]], list[Reference]]] = {
    "function": _routine_references,
    "procedure": _routine_references,
    "view": _query_references,
    "matview": _query_references,
}


def _plpgsql_references(statement: str, obj: SchemaObject, *, first: int | None) -> list[Reference]:
    """Every fragment libpg_query's PL/pgSQL parser found, re-parsed as SQL.

    ``parse_plpgsql`` counts from the body's first line, so *first* — that
    line's number in the file — turns each ``lineno`` into a file line. Without
    it the reference is inexact and reports the routine's line instead. A
    fragment marked dynamic yields one dynamic reference and nothing is read
    out of the string it would have built.
    """
    try:
        tree = pglast.parse_plpgsql(statement)
    except pglast.parser.ParseError:
        return []
    found: list[Reference] = []
    exact = first is not None
    for query, line, dynamic in _fragments(tree, line=1, dynamic=False):
        at = file_line(line, first)
        if dynamic:
            found.append(_reference(None, query, DYNAMIC, at, obj, dynamic=True, exact=False))
            continue
        found.extend(_from_text(query, obj, line=at, exact=exact))
    return found


def _fragments(node: Any, *, line: int, dynamic: bool) -> Iterator[tuple[str, int, bool]]:
    """``(SQL text, body line, dynamic)`` for every fragment under ``node``.

    ``parse_plpgsql`` puts ``lineno`` on the *statement* and the SQL on a
    ``PLpgSQL_expr`` below it, so the nearest enclosing line travels down.
    """
    if isinstance(node, list):
        for item in node:
            yield from _fragments(item, line=line, dynamic=dynamic)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key == _EXPR:
            query = value.get("query") if isinstance(value, dict) else None
            if query:
                yield query, line, dynamic
        elif isinstance(value, dict):
            yield from _fragments(
                value,
                line=value.get("lineno", line),
                dynamic=dynamic or key in _DYNAMIC_STATEMENTS,
            )
        elif isinstance(value, list):
            yield from _fragments(value, line=line, dynamic=dynamic)


def _from_text(
    text: str,
    obj: SchemaObject,
    *,
    line: int | None = None,
    shift: int = 0,
    exact: bool = True,
) -> list[Reference]:
    """References in a SQL fragment: all at *line*, or each at its own plus *shift*.

    A PL/pgSQL fragment can be a bare expression (``v := app.f(1)``, a ``WHEN``
    condition), which is not a statement; prefixing ``SELECT`` makes it one
    without changing what it names.
    """
    for candidate in (text, f"SELECT {text}"):
        try:
            raws = list(pglast.parse_sql(candidate) or [])
        except pglast.parser.ParseError:
            continue
        return [
            ref
            for raw in raws
            for ref in _from_nodes(
                candidate, raw.stmt, obj, line=line, created=raw, exact=exact, offset=shift
            )
        ]
    return []


def _from_nodes(
    text: str,
    root: Any,
    obj: SchemaObject,
    *,
    line: int | None = None,
    created: Any = None,
    exact: bool = True,
    offset: int = 0,
) -> list[Reference]:
    """Walk one parse tree for the relations and routines it names.

    ``created`` is the raw statement when the tree *is* a statement, so a
    fragment that creates something (a temporary table inside a body) does not
    report the thing it just created as missing.
    """
    nodes = list(walk_nodes(root))
    skip = _cte_names(nodes) | _created_name(text, created)
    found: list[Reference] = []
    for node in nodes:
        named = _named_object(node)
        if named is None:
            continue
        schema, name, kind, location = named
        if schema is None and name in skip:
            continue
        at = line if line is not None else _line_of(text, location) + offset
        found.append(_reference(schema, name, kind, at, obj, exact=exact))
    return found


def _named_object(node: Any) -> tuple[str | None, str, str, int | None] | None:
    """``(schema, name, kind, location)`` when this node names an object."""
    kind = type(node).__name__
    if kind == "RangeVar":
        return node.schemaname, node.relname, RELATION, node.location
    if kind == "FuncCall":
        schema, name = split_names(node.funcname)
        return (schema, name, ROUTINE, node.location) if name else None
    return None


def _cte_names(nodes: list[Any]) -> frozenset[str]:
    """``WITH`` names: they live for one statement, so no file creates them."""
    return frozenset(
        node.ctename for node in nodes if type(node).__name__ == "CommonTableExpr" and node.ctename
    )


def _created_name(text: str, raw: Any) -> frozenset[str]:
    """The object this fragment itself creates, if it creates one."""
    if raw is None:
        return frozenset()
    created = object_from_statement(text, raw)
    return frozenset() if created is None else frozenset({created.folded_name})


def _line_of(text: str, location: int | None) -> int:
    if location is None or location < 0:
        return 1
    return text.count("\n", 0, min(location, len(text))) + 1


def _reference(
    schema: str | None,
    name: str,
    kind: str,
    line: int,
    obj: SchemaObject,
    *,
    dynamic: bool = False,
    exact: bool = True,
) -> Reference:
    return Reference(
        schema=schema,
        name=name,
        kind=kind,
        line=line,
        referrer=obj.identity,
        referrer_kind=obj.kind,
        referrer_line=obj.statement_line,
        dynamic=dynamic,
        line_is_exact=exact,
    )
