"""Data models for git-based validation reports.

Provides structured representations of git validation results
for both human-readable and machine-readable output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.models.schema import SchemaChange

if TYPE_CHECKING:
    from confiture.core.function_signature_checker import FunctionSignatureViolation


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
    signature_violations: list[FunctionSignatureViolation] = field(default_factory=list)

    @property
    def has_signature_violations(self) -> bool:
        """True if any function parameter type changes lack a DROP FUNCTION migration."""
        return len(self.signature_violations) > 0

    @property
    def is_valid(self) -> bool:
        """Check if accompaniment validation passed.

        Valid if:
        - No DDL changes (nothing to accompany), or
        - DDL changes exist AND new migrations exist
        AND no function signature violations.

        Returns:
            True if validation passed, False otherwise
        """
        if self.has_signature_violations:
            return False
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
            "signature_violations": [v.to_dict() for v in self.signature_violations],
        }


@dataclass
class GrantAccompanimentReport:
    """Report of grant accompaniment validation.

    Validates that changes to grant files (db/7_grant/) are accompanied
    by migration files, since migrate environments only apply grants
    through migration files.

    Attributes:
        has_grant_changes: Whether any grant files changed
        has_migration_changes: Whether any .up.sql migration files changed
        grant_files_changed: List of changed grant file paths
        migration_files_staged: List of staged migration file paths

    Example:
        >>> report = GrantAccompanimentReport(
        ...     has_grant_changes=True,
        ...     has_migration_changes=False,
        ...     grant_files_changed=[Path("db/7_grant/grants.sql")],
        ...     migration_files_staged=[],
        ... )
        >>> print(f"Valid: {report.is_valid}")
        Valid: False
    """

    has_grant_changes: bool
    has_migration_changes: bool
    grant_files_changed: list[Path] = field(default_factory=list)
    migration_files_staged: list[Path] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Valid when no grant changes, or grant changes + migration present."""
        return (not self.has_grant_changes) or self.has_migration_changes

    def summary(self) -> str:
        """Get human-readable summary of validation result."""
        if not self.has_grant_changes:
            return "No grant file changes"
        if self.is_valid:
            return f"Grant changes accompanied by {len(self.migration_files_staged)} migration(s)"
        return f"Grant changes without migration files ({len(self.grant_files_changed)} file(s) changed)"

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "has_grant_changes": self.has_grant_changes,
            "has_migration_changes": self.has_migration_changes,
            "grant_files_changed": [f.as_posix() for f in self.grant_files_changed],
            "migration_files_staged": [f.as_posix() for f in self.migration_files_staged],
        }
