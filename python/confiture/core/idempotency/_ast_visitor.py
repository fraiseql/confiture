"""AST visitor scaffolding for the idempotency detector.

This module provides shared helpers for the pglast-backed detector:

- :func:`_first_keyword_pos` skips leading whitespace and comments to find
  the position of the first real keyword of a statement.
- :func:`_line_for_stmt` maps a parsed statement to its 1-indexed line
  number in the source SQL.
- :func:`_extract_snippet_from_stmt` slices the source SQL using the
  statement's reported location/length, then normalizes whitespace.

The detector entry point lives in :mod:`ast_detector`; visitors land in
later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SNIPPET_MAX_LENGTH = 80
_SNIPPET_TRAILING_PAD = 50


def _first_keyword_pos(sql: str, start: int) -> int:
    """Skip whitespace and SQL comments from ``start`` to the first keyword.

    Mirrors what a human would do reading the source: jump over leading
    blanks, ``-- line comments``, and ``/* block comments */`` until a
    real token appears.
    """
    i = start
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in " \t\n\r\f\v":
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


def _line_for_stmt(sql: str, stmt_location: int) -> int:
    """Return the 1-indexed line number where the statement keyword begins."""
    pos = _first_keyword_pos(sql, stmt_location)
    return sql[:pos].count("\n") + 1


def _extract_snippet_from_stmt(sql: str, stmt_location: int, stmt_len: int) -> str:
    """Extract a normalized snippet of the statement at ``stmt_location``.

    Mirrors the regex backend's snippet normalization (whitespace
    collapsed, max length 80 with ``...`` ellipsis, trailing semicolon
    included when present) so violation output is comparable across
    backends and the fixer's snippet-based ``suggested_fix`` output
    matches byte-for-byte.
    """
    start = _first_keyword_pos(sql, stmt_location)
    # ``stmt_len`` from pglast excludes the trailing semicolon; include it
    # when present so the snippet matches the regex backend's slice.
    end = stmt_location + stmt_len if stmt_len else len(sql)
    if end <= start:
        end = min(start + _SNIPPET_TRAILING_PAD, len(sql))
    semicolon = sql.find(";", start)
    if semicolon != -1 and semicolon < end + _SNIPPET_TRAILING_PAD:
        end = max(end, semicolon + 1)
    raw = sql[start:end].strip()
    raw = " ".join(raw.split())
    if len(raw) > _SNIPPET_MAX_LENGTH:
        raw = raw[:_SNIPPET_MAX_LENGTH] + "..."
    return raw


@dataclass
class _StatementContext:
    """A single top-level statement plus its source-text coordinates."""

    stmt: Any
    stmt_location: int
    stmt_len: int


def _iter_statements(sql: str, pglast: Any) -> list[_StatementContext]:
    """Parse ``sql`` with pglast and yield one context per top-level statement.

    Raises whatever ``pglast.parse_sql`` raises on parse failure — the
    dispatcher is responsible for catching ``pglast.parser.ParseError``
    and falling through to the regex backend.
    """
    tree = pglast.parse_sql(sql)
    if tree is None:
        return []
    contexts: list[_StatementContext] = []
    for raw in tree:
        contexts.append(
            _StatementContext(
                stmt=raw.stmt,
                stmt_location=raw.stmt_location or 0,
                stmt_len=raw.stmt_len or 0,
            )
        )
    return contexts
