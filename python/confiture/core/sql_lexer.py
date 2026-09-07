"""The one SQL lexer: libpg_query's scanner and parser, nothing hand-written.

Ten hand-written scanners once split statements, skipped comments and matched
dollar tags across confiture, disagreeing on ``"a;b"`` identifiers, ``E'\\';'``
literals and nested tags (ANA-05). Every consumer now goes through here:

- :func:`split_statements` — top-level ``;`` boundaries from pglast's scanner,
  which tokenises anything (invalid SQL included) exactly as PostgreSQL would.
- :func:`strip_comments` — comment tokens blanked from the scanner's positions;
  literals, quoted identifiers and dollar-quoted bodies are untouched.
- :func:`parse` — ``parse_sql`` with each statement's location and line.
- :func:`statement_type` — the verb of a statement (``CREATE``, ``SELECT``, …).
- :func:`tokens` — the scanner's tokens with absolute offsets, minus the data
  rows of a ``COPY … FROM stdin`` block (psql client protocol, not SQL).
- :func:`code_text` — the text with everything that is not code blanked, line
  for line, for the applier's ``psql`` meta-command scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pglast
import pglast.parser

from confiture.core.parser_info import parse_error_index

_COMMENT_TOKENS = frozenset({"SQL_COMMENT", "C_COMMENT"})
# String-like constants: single-quoted, ``E''``, ``U&''``, ``B''``, ``X''`` and
# dollar-quoted bodies all scan as one token.
_STRING_TOKENS = frozenset({"SCONST", "USCONST", "BCONST", "XCONST"})
_SEMICOLON = "ASCII_59"
_COPY_TERMINATOR = "\\."
_WHITESPACE = " \t\n\r\f\v"

# pglast statement node → the verb ``sqlparse``'s ``get_type`` used to report.
_VERB_BY_NODE: dict[str, str] = {
    "SelectStmt": "SELECT",
    "InsertStmt": "INSERT",
    "UpdateStmt": "UPDATE",
    "DeleteStmt": "DELETE",
    "MergeStmt": "MERGE",
    "DropStmt": "DROP",
    "DropOwnedStmt": "DROP",
    "DropRoleStmt": "DROP",
    "DropdbStmt": "DROP",
    "TruncateStmt": "TRUNCATE",
    "GrantStmt": "GRANT",
    "GrantRoleStmt": "GRANT",
    "CommentStmt": "COMMENT",
    "RenameStmt": "ALTER",
    "AlterOwnerStmt": "ALTER",
    "AlterObjectSchemaStmt": "ALTER",
    "VariableSetStmt": "SET",
    "TransactionStmt": "TRANSACTION",
    "DoStmt": "DO",
    "CopyStmt": "COPY",
    "ExplainStmt": "EXPLAIN",
    "VacuumStmt": "VACUUM",
}


@dataclass(frozen=True)
class CodeText:
    """:func:`code_text`'s answer: the blanked text and how many COPY data blocks it skipped."""

    text: str
    copy_blocks: int


@dataclass(frozen=True)
class ParsedStatement:
    """One top-level statement: its node, offset and length in the source, and line."""

    stmt: Any
    location: int
    length: int
    line: int


def split_statements(sql: str) -> list[str]:
    """Split on top-level ``;``, respecting literals, quoted identifiers, comments and dollar bodies.

    Uses the scanner, not the parser, so a script PostgreSQL would reject still
    splits (each statement is then judged on its own). Blank statements are
    dropped; the result is stripped.
    """
    return [s.strip() for s in pglast.split(sql, with_parser=False) if s.strip()]


