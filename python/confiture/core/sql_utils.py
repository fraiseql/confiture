"""Shared SQL utility functions.

:func:`strip_transaction_wrappers` removes the ``BEGIN`` / ``COMMIT`` lines a
migration file wraps itself in, so the file can run under confiture's own
transaction and savepoints (#64). Only a *top-level* wrapper is a wrapper: the
``BEGIN`` of a ``DO $$ … $$`` block is PL/pgSQL, ``'BEGIN'`` is a string, and
``-- BEGIN`` is a comment (#132). What is code on a line comes from
:func:`confiture.core.sql_lexer.code_text` — libpg_query's scanner, not a
scanner of this module's own.
"""

from __future__ import annotations

from confiture.core.sql_lexer import code_text

_WRAPPERS = frozenset({"BEGIN", "COMMIT"})


def _is_transaction_wrapper(code_line: str) -> bool:
    """A line whose code is exactly ``BEGIN`` or ``COMMIT``, with at most one ``;``."""
    words = code_line.replace(";", " ").split()
    return len(words) == 1 and words[0].upper() in _WRAPPERS and code_line.count(";") <= 1


def strip_transaction_wrappers(sql: str, *, return_changed: bool = False) -> str | tuple[str, bool]:
    """Remove standalone TOP-LEVEL BEGIN/COMMIT lines from SQL.

    "Top-level" means outside any string literal, ``--`` line comment,
    ``/* ... */`` block comment, or ``$tag$ ... $tag$`` dollar-quoted block.
    A ``BEGIN`` line inside a ``DO $$ ... $$`` block is preserved — that's
    PL/pgSQL syntax, not a transaction command (#132).

    Strips lines whose code is exactly BEGIN or COMMIT (with or without a
    semicolon, case-insensitive; a trailing comment does not keep the line).
    Preserves all other SQL, collapsing redundant leading/trailing blank
    lines to at most one.

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

    code_lines = code_text(sql).text.split("\n")
    for raw, code in zip(sql.split("\n"), code_lines, strict=True):
        if _is_transaction_wrapper(code):
            changed = True
            continue
        out_lines.append(raw)

    # Collapse leading/trailing blank lines (preserve pre-existing behavior).
    while out_lines and not out_lines[0].strip():
        out_lines.pop(0)
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()

    result = "\n".join(out_lines)
    if result and not result.endswith("\n"):
        result += "\n"

    if return_changed:
        return result, changed
    return result
