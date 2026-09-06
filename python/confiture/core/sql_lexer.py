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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pglast
import pglast.parser

_COMMENT_TOKENS = frozenset({"SQL_COMMENT", "C_COMMENT"})
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


def strip_comments(sql: str) -> str:
    """``sql`` with every ``--`` and ``/* */`` comment removed.

    Comment positions come from the scanner, so ``'a--b'``, ``"x--y"`` and
    ``$$ -- body $$`` are untouched. Line structure inside comments is dropped
    (the callers collapse whitespace); a line comment keeps the newline that
    ended it.
    """
    if "--" not in sql and "/*" not in sql:
        return sql
    out: list[str] = []
    pos = 0
    for token in pglast.parser.scan(sql):
        if token.name not in _COMMENT_TOKENS:
            continue
        out.append(sql[pos : token.start])
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
