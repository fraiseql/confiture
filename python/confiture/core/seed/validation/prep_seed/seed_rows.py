"""What a seed file writes, read by PostgreSQL's parser: each statement's target, columns and rows.

An ``INSERT … VALUES`` is read from its parse tree, every row of it. A
``COPY … FROM stdin`` block's statement is parsed on its own — the rows after it
are not SQL — and its rows are decoded by ``copy_formatter.copy_row``, the reader
beside COPY's one escaper. Either way a row carries its own line, so a finding
about a value names the line the value is on.

A statement level 1 cannot check is never passed over in silence: it is an
:class:`Unread` with the reason, unless :data:`UNREAD_SEED_STATEMENTS` says why a
statement of its kind writes no row to check.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pglast
from pglast import ast

from confiture.core import sql_lexer
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import walk_nodes
from confiture.core.parser_info import parse_error_line
from confiture.core.seed.copy_formatter import CsvOptions, copy_csv_rows, copy_row

_SETOP_NONE = _pg_member("SetOperation", "SETOP_NONE")

#: Statements a seed file may hold that write no row level 1 could check, each
#: with the reason. Any other statement level 1 does not read is reported.
UNREAD_SEED_STATEMENTS: dict[str, str] = {
    "VariableSetStmt": "SET changes a session setting; it writes no row",
    "TransactionStmt": "BEGIN, COMMIT and SAVEPOINT bracket statements; they write no row",
    "SelectStmt": "a SELECT (a setval, a query) writes no row; its UNION branches are checked",
    "TruncateStmt": "TRUNCATE empties a table; it writes no row",
    "DeleteStmt": "DELETE removes rows; it writes none",
}


@dataclass(frozen=True)
class Computed:
    """A value PostgreSQL computes when the row is written: a call, a reference, an operator."""

    node: str


#: One value of a row: its text as PostgreSQL's input reads it, ``None`` for
#: NULL, or :class:`Computed`.
Value = str | None | Computed


@dataclass(frozen=True)
class SeedRow:
    """One row a statement writes: its 1-based position, its line, its values."""

    number: int
    line: int
    values: tuple[Value, ...]


@dataclass(frozen=True)
class SeedWrite:
    """The rows one ``INSERT`` or ``COPY`` writes into one table.

    ``schema`` is ``None`` when the statement does not qualify the table;
    ``columns`` is ``None`` when it names none, and the table's own column
    order then decides which value is which.
    """

    schema: str | None
    table: str
    columns: tuple[str, ...] | None
    rows: tuple[SeedRow, ...]
    line: int
    form: Literal["insert", "copy"]

    @property
    def qualified(self) -> str:
        """The table as the statement names it."""
        return f"{self.schema}.{self.table}" if self.schema else self.table


@dataclass(frozen=True)
class Unread:
    """A statement level 1 does not check, the line it is on, and why."""

    line: int
    reason: str


@dataclass(frozen=True)
class UnionQuery:
    """A ``UNION`` and its branches, each the target-list expressions of one ``SELECT``."""

    line: int
    branches: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True)
class SeedStatements:
    """Everything level 1 reads in one seed file."""

    writes: tuple[SeedWrite, ...]
    unread: tuple[Unread, ...]
    unions: tuple[UnionQuery, ...]
    union_comment_lines: tuple[int, ...]


class SeedParseError(ValueError):
    """PostgreSQL's parser rejects the seed file: the message and the line it points at."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.line = line


class _Lines:
    """The 1-based line of an offset in one text, by bisecting its newlines."""

    def __init__(self, text: str) -> None:
        self._newlines = [i for i, char in enumerate(text) if char == "\n"]

    def of(self, offset: int) -> int:
        return bisect_left(self._newlines, offset) + 1


def _constant(node: Any) -> Value:
    """The input text of a constant, through any casts on it; :class:`Computed` otherwise."""
    while isinstance(node, ast.TypeCast):
        node = node.arg
    if not isinstance(node, ast.A_Const):
        return Computed(type(node).__name__)
    if node.isnull:
        return None
    val = node.val
    if isinstance(val, ast.String):
        return val.sval
    if isinstance(val, ast.Integer):
        return str(val.ival)
    if isinstance(val, ast.Float):
        return val.fval
    if isinstance(val, ast.Boolean):
        return "true" if val.boolval else "false"
    return val.bsval


