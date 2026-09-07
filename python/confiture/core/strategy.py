"""Migration strategy header parser.

Parses ``-- Strategy: <name>`` headers from SQL migration files.
The header must appear within the first 10 lines of the file.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.sql_lexer import comments

_HEADER = "strategy:"
_MAX_HEADER_LINES = 10


def parse_migration_strategy(sql: str) -> str | None:
    """Extract strategy name from a SQL migration string.

    Looks for a ``-- Strategy: <name>`` line comment in the first 10 lines —
    a comment token, so the same text inside a dollar-quoted body is not one.

    Args:
        sql: Raw SQL content.

    Returns:
        Lowercase strategy name, or None if no header found.
    """
    for comment in comments(sql):
        if comment.line > _MAX_HEADER_LINES:
            break
        if comment.kind == "line" and comment.text[: len(_HEADER)].lower() == _HEADER:
            value = comment.text[len(_HEADER) :].strip().lower()
            if value:
                return value
    return None


def parse_file_strategy(path: Path) -> str | None:
    """Extract strategy name from a SQL migration file.

    Args:
        path: Path to the migration file.

    Returns:
        Lowercase strategy name, or None if no header found.
    """
    return parse_migration_strategy(path.read_text())


def find_rebuild_strategy_files(migrations_dir: Path) -> list[Path]:
    """Find migration files with ``-- Strategy: rebuild`` header.

    Args:
        migrations_dir: Directory containing migration files.

    Returns:
        Sorted list of paths whose strategy is ``rebuild``.
    """
    result: list[Path] = []
    if not migrations_dir.is_dir():
        return result
    result.extend(
        path
        for path in sorted(migrations_dir.glob("*.up.sql"))
        if parse_file_strategy(path) == "rebuild"
    )
    return result
