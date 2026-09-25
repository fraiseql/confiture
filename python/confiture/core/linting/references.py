"""What a body names, so the build can be asked whether it creates it (#246).

``build_001`` proves confiture holds a complete inventory of what a build
*creates* — it has to, to know that something is created twice. This module
reads it in the other direction, because a routine that selects from a table no
file creates, or calls a function no file creates, otherwise builds and lints in
silence. It collects the objects a body *references*:

- a PL/pgSQL body through :mod:`confiture.core.plpgsql_fragments`, which
  hands back every embedded SQL fragment with the statement it belongs to and
  the line it is written on, parsed the way that statement writes it — an
  assignment's value, a condition, a whole query (#363);
- a ``LANGUAGE sql`` body and a view definition directly, because they are SQL
  already.

One walker then collects ``RangeVar`` (a relation) and ``FuncCall`` (a routine)
from whatever came back. A hand-rolled regex is crude and misses plenty; the
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

A body has a third possible outcome beside "read" and "dynamic": *not
returned*. The compiler behind ``parse_plpgsql`` has no catalogue, and there
are shapes it will not resolve without one — an array whose element type it
cannot name, for one. :func:`read_references` names those routines instead of
raising or staying quiet, because a rule that skipped a body has not
established that the body is clean. What it takes to keep that list short is
:mod:`confiture.core.plpgsql_parse`'s work (#270, #272), not this module's:
everything here asks :func:`~confiture.core.plpgsql_parse.parse_body` for a
tree and reports the routine when it does not get one.

A fragment the reader could not parse is a fourth: the body was read, one
statement in it was not, and :attr:`ReferenceScan.unread_fragments` names it
with its line rather than letting the rest of the body pass for the whole.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pglast
import pglast.parser

from confiture.core import plpgsql_fragments, plpgsql_parse, sql_lexer
from confiture.core._pglast_enums import member as _pg_member
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

#: Not an object either — a fragment that could not be parsed, kept so the
#: rule can say the body was read short instead of implying it was read whole.
UNREAD = "unread"

#: When PostgreSQL resolves a name, which decides whether the object must exist
#: before the statement that names it (``build_004``): when the body first runs
#: (PL/pgSQL), when the statement runs (a view, a ``BEGIN ATOMIC`` body, a
#: default, a check, an index expression, a trigger's function, a foreign key),
#: or when it runs while ``check_function_bodies`` is on (a ``LANGUAGE sql``
#: body written as a string, #383).
AT_RUN = "run"
AT_CREATE = "create"
AT_CREATE_IF_CHECKED = "create, when function bodies are checked"

#: The languages whose bodies are SQL confiture can parse. Everything else —
#: ``c``, ``internal``, ``plpython3u``, ``plperl`` — has a body that is not SQL.
_SQL_LANGUAGES = frozenset({"sql", "plpgsql"})

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
    #: When PostgreSQL resolves the name: :data:`AT_RUN`, :data:`AT_CREATE` or
    #: :data:`AT_CREATE_IF_CHECKED`.
    resolves: str = AT_RUN
    #: What names it, when not a body: ``DEFAULT``, ``CHECK``, ``FOREIGN KEY``, …
    clause: str | None = None
    #: A foreign key written in its ``CREATE TABLE``, which the builder's
    #: two-pass mode moves to the end of the build.
    movable: bool = False

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


class _UnreadableBody(Exception):
    """No parser would return this body, so nothing can be read out of it."""


@dataclass(frozen=True)
class ReferenceScan:
    """What one text's bodies name, and which of them could not be read.

    Attributes:
        references: Every object a routine or view body names, in source order.
        unread: The identity of each routine whose body no parser returned.
            Empty for almost every schema and never empty for one with a
            trigger function, which is why it is a list and not a flag.
        unread_fragments: One entry per fragment of a body that *was*
            returned but that pglast would not parse, or whose slot the
            fragment reader has no reading for — ``name`` holds the reason,
            ``line`` where it is written. What it would have named is unknown.
    """

    references: list[Reference] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    unread_fragments: list[Reference] = field(default_factory=list)
    #: What a statement that is not a body names and PostgreSQL resolves when
    #: the statement runs: a default, a check, a foreign key, an index
    #: expression, a trigger's function, the table an index, trigger or
    #: ``ALTER TABLE`` is on. Kept apart from :attr:`references`, which is what
    #: ``build_003`` judges; ``build_004`` reads both.
    clauses: list[Reference] = field(default_factory=list)
    #: ``(line, on)`` for each ``SET``/``RESET check_function_bodies``, in order.
    body_checks: list[tuple[int, bool]] = field(default_factory=list)


def read_references(sql: str) -> ReferenceScan:
    """Every object the routine and view bodies in ``sql`` name, and what went unread.

    A text pglast rejects yields nothing: the linter already reports a parse
    failure once, as its ``UNPARSEABLE`` notice, and a second report of the
    same fact from every rule would be noise. A single *body* it will not
    return is different — the rest of the text read fine — so that routine is
    named rather than dropped.
    """
    try:
        raws = list(pglast.parse_sql(sql) or [])
    except pglast.parser.ParseError:
        return ReferenceScan()
    # Scanned once for the whole text: a body's first line is a lexical
    # question, and asking it per routine would make the cost quadratic.
    constants = _string_constants(sql)
    scan = ReferenceScan()
    lines = _StatementLines(sql)
    for raw in raws:
        _read_clauses(raw, lines, scan)
        obj = object_from_statement(sql, raw)
        reader = None if obj is None else _READERS.get(obj.kind)
        if obj is None or reader is None:
            continue
        try:
            read = reader(sql, raw, obj, constants)
        except _UnreadableBody:
            scan.unread.append(obj.identity)
            continue
        for reference in read:
            kept = scan.unread_fragments if reference.kind == UNREAD else scan.references
            kept.append(reference)
    return scan


def temp_relations(sql: str) -> frozenset[str]:
    """The bare names of the relations a PL/pgSQL body in ``sql`` creates ``TEMP``.

    They exist only while that body runs, so an analyser that resolves a body
    against the built schema reports each one missing — the ``temp_table``
    artefact ``body_003`` names (#354). Read from the same fragments
    :func:`read_references` walks; a body that will not parse contributes nothing.
    """
    try:
        raws = list(pglast.parse_sql(sql) or [])
    except pglast.parser.ParseError:
        return frozenset()
    found: set[str] = set()
    for raw in raws:
        obj = object_from_statement(sql, raw)
        if obj is None or obj.kind not in _ROUTINE_KINDS:
            continue
        language, body = routine_body(raw.stmt)
        if language != "plpgsql" or body is None:
            continue
        at = _as_location(raw.stmt)
        offset = raw.stmt_location or 0
        try:
            compiled = plpgsql_parse.parse_body(
                _statement_text(sql, raw), body_at=None if at is None else at - offset
            )
        except (pglast.parser.ParseError, json.JSONDecodeError):
            continue
        for fragment in plpgsql_fragments.fragments(compiled):
            if fragment.mode is plpgsql_fragments.Mode.STATEMENT and fragment.tree:
                found.update(_created_temp(fragment.tree))
    return frozenset(found)


def _created_temp(statements: tuple[Any, ...]) -> set[str]:
    """What one fragment creates ``TEMP``: ``CREATE TEMP TABLE`` or ``… AS``."""
    created: set[str] = set()
    for raw in statements:
        stmt = raw.stmt
        kind = type(stmt).__name__
        if kind == "CreateStmt":
            relation = getattr(stmt, "relation", None)
        elif kind == "CreateTableAsStmt":
            relation = getattr(getattr(stmt, "into", None), "rel", None)
        else:
            relation = None
        if relation is not None and relation.relpersistence == "t":
            created.add(relation.relname)
    return created


def referenced_objects(sql: str) -> list[Reference]:
    """Every object the routine and view bodies in ``sql`` name, in source order."""
    return read_references(sql).references


def _string_constants(sql: str) -> list[tuple[int, int]]:
    try:
        return sql_lexer.string_constants(sql)
    except (ValueError, IndexError):
        return []


def _as_location(stmt: Any) -> int | None:
    """Where the routine's ``AS`` clause begins, or ``None`` when it has none.

    Both the line the body starts on and the text handed to the PL/pgSQL
    compiler are counted from it, so the ``DefElem`` walk is written once.
    """
    at = next(
        (opt.location for opt in getattr(stmt, "options", None) or () if opt.defname == "as"),
        None,
    )
    return None if at is None or at < 0 else at


def _body_line(sql: str, stmt: Any, constants: list[tuple[int, int]]) -> int | None:
    """The file line the routine's body starts on, or ``None`` when it cannot be found.

    ``parse_plpgsql`` numbers a body from its first line, which is whatever
    follows the opening ``$$`` — so the line to add back is the line of the
    first string constant at or after the ``AS`` clause.
    """
    at = _as_location(stmt)
    if at is None:
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
    """A function or procedure body, read by :func:`read_body`."""
    body = read_body(sql, raw, obj, constants)
    if body.refused is not None:
        raise _UnreadableBody(obj.identity)
    if getattr(raw.stmt, "sql_body", None) is not None:
        resolves = AT_CREATE
    elif body.language == "sql":
        resolves = AT_CREATE_IF_CHECKED
    else:
        resolves = AT_RUN
    found: list[Reference] = []
    for statement in body.statements:
        found.extend(
            _from_nodes(
                statement.text,
                statement.root,
                obj,
                line=statement.line,
                created=statement.created,
                exact=statement.exact,
                offset=statement.offset,
                resolves=resolves,
            )
        )
    found.extend(
        _reference(None, text, DYNAMIC, line, obj, dynamic=True, exact=False)
        for line, text in body.dynamic
    )
    found.extend(
        _reference(None, reason, UNREAD, line, obj, exact=body.exact)
        for line, reason in body.unread
    )
    return sorted(found, key=lambda reference: reference.line)


def _query_references(
    sql: str, raw: Any, obj: SchemaObject, _constants: list[tuple[int, int]]
) -> list[Reference]:
    """A view or materialized view: its query was parsed with the statement."""
    return _from_nodes(sql, raw.stmt.query, obj, resolves=AT_CREATE)


#: Which reader each inventory kind needs. A kind that is absent has no body.
_READERS: dict[str, Callable[[str, Any, SchemaObject, list[tuple[int, int]]], list[Reference]]] = {
    "function": _routine_references,
    "procedure": _routine_references,
    "view": _query_references,
    "matview": _query_references,
}


@dataclass(frozen=True)
class BodyStatement:
    """One statement or expression of a routine body, parsed, and where it is written.

    Attributes:
        root: The parse node: a statement, or the ``SELECT`` an expression was
            read as.
        text: The text the node's locations index into.
        created: The raw statement when *root* is one, so what it creates (a
            temporary table) is known; ``None`` for a body parsed with its ``CREATE``.
        line: The line every location in the node reports — a PL/pgSQL
            fragment's statement line — or ``None`` when each location has its own.
        offset: Added to a location's own line in *text* to place it in the
            frame of the text :func:`read_body` was given.
        exact: Whether that frame is the file's, rather than the body's own.
    """

    root: Any
    text: str
    created: Any = None
    line: int | None = None
    offset: int = 0
    exact: bool = True

    def line_at(self, location: int | None) -> int:
        """The line *location* in :attr:`root` is written on."""
        return self.line if self.line is not None else _line_of(self.text, location) + self.offset


@dataclass(frozen=True)
class RoutineBody:
    """What of one routine's body was read, and what was not.

    Attributes:
        obj: The routine.
        language: Its ``LANGUAGE``, as written.
        statements: Every statement and expression that parsed, in source order.
        dynamic: ``(line, text)`` of each string ``EXECUTE`` builds at run time.
        unread: ``(line, reason)`` of each statement that was not parsed.
        refused: Why no parser returned the body at all, or ``None``.
        exact: Whether the lines are the file's rather than the body's own.
    """

    obj: SchemaObject
    language: str | None
    statements: tuple[BodyStatement, ...] = ()
    dynamic: tuple[tuple[int, str], ...] = ()
    unread: tuple[tuple[int, str], ...] = ()
    refused: str | None = None
    exact: bool = True

    @property
    def is_sql(self) -> bool:
        """Whether the body is SQL confiture reads, rather than a symbol or another language."""
        return self.language in _SQL_LANGUAGES or bool(self.statements)


def read_body(
    sql: str, raw: Any, obj: SchemaObject, constants: list[tuple[int, int]] | None = None
) -> RoutineBody:
    """One ``CREATE FUNCTION``/``PROCEDURE`` statement's body, read by the parser its language needs.

    *raw* is the statement as pglast returned it from *sql*; lines are counted in
    *sql*'s frame. ``BEGIN ATOMIC`` was parsed with the statement; a ``LANGUAGE
    sql`` body is SQL text; a PL/pgSQL body is compiled by
    :func:`~confiture.core.plpgsql_parse.parse_body` and read fragment by
    fragment through :mod:`confiture.core.plpgsql_fragments`. Any other language
    comes back with no statements, and a body that is not read whole says so.
    """
    stmt = raw.stmt
    language, body = routine_body(stmt)
    if getattr(stmt, "sql_body", None) is not None:
        return RoutineBody(obj, language or "sql", (BodyStatement(stmt.sql_body, sql),))
    if language not in _SQL_LANGUAGES or body is None:
        return RoutineBody(obj, language)
    first = _body_line(sql, stmt, _string_constants(sql) if constants is None else constants)
    exact = first is not None
    if language == "sql":
        return _sql_body(obj, body, first=first)
    at = _as_location(stmt)
    offset = raw.stmt_location or 0
    try:
        compiled = plpgsql_parse.parse_body(
            _statement_text(sql, raw), body_at=None if at is None else at - offset
        )
    except (pglast.parser.ParseError, json.JSONDecodeError) as exc:
        # A refusal by the PL/pgSQL compiler about this one body, which blanking
        # a qualifier does not address (#270), or a serialisation that does not
        # decode for a reason other than the stray brace repaired for #272:
        # either way what the tree holds is unknown, and an unknown tree is an
        # unread body — named, never half-read and never passed off as clean.
        return RoutineBody(obj, language, refused=str(exc).split("\n", 1)[0], exact=exact)
    return _plpgsql_body(obj, compiled, first=first)


def _sql_body(obj: SchemaObject, body: str, *, first: int | None) -> RoutineBody:
    """A ``LANGUAGE sql`` body: statements and nothing else, parsed as one text."""
    shift = (first - 1) if first else 0
    try:
        raws = list(pglast.parse_sql(body) or [])
    except pglast.parser.ParseError as exc:
        return RoutineBody(obj, "sql", unread=((first or obj.statement_line, str(exc)),))
    statements = tuple(
        BodyStatement(raw.stmt, body, created=raw, offset=shift, exact=first is not None)
        for raw in raws
    )
    return RoutineBody(obj, "sql", statements, exact=first is not None)


def _plpgsql_body(
    obj: SchemaObject, compiled: plpgsql_parse.Compiled, *, first: int | None
) -> RoutineBody:
    """Every fragment the compiler found: parsed, built at run time, or not read.

    ``parse_plpgsql`` counts from the body's first line, so *first* — that
    line's number in the file — turns each ``lineno`` into a file line. Without
    it every line is the body's own, and the body says it is inexact.
    """
    exact = first is not None
    statements: list[BodyStatement] = []
    dynamic: list[tuple[int, str]] = []
    unread: list[tuple[int, str]] = []
    for fragment in plpgsql_fragments.fragments(compiled):
        at = file_line(fragment.line, first)
        if fragment.dynamic:
            dynamic.append((at, fragment.text))
        elif fragment.tree is None:
            unread.append((at, fragment.finding or ""))
        else:
            statements.extend(
                BodyStatement(raw.stmt, fragment.sql or "", created=raw, line=at, exact=exact)
                for raw in fragment.tree
            )
    return RoutineBody(
        obj, "plpgsql", tuple(statements), tuple(dynamic), tuple(unread), exact=exact
    )


def _from_nodes(
    text: str,
    root: Any,
    obj: SchemaObject,
    *,
    line: int | None = None,
    created: Any = None,
    exact: bool = True,
    offset: int = 0,
    resolves: str = AT_RUN,
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
        found.append(_reference(schema, name, kind, at, obj, exact=exact, resolves=resolves))
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
    resolves: str = AT_RUN,
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
        resolves=resolves,
    )


class _StatementLines:
    """The line each statement of one text starts on, counted on from the last one asked."""

    def __init__(self, sql: str) -> None:
        self._sql = sql
        self._pos = 0
        self._line = 1

    def of(self, raw: Any) -> int:
        start = sql_lexer.skip_leading_comments(self._sql, raw.stmt_location or 0)
        if start < self._pos:
            return _line_of(self._sql, start)
        self._line += self._sql.count("\n", self._pos, start)
        self._pos = start
        return self._line


#: The statements that name, outside any body, objects PostgreSQL resolves when
#: they run, and the node each one is *on* (``None``: it is on nothing else).
_CLAUSE_STATEMENTS = frozenset(
    {"CreateStmt", "CreateTableAsStmt", "IndexStmt", "CreateTrigStmt", "AlterTableStmt"}
)

#: A ``Constraint``'s kind, as the clause a finding names.
_CLAUSES = {
    _pg_member("ConstrType", "CONSTR_DEFAULT"): "DEFAULT",
    _pg_member("ConstrType", "CONSTR_CHECK"): "CHECK",
    _pg_member("ConstrType", "CONSTR_FOREIGN"): "FOREIGN KEY",
    _pg_member("ConstrType", "CONSTR_GENERATED"): "GENERATED",
}
_FOREIGN = _pg_member("ConstrType", "CONSTR_FOREIGN")


def _clause_target(stmt: Any, kind: str) -> tuple[Any, str] | None:
    """``(the relation the statement creates or None, what it is)`` for a clause statement."""
    if kind == "CreateTableAsStmt":
        return None if stmt.objtype == _MATVIEW_OBJECT else (stmt.into.rel, "table")
    if kind == "CreateStmt":
        return stmt.relation, "table"
    return None, {"IndexStmt": "index", "CreateTrigStmt": "trigger"}.get(kind, "table")


def _referrer_name(stmt: Any, own: Any) -> str:
    """The table a statement creates or is on — an index or trigger by its own name, on it."""
    target = stmt.relation if own is None else own
    table = ".".join(p for p in (target.schemaname, target.relname) if p)
    own_name = getattr(stmt, "idxname", None) or getattr(stmt, "trigname", None)
    return f"{own_name} on {table}" if own_name else table


def _constraint_clauses(stmt: Any, *, in_create: bool) -> tuple[dict[int, str], set[int]]:
    """The clause each node under a constraint belongs to, and the movable foreign keys.

    A foreign key written in its ``CREATE TABLE`` is one the builder's two-pass
    mode moves to the end of the build; one added by ``ALTER TABLE`` stays put.
    """
    clause_of: dict[int, str] = {}
    movable: set[int] = set()
    for node in walk_nodes(stmt):
        if type(node).__name__ != "Constraint" or int(node.contype) not in _CLAUSES:
            continue
        for part in walk_nodes((node.raw_expr, node.pktable)):
            clause_of[id(part)] = _CLAUSES[int(node.contype)]
        if int(node.contype) == _FOREIGN and in_create and node.pktable is not None:
            movable.add(id(node.pktable))
    return clause_of, movable


def _read_clauses(raw: Any, lines: _StatementLines, scan: ReferenceScan) -> None:
    """What one statement outside a body needs when it runs, into *scan*."""
    stmt = raw.stmt
    kind = type(stmt).__name__
    if kind == "VariableSetStmt" and stmt.name == "check_function_bodies":
        scan.body_checks.append((lines.of(raw), _guc_on(stmt)))
        return
    target = _clause_target(stmt, kind) if kind in _CLAUSE_STATEMENTS else None
    if target is None:
        return
    own, what = target
    line = lines.of(raw)
    referrer = _referrer_name(stmt, own)
    clause_of, movable = _constraint_clauses(stmt, in_create=kind == "CreateStmt")

    def needs(schema: str | None, name: str, ref_kind: str, clause: str | None, node: Any) -> None:
        scan.clauses.append(
            Reference(
                schema,
                name,
                ref_kind,
                line,
                referrer,
                what,
                line,
                resolves=AT_CREATE,
                clause=clause,
                movable=id(node) in movable,
            )
        )

    if kind == "CreateTrigStmt":
        needs(*split_names(stmt.funcname), ROUTINE, "EXECUTE FUNCTION", stmt.funcname)
    for node in walk_nodes(stmt):
        named = None if node is own else _named_object(node)
        if named is None:
            continue
        clause = clause_of.get(id(node))
        if own is None and node is stmt.relation:
            clause = "ALTER TABLE" if what == "table" else f"CREATE {what.upper()}"
        elif clause is None and kind == "IndexStmt":
            clause = "index expression"
        needs(named[0], named[1], named[2], clause, node)


_MATVIEW_OBJECT = _pg_member("ObjectType", "OBJECT_MATVIEW")
_VAR_SET_VALUE = _pg_member("VariableSetKind", "VAR_SET_VALUE")

#: How PostgreSQL spells a boolean setting that is off.
_OFF = frozenset({"off", "false", "no", "0", "f", "n", "of", "fa", "fal", "fals"})


def _guc_on(stmt: Any) -> bool:
    """Whether a ``SET``/``RESET check_function_bodies`` leaves the check on."""
    if int(stmt.kind) != _VAR_SET_VALUE or not stmt.args:
        return True
    value = stmt.args[0].val
    text = str(getattr(value, "sval", None) or getattr(value, "ival", ""))
    return text.lower() not in _OFF