def _row_openings(toks: Sequence[Any], starts: Sequence[int], start: int, end: int) -> list[int]:
    """The offsets of the ``(`` that opens each row of the first depth-0 ``VALUES`` in a span.

    The column list is inside parentheses, so the ``VALUES`` a row list follows
    is the first one met at depth 0 after the target; a row starts at each ``(``
    met at depth 0 after it. *starts* is each token's start, to find the span's
    first token without walking the file's.
    """
    depth = 0
    seen_values = False
    openings: list[int] = []
    for tok in toks[bisect_left(starts, start) : bisect_left(starts, end)]:
        if tok.name == "ASCII_40":
            if seen_values and depth == 0:
                openings.append(tok.start)
            depth += 1
        elif tok.name == "ASCII_41":
            depth -= 1
        elif tok.name == "VALUES" and depth == 0:
            seen_values = True
    return openings


def _insert(
    lines: _Lines, toks: Sequence[Any], starts: Sequence[int], parsed: sql_lexer.ParsedStatement
) -> SeedWrite | Unread:
    stmt = parsed.stmt
    select = stmt.selectStmt
    if select is None:
        return Unread(parsed.line, "INSERT … DEFAULT VALUES writes no value to check")
    if not select.valuesLists:
        return Unread(parsed.line, "an INSERT … SELECT: the values are computed at run time")
    relation = stmt.relation
    openings = _row_openings(toks, starts, relation.location, parsed.location + parsed.length)
    if len(openings) != len(select.valuesLists):
        openings = [parsed.location] * len(select.valuesLists)
    rows = tuple(
        SeedRow(number, lines.of(at), tuple(_constant(v) for v in values))
        for number, (at, values) in enumerate(
            zip(openings, select.valuesLists, strict=True), start=1
        )
    )
    columns = tuple(target.name for target in stmt.cols) if stmt.cols else None
    return SeedWrite(relation.schemaname, relation.relname, columns, rows, parsed.line, "insert")


def _options(stmt: Any) -> dict[str, str]:
    options: dict[str, str] = {}
    for opt in stmt.options or ():
        options[opt.defname] = getattr(opt.arg, "sval", None) or ""
    return options


def _copy(lines: _Lines, block: sql_lexer.CopyBlock) -> SeedWrite | Unread:
    line = lines.of(block.start)
    try:
        (parsed,) = pglast.parse_sql(block.statement)
    except pglast.parser.ParseError as exc:
        raise SeedParseError(str(exc), line + parse_error_line(block.statement, exc) - 1) from exc
    stmt = parsed.stmt
    if not isinstance(stmt, ast.CopyStmt) or stmt.relation is None:
        return Unread(line, "a COPY … FROM stdin that names no table")
    options = _options(stmt)
    fmt = options.get("format", "text").lower()
    relation = stmt.relation
    columns = tuple(name.sval for name in stmt.attlist) if stmt.attlist else None
    first = lines.of(block.data_start)
    if fmt == "csv":
        return _csv_copy(stmt, block, columns, line=line, first=first)
    if fmt != "text":
        return Unread(line, f"a COPY in {fmt} format: level 1 decodes the text and csv formats")
    texts = block.data.split("\n")[:-1] if block.data else []
    delimiter = options.get("delimiter", "\t")
    null = options.get("null", "\\N")
    rows = tuple(
        SeedRow(number, first + number - 1, copy_row(text, delimiter=delimiter, null=null))
        for number, text in enumerate(texts, start=1)
    )
    return SeedWrite(relation.schemaname, relation.relname, columns, rows, line, "copy")


def _csv_copy(
    stmt: Any, block: sql_lexer.CopyBlock, columns: tuple[str, ...] | None, *, line: int, first: int
) -> SeedWrite | Unread:
    """A CSV ``COPY``'s rows, decoded by :func:`copy_csv_rows` with the statement's options."""
    options = _csv_options(stmt, columns)
    if isinstance(options, str):
        return Unread(line, options)
    try:
        decoded = copy_csv_rows(block.data, options)
    except ValueError as exc:
        raise SeedParseError(str(exc), first) from exc
    relation = stmt.relation
    rows = tuple(
        SeedRow(number, first + at, values) for number, (at, values) in enumerate(decoded, start=1)
    )
    return SeedWrite(relation.schemaname, relation.relname, columns, rows, line, "copy")


