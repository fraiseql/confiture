"""Shared SQL utility functions.

This module hosts a small, module-private SQL scanner used to make
``strip_transaction_wrappers`` dollar-quote-aware (#132). The scanner
distinguishes top-level SQL lines from lines that live inside single-quoted
strings, ``--`` line comments, ``/* ... */`` block comments, or
``$tag$ ... $tag$`` dollar-quoted blocks.

A line is considered top-level (and therefore eligible for the transaction-
wrapper stripper) iff:

* the scanner's state at the line's start OR end is ``NORMAL``
  (so the first/last line of a ``DO $$ ... $$;`` block counts as top-level
  even though it transitions in/out of the block on that same line), AND
* the line contains no string or comment transition (so
  ``INSERT INTO t VALUES ('BEGIN');`` is NOT top-level — its embedded
  string would taint a wrapper-regex match).

Known limitations:

* PostgreSQL allows nested block comments; this scanner implements the
  simpler ANSI behavior — the first ``*/`` closes the block. The
  practical impact on the stripper is minimal because the trailing
  fragment of a nested-comment construct never matches the wrapper regex.
* ``COPY t FROM stdin;`` followed by inline data rows is not modeled.
  psycopg uses the dedicated ``copy()`` API, so such SQL is already
  broken when run through ``execute()`` — the scanner does not try to
  preserve it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# Matches lines that are exactly BEGIN[;] or COMMIT[;] (with optional whitespace).
# Trailing ``\s*`` tolerates ``\r`` (CRLF line endings) after rstrip(\n).
_TRANSACTION_LINE_RE = re.compile(r"^\s*(BEGIN|COMMIT)\s*;?\s*$", re.IGNORECASE)

# Matches a PostgreSQL dollar-quote tag: $tag$ where tag matches
# [A-Za-z_][A-Za-z_0-9]*, or empty ($$).
_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_]\w*)?\$")


def _iter_top_level_lines(sql: str) -> Iterator[tuple[int, str, bool]]:
    """Yield ``(line_index, line_text, is_top_level)`` for each line in ``sql``.

    See the module docstring for the precise definition of ``is_top_level``.
    The scanner walks every line; callers decide what to do with the lines
    that are inside dollar-quoted blocks (the stripper preserves them
    verbatim).
    """
    n = len(sql)
    if n == 0:
        return

    state = "NORMAL"
    dollar_tag = ""  # full literal tag (e.g. "$$" or "$body$") when IN_DOLLAR_QUOTE

    line_index = 0
    line_start = 0
    line_entry_state = "NORMAL"
    has_non_dollar_transition = False

    i = 0
    while i < n:
        c = sql[i]

        # Newline handling — close line comment first, then emit.
        if c == "\n":
            if state == "IN_LINE_COMMENT":
                state = "NORMAL"
            line_text = sql[line_start : i + 1]
            is_top = (
                line_entry_state == "NORMAL" or state == "NORMAL"
            ) and not has_non_dollar_transition
            yield line_index, line_text, is_top
            line_index += 1
            line_start = i + 1
            line_entry_state = state
            has_non_dollar_transition = False
            i += 1
            continue

        if state == "NORMAL":
            m = _DOLLAR_TAG_RE.match(sql, i)
            if m:
                # Dollar-quote opener — does not count as a string/comment
                # transition for top-level purposes.
                dollar_tag = m.group(0)
                state = "IN_DOLLAR_QUOTE"
                i = m.end()
                continue
            if c == "-" and i + 1 < n and sql[i + 1] == "-":
                has_non_dollar_transition = True
                state = "IN_LINE_COMMENT"
                i += 2
                continue
            if c == "/" and i + 1 < n and sql[i + 1] == "*":
                has_non_dollar_transition = True
                state = "IN_BLOCK_COMMENT"
                i += 2
                continue
            if c == "'":
                has_non_dollar_transition = True
                state = "IN_STRING"
                i += 1
                continue
            i += 1
        elif state == "IN_STRING":
            if c == "'":
                # Doubled '' is an escaped quote, not a close.
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                has_non_dollar_transition = True  # closing the string
                state = "NORMAL"
                i += 1
                continue
            i += 1
        elif state == "IN_LINE_COMMENT":
            # Newline is handled at the top of the loop; everything else stays in-comment.
            i += 1
        elif state == "IN_BLOCK_COMMENT":
            if c == "*" and i + 1 < n and sql[i + 1] == "/":
                has_non_dollar_transition = True  # closing the block comment
                state = "NORMAL"
                i += 2
                continue
            i += 1
        elif state == "IN_DOLLAR_QUOTE":
            # Only the literal matching tag closes the block; ``$$`` inside
            # ``$body$ ... $body$`` is literal text.
            if c == "$" and sql.startswith(dollar_tag, i):
                tag_len = len(dollar_tag)
                state = "NORMAL"
                dollar_tag = ""
                i += tag_len
                continue
            i += 1

    # Trailing line without a terminating newline.
    if line_start < n:
        line_text = sql[line_start:n]
        is_top = (
            line_entry_state == "NORMAL" or state == "NORMAL"
        ) and not has_non_dollar_transition
        yield line_index, line_text, is_top


def strip_transaction_wrappers(sql: str, *, return_changed: bool = False) -> str | tuple[str, bool]:
    """Remove standalone TOP-LEVEL BEGIN/COMMIT lines from SQL.

    "Top-level" means outside any single-quoted string, ``--`` line comment,
    ``/* ... */`` block comment, or ``$tag$ ... $tag$`` dollar-quoted block.
    A ``BEGIN`` line inside a ``DO $$ ... $$`` block is preserved — that's
    PL/pgSQL syntax, not a transaction command (#132).

    Strips lines that are exactly BEGIN or COMMIT (with or without semicolons,
    case-insensitive). Preserves all other SQL, collapsing redundant leading/
    trailing blank lines to at most one.

    Used by:

    * ``FileSQLMigration``: strips wrappers before savepoint-based execution.
    * ``MigrationGenerator``: strips wrappers from external generator output.

    Args:
        sql: Raw SQL string.
        return_changed: If True, returns a ``(sql, changed)`` tuple where
            ``changed`` is True when at least one line was removed.

    Returns:
        Cleaned SQL string, or a ``(sql, changed)`` tuple when
        ``return_changed=True``.
    """
    out_lines: list[str] = []
    changed = False

    for _idx, line, is_top_level in _iter_top_level_lines(sql):
        # Strip trailing newline before regex match so the regex anchors
        # against the line content. _TRANSACTION_LINE_RE's trailing ``\s*``
        # tolerates ``\r`` (CRLF line endings).
        match_target = line.rstrip("\n")
        if is_top_level and _TRANSACTION_LINE_RE.match(match_target):
            changed = True
            continue
        out_lines.append(line)

    # Collapse leading/trailing blank lines (preserve pre-existing behavior).
    while out_lines and not out_lines[0].strip():
        out_lines.pop(0)
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()

    result = "".join(out_lines)
    if result and not result.endswith("\n"):
        result += "\n"

    if return_changed:
        return result, changed
    return result
