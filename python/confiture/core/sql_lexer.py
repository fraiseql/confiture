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
- :func:`comments` / :func:`directives` — comment tokens, and the
  ``-- confiture:<name>`` directives among them with the statement each attaches to.
- :func:`blank_copy_blocks` — ``COPY … FROM stdin`` blocks blanked in place, so
  the text parses and every offset after a block is still its own.
- :func:`copy_blocks` — each ``COPY … FROM stdin`` block's statement and data
  rows, for a caller that hands the rows to the driver's ``COPY`` protocol.
- :func:`transaction_statements` — the statements that open, end or split a
  transaction, found by their first token rather than by a word in the text.
- :func:`blank_preserving_lines` — the same blanking over a whole string, for a
  caller that must hide a span from the parser without moving anything after it.
"""

from __future__ import annotations

from collections.abc import Iterator
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
# Bytes to scan ahead when looking for the next COPY block. Doubling from here
# rescans from scratch, so reaching a block d bytes away costs ~2d whatever the
# floor is; the floor only has to clear the statement that introduces one. Measured
# over 1600 dense blocks (a pg_dump seed, the shape #278 is about) and over blocks
# 3 KB apart: 128 costs 56.7 ms / 3.1x the file on the first and is within noise of
# every other value on the second, while 512 costs 105 ms / 9.0x and 4096 costs
# 645 ms / 55x.
_SCAN_WINDOW = 128
#: What a comment must start with to be a directive: ``-- confiture:<name> [argument]``.
DIRECTIVE_PREFIX = "confiture:"
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
class Comment:
    """A comment token: its inner text (stripped), 1-based line and kind (``line`` or ``block``)."""

    text: str
    line: int
    kind: str


@dataclass(frozen=True)
class Directive:
    """A ``-- confiture:<name> [argument]`` line comment and the statement it attaches to.

    ``name`` is case-folded; ``argument`` is the rest of the comment, stripped,
    or ``None``; ``statement_line`` is the line of the first code token after
    the comment when only comments and whitespace lie between — the statement
    the directive is written above — else ``None``.
    """

    name: str
    argument: str | None
    line: int
    statement_line: int | None


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


def string_constants(sql: str) -> list[tuple[int, int]]:
    """``(token start, content start)`` of every string constant, in source order.

    The content start is the offset past the opening delimiter — ``'``, ``E'``,
    ``U&'``, ``$$``, ``$tag$`` — which is where PostgreSQL starts counting a
    function body's lines, and therefore what turns ``parse_plpgsql``'s
    body-relative ``lineno`` into a line in the file. Where that delimiter ends
    is the scanner's question, so it is answered here and nowhere else.
    """
    return [
        (token.start, token.start + _opening_length(sql[token.start : token.end + 1]))
        for token in tokens(sql)
        if token.name in _STRING_TOKENS
    ]


def _opening_length(text: str) -> int:
    """How many characters of a string constant's text are its opening delimiter."""
    if text.startswith("$"):
        return text.index("$", 1) + 1
    return text.index("'") + 1


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


def _lex(sql: str) -> tuple[list[Any], list[tuple[int, int, int]]]:
    """(tokens outside COPY data, ``(start, data_start, end)`` of each COPY block).

    ``start`` is the statement's first character, ``data_start`` the first of its
    data rows, ``end`` just past its ``\\.`` line.
    """
    out: list[Any] = []
    blocks: list[tuple[int, int, int]] = []
    n = len(sql)
    toks = _scan_recovering(sql)
    windowed = False
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
        # Tokens are sorted by offset, so the run ends at the first one that is not —
        # searching from the semicolon rather than filtering the whole tail, which cost
        # O(tokens) per block and was the larger half of #278's quadratic.
        data_first = _index_at_or_after(toks, semicolon + 1, base, data_start)
        out.extend(_shift(toks[idx:data_first], base))
        data_end = _terminator_end(sql, data_start)
        blocks.append((base + toks[first].start, data_start, data_end))
        if data_end >= n:
            return out, blocks
        # A windowed scan is trusted for the one block it was grown to hold and no
        # further: its tokens stop at the window, not at the end of the file, so
        # resuming inside one would drop everything past it without a word. The
        # scanner tokenises `\.` quite happily (`ASCII_92`, `ASCII_46`), so a window
        # that reaches past a block's data really can look in sync at `data_end` —
        # measured, 1359 of 2198 windowed rescans over generated input. Dropping this
        # guard loses text, silently.
        resume = None if windowed else _resume_index(sql, toks, data_first, base, data_end)
        if resume is None:
            toks, windowed = _scan_after_block(sql, data_end)
            base = data_end
            idx = 0
        else:
            idx = resume


