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
