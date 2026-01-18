"""Confiture migration models.

This module provides the base classes for creating migrations:
- Migration: Abstract base class for Python migrations
- SQLMigration: Convenience class for SQL-only migrations with up_sql/down_sql attributes
- FileSQLMigration: Migrations loaded from .up.sql/.down.sql file pairs
"""

from confiture.models.migration import Migration, SQLMigration
from confiture.models.sql_file_migration import (
    FileSQLMigration,
    find_sql_migration_files,
    get_sql_migration_version,
)

__all__ = [
    # Base migration classes
    "Migration",
    "SQLMigration",
    "FileSQLMigration",
    # SQL file discovery
    "find_sql_migration_files",
    "get_sql_migration_version",
]