def _scan_after_block(sql: str, start: int) -> tuple[list[Any], bool]:
    """Tokens of ``sql[start:]`` scanned only as far as the next COPY block needs.

    Returns ``(tokens, windowed)``; offsets are relative to ``start``. ``windowed``
    is false when the tokens cover the whole of ``sql[start:]``, and true when they
    stop at a window that was grown until it held a complete ``COPY … FROM stdin;``.

    ``pglast.parser.scan`` reads its whole buffer however early its error is, so
    handing it the rest of the file after every block cost O(remaining) each time
    and O(n × total) for n blocks (issue #278). It only ever needs to reach the
    *next* block, and a prefix is safe to scan on its own because cutting text short
    can only destroy structure, never invent it: an unterminated string, comment or
    dollar quote makes the scanner error and ``_scan_recovering`` cuts back to
    before it, so a ``COPY … FROM stdin;`` found inside a window stands at that same
    offset in the whole text. A window holding no complete block is grown, never
    trusted.
    """
    remaining = len(sql) - start
    window = _SCAN_WINDOW
    while window < remaining:
        toks = _scan_recovering(sql[start : start + window])
        if _first_copy_statement(toks, 0) is not None:
            return toks, True
        window *= 2
    return _scan_recovering(sql[start:]), False


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


def _index_at_or_after(toks: list[Any], lo: int, base: int, offset: int) -> int:
    """Index of the first token from ``lo`` whose start is at or past ``offset``."""
    j = lo
    while j < len(toks) and base + toks[j].start < offset:
        j += 1
    return j


def _resume_index(sql: str, toks: list[Any], lo: int, base: int, data_end: int) -> int | None:
    """Index of the first token at or after ``data_end`` if the scan is still in sync there.

    The scanner tokenised the data rows as if they were SQL. Its tokens after
    the block are trustworthy only if it was between tokens where the code
    resumes: a token starts exactly at the first code character and no earlier
    token spans the boundary. ``None`` means rescan.

    ``lo`` is a token index known to sit at or before ``data_end`` — the search for
    the boundary starts there, so each block pays for its own data rather than for
    every token before it (#278).
    """
    code_start = data_end
    n = len(sql)
    while code_start < n and sql[code_start] in _WHITESPACE:
        code_start += 1
    j = _index_at_or_after(toks, lo, base, data_end)
    if j and base + toks[j - 1].end >= data_end:
        return None
    if code_start >= n:
        return len(toks)
    if j < len(toks) and base + toks[j].start == code_start:
        return j
    return None


# ---------------------------------------------------------------------------
# Comments and directives
# ---------------------------------------------------------------------------


def comments(sql: str) -> list[Comment]:
    """Every comment of ``sql`` — a token, so nothing inside a literal or a COPY row counts."""
    out: list[Comment] = []
    for token, line in _tokens_with_lines(sql):
        if token.name == "SQL_COMMENT":
            out.append(
                Comment(text=sql[token.start + 2 : token.end + 1].strip(), line=line, kind="line")
            )
        elif token.name == "C_COMMENT":
            out.append(
                Comment(text=sql[token.start + 2 : token.end - 1].strip(), line=line, kind="block")
            )
    return out


def directives(sql: str) -> list[Directive]:
    """The ``-- confiture:<name>`` line-comment directives of ``sql``, in order.

    Each rule used to find its directive with its own regex over lines, so a
    directive inside a dollar-quoted body or a COPY data row was one, and each
    rule attached it to "the next line" by its own walk. Here a directive is a
    comment *token*, and it attaches to the first statement after it (blank
    lines and other comments in between do not detach it). Block comments are
    not directives.
    """
    out: list[Directive] = []
    pending: list[tuple[str, str | None, int]] = []
    for token, line in _tokens_with_lines(sql):
        if token.name == "C_COMMENT":
            continue
        if token.name != "SQL_COMMENT":
            out.extend(Directive(n, a, at, line) for n, a, at in pending)
            pending = []
            continue
        text = sql[token.start + 2 : token.end + 1].strip()
        if text[: len(DIRECTIVE_PREFIX)].lower() != DIRECTIVE_PREFIX:
            continue
        parts = text[len(DIRECTIVE_PREFIX) :].split(None, 1)
        if parts:
            argument = parts[1].strip() if len(parts) > 1 else None
            pending.append((parts[0].lower(), argument or None, line))
    out.extend(Directive(n, a, at, None) for n, a, at in pending)
    return out


