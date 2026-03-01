"""Migration strategy header parser.

Parses ``-- Strategy: <name>`` headers from SQL migration files.
The header must appear within the first 10 lines of the file.
"""

from __future__ import annotations

import re
from pathlib import Path

_STRATEGY_RE = re.compile(r"^--\s*Strategy:\s*(.+)$", re.IGNORECASE)

_MAX_HEADER_LINES = 10


def parse_migration_strategy(sql: str) -> str | None:
    """Extract strategy name from a SQL migration string.

    Looks for ``-- Strategy: <name>`` in the first 10 lines.

    Args:
        sql: Raw SQL content.

    Returns:
        Lowercase strategy name, or None if no header found.
    """
    for line in sql.splitlines()[:_MAX_HEADER_LINES]:
        m = _STRATEGY_RE.match(line)
        if m:
            return m.group(1).strip().lower()
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
    for path in sorted(migrations_dir.glob("*.up.sql")):
        if parse_file_strategy(path) == "rebuild":
            result.append(path)
    return result
