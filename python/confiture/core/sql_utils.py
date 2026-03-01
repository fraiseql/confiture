"""Shared SQL utility functions."""

import re

# Matches lines that are exactly BEGIN[;] or COMMIT[;] (with optional whitespace)
_TRANSACTION_LINE_RE = re.compile(r"^\s*(BEGIN|COMMIT)\s*;?\s*$", re.IGNORECASE)


def strip_transaction_wrappers(sql: str, *, return_changed: bool = False) -> str | tuple[str, bool]:
    """Remove standalone BEGIN/COMMIT lines from SQL.

    Strips lines that are exactly BEGIN or COMMIT (with or without semicolons,
    case-insensitive). Preserves all other SQL, collapsing redundant leading/
    trailing blank lines to at most one.

    Used by:
    - FileSQLMigration: strips wrappers before savepoint-based execution
    - MigrationGenerator: strips wrappers from external generator output

    Args:
        sql: Raw SQL string.
        return_changed: If True, returns a (sql, changed) tuple where
            ``changed`` is True when at least one line was removed.

    Returns:
        Cleaned SQL string, or a (sql, changed) tuple when return_changed=True.
    """
    lines = sql.splitlines()
    filtered = [line for line in lines if not _TRANSACTION_LINE_RE.match(line)]
    changed = len(filtered) != len(lines)

    # Remove leading blank lines
    while filtered and not filtered[0].strip():
        filtered.pop(0)

    # Remove trailing blank lines
    while filtered and not filtered[-1].strip():
        filtered.pop()

    result = "\n".join(filtered) + "\n" if filtered else ""

    if return_changed:
        return result, changed
    return result