def strip_comments(sql: str, *, replace_with: str = "") -> str:
    """``sql`` with every ``--`` and ``/* */`` comment removed.

    Comment positions come from the scanner, so ``'a--b'``, ``"x--y"`` and
    ``$$ -- body $$`` are untouched. Line structure inside comments is dropped
    (the callers collapse whitespace); a line comment keeps the newline that
    ended it. ``replace_with`` stands in for each comment (the body normaliser
    passes a space so tokens do not merge).
    """
    if "--" not in sql and "/*" not in sql:
        return sql
    out: list[str] = []
    pos = 0
    for token in pglast.parser.scan(sql):
        if token.name not in _COMMENT_TOKENS:
            continue
        out.append(sql[pos : token.start])
        out.append(replace_with)
        pos = token.end + 1
    out.append(sql[pos:])
    return "".join(out)


def parse(sql: str) -> list[ParsedStatement]:
    """Every top-level statement with its source location. Raises ``pglast.parser.ParseError``."""
    tree = pglast.parse_sql(sql)
    out: list[ParsedStatement] = []
    for raw in tree or []:
        location = raw.stmt_location or 0
        start = skip_leading_comments(sql, location)
        out.append(
            ParsedStatement(
                stmt=raw.stmt,
                location=location,
                length=raw.stmt_len or 0,
                line=sql.count("\n", 0, start) + 1,
            )
        )
    return out


def skip_leading_comments(sql: str, start: int) -> int:
    """The offset of the first code character at or after ``start``.

    pglast's ``stmt_location`` includes the whitespace and comments that
    precede a statement; this jumps over them to the statement's first token.
    """
    i = start
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in _WHITESPACE:
            i += 1
            continue
        if sql.startswith("--", i):
            nl = sql.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        return i
    return start


def statement_type(statement: str) -> str:
    """The verb of one statement: ``CREATE``, ``ALTER``, ``SELECT``, … or ``UNKNOWN``."""
    try:
        parsed = pglast.parse_sql(statement)
    except pglast.parser.ParseError:
        return "UNKNOWN"
    if not parsed:
        return "UNKNOWN"
    node = type(parsed[0].stmt).__name__
    if node in _VERB_BY_NODE:
        return _VERB_BY_NODE[node]
    if node.startswith("Create") or node in (
        "IndexStmt",
        "ViewStmt",
        "DefineStmt",
        "CompositeTypeStmt",
        "RuleStmt",
    ):
        return "CREATE"
    if node.startswith("Alter"):
        return "ALTER"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Tokens, and what is code
# ---------------------------------------------------------------------------
#
# The scanner tokenises any text, but two things in a script are not SQL to it:
# the data rows between ``COPY … FROM stdin;`` and a line that is exactly ``\.``
# (psql reads them off the input stream without lexing), and whatever follows a
# scanner error such as an unterminated string (psql would swallow it too). The
# rows are skipped at the line level, exactly as psql consumes them, and the
# scan resumes after the terminator — on the same token list when the scanner
# provably re-synchronised there (a token starts exactly where the code
# resumes, none spans the boundary), by rescanning otherwise. A scanner error
# keeps the tokens before it and ends the code.


def tokens(sql: str) -> list[Any]:
    """Every scanner token of ``sql`` outside COPY data blocks, with absolute offsets.

    Each item is pglast's ``Token`` (``start``, ``end`` inclusive, ``name``,
    ``kind``); comments are tokens too. Text after a scanner error is opaque
    and yields nothing.
    """
    return _lex(sql)[0]


def code_text(sql: str) -> CodeText:
    r"""``sql`` with everything that is not SQL code blanked to spaces.

    Line structure is preserved exactly — the result has the same number of
    lines, each the same length — so a position in the output is a position in
    the input. Blanked: comments, string and dollar-quoted constants, quoted
    identifiers, COPY data rows (with their ``\.`` terminator) and the text
    after a scanner error. Kept: keywords, identifiers, numbers, operators,
    ``;`` and any backslash ``psql`` would execute.
    """
    toks, blocks = _lex(sql)
    out = [c if c == "\n" else " " for c in sql]
    for t in toks:
        if t.name in _COMMENT_TOKENS or t.name in _STRING_TOKENS or _is_quoted_identifier(sql, t):
            continue
        out[t.start : t.end + 1] = sql[t.start : t.end + 1]
    return CodeText(text="".join(out), copy_blocks=len(blocks))


