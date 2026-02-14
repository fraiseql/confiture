"""Command result models for structured output.

Provides dataclasses for capturing and serializing command execution
results in JSON/CSV formats. These models ensure consistent output
across all commands that support structured output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BuildResult:
    """Result of schema build operation.

    Tracks success/failure, files processed, size, timing, and any
    warnings or errors that occurred during build.
    """

    success: bool
    files_processed: int
    schema_size_bytes: int
    output_path: str
    hash: str | None = None
    execution_time_ms: int = 0
    seed_files_applied: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "success": self.success,
            "files_processed": self.files_processed,
            "schema_size_bytes": self.schema_size_bytes,
            "output_path": self.output_path,
            "hash": self.hash,
            "execution_time_ms": self.execution_time_ms,
            "seed_files_applied": self.seed_files_applied,
            "warnings": self.warnings,
            "error": self.error,
        }


@dataclass
class MigrationApplied:
    """Single migration that was applied.

    Tracks version, name, execution time, and rows affected.
    """

    version: str
    name: str
    execution_time_ms: int
    rows_affected: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "version": self.version,
            "name": self.name,
            "execution_time_ms": self.execution_time_ms,
            "rows_affected": self.rows_affected,
        }


@dataclass
class MigrateUpResult:
    """Result of migrate up operation.

    Tracks which migrations were applied, total execution time,
    checksum verification status, and any warnings or errors.
    """

    success: bool
    migrations_applied: list[MigrationApplied]
    total_execution_time_ms: int
    checksums_verified: bool = True
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "success": self.success,
            "migrations_applied": [m.to_dict() for m in self.migrations_applied],
            "count": len(self.migrations_applied),
            "total_execution_time_ms": self.total_execution_time_ms,
            "checksums_verified": self.checksums_verified,
            "dry_run": self.dry_run,
            "warnings": self.warnings,
            "error": self.error,
        }


@dataclass
class MigrateDownResult:
    """Result of migrate down operation.

    Tracks which migrations were rolled back, total execution time,
    and any warnings or errors that occurred.
    """

    success: bool
    migrations_rolled_back: list[MigrationApplied]
    total_execution_time_ms: int
    checksums_verified: bool = True
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "success": self.success,
            "migrations_rolled_back": [m.to_dict() for m in self.migrations_rolled_back],
            "count": len(self.migrations_rolled_back),
            "total_execution_time_ms": self.total_execution_time_ms,
            "checksums_verified": self.checksums_verified,
            "warnings": self.warnings,
            "error": self.error,
        }


@dataclass
class SchemaChange:
    """A single schema change detected in diff.

    Tracks the type of change and details about what changed.
    """

    change_type: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.change_type,
            "details": self.details,
        }


@dataclass
class MigrateDiffResult:
    """Result of schema diff operation.

    Tracks differences between two schemas and whether a migration
    was generated from the diff.
    """

    success: bool
    has_changes: bool
    changes: list[SchemaChange] = field(default_factory=list)
    migration_generated: bool = False
    migration_file: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "success": self.success,
            "has_changes": self.has_changes,
            "changes": [c.to_dict() for c in self.changes],
            "change_count": len(self.changes),
            "migration_generated": self.migration_generated,
            "migration_file": self.migration_file,
            "error": self.error,
        }


@dataclass
class MigrateValidateResult:
    """Result of migration validation operation.

    Tracks validation checks performed and any issues found.
    """

    success: bool
    orphaned_files: list[str] = field(default_factory=list)
    duplicate_versions: dict[str, list[str]] = field(default_factory=dict)
    fixed_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "success": self.success,
            "orphaned_files": self.orphaned_files,
            "orphaned_files_count": len(self.orphaned_files),
            "duplicate_versions": self.duplicate_versions,
            "duplicate_versions_count": len(self.duplicate_versions),
            "fixed_files": self.fixed_files,
            "fixed_files_count": len(self.fixed_files),
            "warnings": self.warnings,
            "error": self.error,
        }


@dataclass
class ConversionResult:
    """Result of converting a single INSERT statement to COPY format.

    Tracks whether conversion was successful, the converted output,
    number of rows converted, or failure reason if conversion failed.
    """

    file_path: str
    success: bool
    copy_format: str | None = None
    rows_converted: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "file_path": self.file_path,
            "success": self.success,
            "copy_format": self.copy_format,
            "rows_converted": self.rows_converted,
            "reason": self.reason,
        }


@dataclass
class ConversionReport:
    """Report of batch INSERT to COPY conversion.

    Aggregates results from converting multiple seed files,
    tracking success/failure counts and providing overall metrics.
    """

    total_files: int
    successful: int
    failed: int
    results: list[ConversionResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage.

        Returns:
            Percentage of successful conversions (0-100).
        """
        if self.total_files == 0:
            return 0.0
        return (self.successful / self.total_files) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields suitable for JSON output.
        """
        return {
            "total_files": self.total_files,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": self.success_rate,
            "results": [r.to_dict() for r in self.results],
        }
