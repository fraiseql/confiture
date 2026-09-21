"""Confiture migration models.

This module provides the base classes for creating migrations:
- Migration: Abstract base class for Python migrations
- SQLMigration: Convenience class for SQL-only migrations with up_sql/down_sql attributes
- FileSQLMigration: Migrations loaded from .up.sql/.down.sql file pairs
"""

from importlib import import_module
from typing import Any

#: Each public name, and the module it is defined in. Resolved on first use, so
#: that importing ``confiture.models.error`` does not run the migration runtime —
#: which imports ``core`` — as ``confiture.exceptions`` is being initialised.
_LAZY: dict[str, str] = {
    "FileSQLMigration": "confiture.models.sql_file_migration",
    "Migration": "confiture.models.migration",
    "SQLMigration": "confiture.models.migration",
    "find_sql_migration_files": "confiture.models.sql_file_migration",
    "get_sql_migration_version": "confiture.models.sql_file_migration",
}

__all__ = [
    "FileSQLMigration",
    # Base migration classes
    "Migration",
    "SQLMigration",
    # SQL file discovery
    "find_sql_migration_files",
    "get_sql_migration_version",
]


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(import_module(module), name)
