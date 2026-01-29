"""Data models for git-based validation reports.

Provides structured representations of git validation results
for both human-readable and machine-readable output.
"""

from dataclasses import dataclass, field
from pathlib import Path

from confiture.models.schema import SchemaChange


@dataclass
class MigrationAccompanimentReport:
    """Report of migration accompaniment validation.

    Validates that DDL changes are accompanied by corresponding migration files.
    Useful for pre-commit hooks and CI/CD pipelines.

    Attributes:
        has_ddl_changes: Whether schema has DDL changes
        has_new_migrations: Whether new migration files exist
        ddl_changes: List of structural schema changes
        new_migration_files: List of new migration file paths
        migration_error: Optional error message if validation failed
        base_ref: Git reference used as base for comparison
        target_ref: Git reference used as target for comparison

    Example:
        >>> report = MigrationAccompanimentReport(
        ...     has_ddl_changes=True,
        ...     has_new_migrations=True,
        ...     ddl_changes=[SchemaChange(type="ADD_TABLE", table="users")],
        ...     new_migration_files=[Path("db/migrations/001_add_users.up.sql")],
        ... )
        >>> print(f"Valid: {report.is_valid}")
        Valid: True
    """

    has_ddl_changes: bool
    has_new_migrations: bool
    ddl_changes: list[SchemaChange] = field(default_factory=list)
    new_migration_files: list[Path] = field(default_factory=list)
    migration_error: str | None = None
    base_ref: str | None = None
    target_ref: str | None = None

    @property
    def is_valid(self) -> bool:
        """Check if accompaniment validation passed.

        Valid if either:
        - No DDL changes (nothing to accompany), or
        - DDL changes exist AND new migrations exist

        Returns:
            True if validation passed, False otherwise
        """
        if not self.has_ddl_changes:
            return True
        return self.has_new_migrations

    def summary(self) -> str:
        """Get human-readable summary of validation result.

        Returns:
            One-line summary (e.g., "Valid: DDL changes with 2 new migrations")
        """
        if not self.has_ddl_changes:
            return "No DDL changes"
        if self.is_valid:
            return f"Valid: {len(self.ddl_changes)} DDL changes, {len(self.new_migration_files)} migrations"
        return f"Invalid: {len(self.ddl_changes)} DDL changes but no migrations"

    def to_dict(self) -> dict:
        """Convert report to dictionary for JSON serialization.

        Returns:
            Dictionary representation with serializable types
        """
        return {
            "is_valid": self.is_valid,
            "has_ddl_changes": self.has_ddl_changes,
            "has_new_migrations": self.has_new_migrations,
            "ddl_changes": [
                {
                    "type": change.type,
                    "table": change.table,
                    "column": change.column,
                    "details": change.details,
                }
                for change in self.ddl_changes
            ],
            "new_migration_files": [f.as_posix() for f in self.new_migration_files],
            "migration_error": self.migration_error,
            "base_ref": self.base_ref,
            "target_ref": self.target_ref,
        }