def _tokens_with_lines(sql: str) -> Iterator[tuple[Any, int]]:
    line = 1
    pos = 0
    for token in tokens(sql):
        line += sql.count("\n", pos, token.start)
        pos = token.start
        yield token, line


def blank_copy_blocks(sql: str) -> str:
    """``sql`` with its ``COPY … FROM stdin`` blocks blanked to spaces.

    Same length, same newlines, same line numbers: a character offset into the
    result is the same offset in ``sql``. That is the whole point — a lint reports
    ``file:line`` on every finding and ``parse_error_line`` counts newlines up
    to an index into the text it parsed, so deleting a block — which is what
    this replaced (#194) — silently moves every finding after it (#274).

    Do not "simplify" this back to a strip. The technique is #270's: when the
    parser must not see some characters but the caller must keep every
    position, blank them and leave the newlines alone.
    """
    _, blocks = _lex(sql)
    if not blocks:
        return sql
    parts: list[str] = []
    cursor = 0
    for start, _data_start, end in blocks:
        stop = min(end, len(sql))
        parts.append(sql[cursor:start])
        parts.append(blank_preserving_lines(sql[start:stop]))
        cursor = stop
    parts.append(sql[cursor:])
    return "".join(parts)


@dataclass(frozen=True)
class CopyBlock:
    """One ``COPY … FROM stdin`` block: its statement, then the rows psql would stream.

    ``start`` / ``end`` are its offsets in the text, ``end`` just past the ``\\.``
    line (the end of the text when there is none). ``statement`` runs from
    ``COPY`` to the end of its line; ``data`` is the rows, the terminator left out.
    """

    start: int
    end: int
    statement: str
    data: str


def copy_blocks(sql: str) -> list[CopyBlock]:
    """Every ``COPY … FROM stdin`` block in *sql*, in order.

    The rows are not SQL — psql reads them off its input and streams them — so a
    driver that runs a script must do the same: execute the text between blocks,
    and hand each block's rows to its ``COPY`` protocol.
    """
    found: list[CopyBlock] = []
    for start, data_start, end in _lex(sql)[1]:
        data = sql[data_start:end]
        body, _, last = data.rstrip("\n").rpartition("\n")
        if last.rstrip("\r") == _COPY_TERMINATOR:
            data = f"{body}\n" if body else ""
        found.append(
            CopyBlock(start=start, end=end, statement=sql[start:data_start].strip(), data=data)
        )
    return found


#: The first token of a statement that opens, ends or splits a transaction.
_TRANSACTION_TOKENS = frozenset(
    {"BEGIN_P", "COMMIT", "END_P", "ROLLBACK", "SAVEPOINT", "RELEASE", "ABORT_P"}
)
#: ``START TRANSACTION`` and ``PREPARE TRANSACTION``: two words, since ``PREPARE``
#: alone prepares a statement.
_TRANSACTION_PAIRS = frozenset({("START", "TRANSACTION"), ("PREPARE", "TRANSACTION")})


def transaction_statements(sql: str) -> int:
    """How many top-level statements in *sql* control a transaction.

    Read from the statements' first tokens: ``BEGIN`` inside a string, a
    ``DO`` body or COPY data is not a statement, and ``END`` closing a ``CASE``
    is not the first token of one.
    """
    code = [token.name for token in tokens(sql) if token.name not in _COMMENT_TOKENS]
    starts = [0, *(i + 1 for i, name in enumerate(code) if name == _SEMICOLON)]
    return sum(
        1
        for i in starts
        if i < len(code)
        and (code[i] in _TRANSACTION_TOKENS or tuple(code[i : i + 2]) in _TRANSACTION_PAIRS)
    )


def blank_preserving_lines(text: str) -> str:
    """``text`` with every character but its newlines replaced by a space.

    Same length, same line count, so an offset into the result is an offset into
    ``text``. The one way to hide a span from the parser without moving what
    follows it: :func:`blank_copy_blocks` uses it on a COPY block, and the lint
    uses it on a whole file pglast rejected (#274).
    """
    return "\n".join(" " * len(line) for line in text.split("\n"))