def _is_quoted_identifier(sql: str, token: Any) -> bool:
    return token.name == "UIDENT" or (token.name == "IDENT" and sql[token.start] == '"')


def _lex(sql: str) -> tuple[list[Any], list[tuple[int, int]]]:
    """(tokens outside COPY data, ``(start, end)`` offsets of each COPY block incl. its data)."""
    out: list[Any] = []
    blocks: list[tuple[int, int]] = []
    n = len(sql)
    toks = _scan_recovering(sql)
    base = 0
    idx = 0
    while True:
        cut = _first_copy_statement(toks, idx)
        if cut is None:
            out.extend(_shift(toks[idx:], base))
            return out, blocks
        first, semicolon = cut
        newline = sql.find("\n", base + toks[semicolon].end + 1)
        data_start = n if newline == -1 else newline + 1
        # The rest of the COPY line is still code: psql lexes it before it reads data.
        out.extend(_shift([t for t in toks[idx:] if base + t.start < data_start], base))
        data_end = _terminator_end(sql, data_start)
        blocks.append((base + toks[first].start, data_end))
        if data_end >= n:
            return out, blocks
        resume = _resume_index(sql, toks, base, data_end)
        if resume is None:
            toks = _scan_recovering(sql[data_end:])
            base = data_end
            idx = 0
        else:
            idx = resume


def _scan_recovering(text: str) -> list[Any]:
    """The scanner's tokens; on a scanner error, the tokens before it."""
    try:
        return list(pglast.parser.scan(text))
    except pglast.parser.ParseError as exc:
        index = parse_error_index(exc)
        if not index:
            return []
        try:
            return list(pglast.parser.scan(text[:index]))
        except pglast.parser.ParseError:
            return []


def _shift(toks: list[Any], base: int) -> list[Any]:
    if not base:
        return list(toks)
    return [t._replace(start=t.start + base, end=t.end + base) for t in toks]


def _first_copy_statement(toks: list[Any], idx: int) -> tuple[int, int] | None:
    """``(first token, semicolon)`` indexes of the first ``COPY … FROM stdin;`` from ``idx``."""
    stmt_first = idx
    for i in range(idx, len(toks)):
        if toks[i].name != _SEMICOLON:
            continue
        if _is_copy_from_stdin(toks[stmt_first:i]):
            return stmt_first, i
        stmt_first = i + 1
    return None


def _is_copy_from_stdin(stmt: list[Any]) -> bool:
    names = [t.name for t in stmt if t.name not in _COMMENT_TOKENS]
    if not names or names[0] != "COPY":
        return False
    return any(a == "FROM" and b == "STDIN" for a, b in pairwise(names))


def _terminator_end(sql: str, start: int) -> int:
    r"""The offset just past the ``\.`` line at or after ``start`` (the end of the text if none)."""
    n = len(sql)
    i = start
    while i < n:
        newline = sql.find("\n", i)
        line_end = n if newline == -1 else newline
        if sql[i:line_end].rstrip("\r") == _COPY_TERMINATOR:
            return n if newline == -1 else newline + 1
        if newline == -1:
            break
        i = newline + 1
    return n


def _resume_index(sql: str, toks: list[Any], base: int, data_end: int) -> int | None:
    """Index of the first token at or after ``data_end`` if the scan is still in sync there.

    The scanner tokenised the data rows as if they were SQL. Its tokens after
    the block are trustworthy only if it was between tokens where the code
    resumes: a token starts exactly at the first code character and no earlier
    token spans the boundary. ``None`` means rescan.
    """
    code_start = data_end
    n = len(sql)
    while code_start < n and sql[code_start] in _WHITESPACE:
        code_start += 1
    j = 0
    while j < len(toks) and base + toks[j].start < data_end:
        j += 1
    if j and base + toks[j - 1].end >= data_end:
        return None
    if code_start >= n:
        return len(toks)
    if j < len(toks) and base + toks[j].start == code_start:
        return j
    return None