def _csv_options(stmt: Any, columns: tuple[str, ...] | None) -> CsvOptions | str:
    """The statement's CSV options, or why level 1 cannot read its rows."""
    given = {opt.defname: opt.arg for opt in stmt.options or ()}
    if "default" in given:
        return "a COPY with a DEFAULT marker: level 1 does not read which fields it fills"
    forced: dict[str, frozenset[int]] = {}
    for name in ("force_null", "force_not_null"):
        arg = given.get(name)
        if arg is None:
            forced[name] = frozenset()
        elif columns is None:
            return f"a COPY whose {name.upper()} names columns it does not list"
        elif type(arg).__name__ == "A_Star":
            forced[name] = frozenset(range(len(columns)))
        else:
            named = [item.sval for item in arg]
            if not set(named) <= set(columns):
                return f"a COPY whose {name.upper()} names a column it does not list"
            forced[name] = frozenset(columns.index(n) for n in named)
    text = {name: getattr(arg, "sval", None) for name, arg in given.items()}
    return CsvOptions(
        delimiter=text.get("delimiter") or ",",
        quote=text.get("quote") or '"',
        escape=text.get("escape"),
        null=text["null"] if text.get("null") is not None else "",
        header=_header(given),
        columns=columns,
        force_null=forced["force_null"],
        force_not_null=forced["force_not_null"],
    )


def _header(given: dict[str, Any]) -> bool | str:
    """``HEADER``'s value: absent is false, bare is true, then a Boolean, an Integer or a word."""
    if "header" not in given:
        return False
    arg = given["header"]
    match type(arg).__name__:
        case "NoneType":
            return True
        case "Boolean":
            return bool(arg.boolval)
        case "Integer":
            return bool(arg.ival)
        case _:
            word = arg.sval.lower()
            return "match" if word == "match" else word in ("true", "on")


def _set_operations(stmt: Any) -> Iterator[Any]:
    """Every outermost set operation in *stmt*: a ``UNION`` nested in another is its branch."""
    inner: set[int] = set()
    for node in walk_nodes(stmt):
        if not isinstance(node, ast.SelectStmt) or int(node.op) == _SETOP_NONE:
            continue
        if id(node) in inner:
            continue
        for child in (node.larg, node.rarg):
            inner.add(id(child))
        yield node


def _branches(select: Any) -> list[tuple[Any, ...]]:
    if int(select.op) == _SETOP_NONE:
        return [tuple(target.val for target in select.targetList or ())]
    return _branches(select.larg) + _branches(select.rarg)


def _union_comment_lines(sql: str, lines: _Lines, toks: Sequence[Any]) -> tuple[int, ...]:
    """The line of each ``UNION [ALL|DISTINCT]`` a line comment follows on the same line."""
    found: list[int] = []
    for i, tok in enumerate(toks):
        if tok.name != "UNION":
            continue
        j = i + 1
        if j < len(toks) and toks[j].name in ("ALL", "DISTINCT"):
            j += 1
        if (
            j < len(toks)
            and toks[j].name == "SQL_COMMENT"
            and "\n" not in sql[tok.end : toks[j].start]
        ):
            found.append(lines.of(tok.start))
    return tuple(found)


def read_seed_statements(sql: str) -> SeedStatements:
    """Every statement of a seed file, read by PostgreSQL's parser.

    Raises:
        SeedParseError: the parser rejects the file, or a ``COPY`` statement in
            it; the error names the line.
    """
    blanked = sql_lexer.blank_copy_blocks(sql)
    try:
        parsed = sql_lexer.parse(blanked)
    except pglast.parser.ParseError as exc:
        raise SeedParseError(str(exc), parse_error_line(blanked, exc)) from exc
    toks = sql_lexer.tokens(blanked)
    starts = [tok.start for tok in toks]
    lines = _Lines(sql)

    found: list[tuple[int, SeedWrite | Unread]] = []
    unions: list[UnionQuery] = []
    for statement in parsed:
        node = type(statement.stmt).__name__
        unions.extend(
            UnionQuery(statement.line, tuple(_branches(op)))
            for op in _set_operations(statement.stmt)
        )
        if node == "InsertStmt":
            found.append((statement.location, _insert(lines, toks, starts, statement)))
        elif node == "CopyStmt":
            # A `COPY … FROM stdin` block is blanked before this parse: what is
            # left reads a file or a program, or writes rows out.
            reason = "a COPY that does not read its rows from the file level 1 is reading"
            found.append((statement.location, Unread(statement.line, reason)))
        elif node not in UNREAD_SEED_STATEMENTS:
            found.append(
                (statement.location, Unread(statement.line, f"level 1 does not read a {node}"))
            )
    found.extend((block.start, _copy(lines, block)) for block in sql_lexer.copy_blocks(sql))
    found.sort(key=lambda item: item[0])

    return SeedStatements(
        writes=tuple(item for _, item in found if isinstance(item, SeedWrite)),
        unread=tuple(item for _, item in found if isinstance(item, Unread)),
        unions=tuple(unions),
        union_comment_lines=_union_comment_lines(blanked, lines, toks),
    )
