"""Data models for idempotency validation.

This module defines the core data structures used for tracking and reporting
idempotency violations in SQL migrations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IdempotencyPattern(Enum):
    """Patterns of non-idempotent SQL statements.

    Each pattern represents a type of SQL statement that is not idempotent
    by default and needs modification to be safely re-run.
    """

    CREATE_TABLE = "CREATE_TABLE"
    CREATE_INDEX = "CREATE_INDEX"
    CREATE_UNIQUE_INDEX = "CREATE_UNIQUE_INDEX"
    CREATE_FUNCTION = "CREATE_FUNCTION"
    CREATE_PROCEDURE = "CREATE_PROCEDURE"
    CREATE_VIEW = "CREATE_VIEW"
    CREATE_TYPE = "CREATE_TYPE"
    CREATE_EXTENSION = "CREATE_EXTENSION"
    CREATE_SCHEMA = "CREATE_SCHEMA"
    CREATE_SEQUENCE = "CREATE_SEQUENCE"
    ALTER_TABLE_ADD_COLUMN = "ALTER_TABLE_ADD_COLUMN"
    DROP_TABLE = "DROP_TABLE"
    DROP_INDEX = "DROP_INDEX"
    DROP_FUNCTION = "DROP_FUNCTION"
    DROP_VIEW = "DROP_VIEW"
    DROP_TYPE = "DROP_TYPE"
    DROP_SCHEMA = "DROP_SCHEMA"
    DROP_SEQUENCE = "DROP_SEQUENCE"

    @property
    def suggestion(self) -> str:
        """Get the suggestion for making this pattern idempotent."""
        suggestions = {
            IdempotencyPattern.CREATE_TABLE: "Use CREATE TABLE IF NOT EXISTS",
            IdempotencyPattern.CREATE_INDEX: "Use CREATE INDEX IF NOT EXISTS",
            IdempotencyPattern.CREATE_UNIQUE_INDEX: "Use CREATE UNIQUE INDEX IF NOT EXISTS",
            IdempotencyPattern.CREATE_FUNCTION: "Use CREATE OR REPLACE FUNCTION",
            IdempotencyPattern.CREATE_PROCEDURE: "Use CREATE OR REPLACE PROCEDURE",
            IdempotencyPattern.CREATE_VIEW: "Use CREATE OR REPLACE VIEW",
            IdempotencyPattern.CREATE_TYPE: "Wrap in DO block with pg_type check",
            IdempotencyPattern.CREATE_EXTENSION: "Use CREATE EXTENSION IF NOT EXISTS",
            IdempotencyPattern.CREATE_SCHEMA: "Use CREATE SCHEMA IF NOT EXISTS",
            IdempotencyPattern.CREATE_SEQUENCE: "Use CREATE SEQUENCE IF NOT EXISTS",
            IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: (
                "Wrap in DO block with EXCEPTION handler for duplicate_column"
            ),
            IdempotencyPattern.DROP_TABLE: "Use DROP TABLE IF EXISTS",
            IdempotencyPattern.DROP_INDEX: "Use DROP INDEX IF EXISTS",
            IdempotencyPattern.DROP_FUNCTION: "Use DROP FUNCTION IF EXISTS",
            IdempotencyPattern.DROP_VIEW: "Use DROP VIEW IF EXISTS",
            IdempotencyPattern.DROP_TYPE: "Use DROP TYPE IF EXISTS",
            IdempotencyPattern.DROP_SCHEMA: "Use DROP SCHEMA IF EXISTS",
            IdempotencyPattern.DROP_SEQUENCE: "Use DROP SEQUENCE IF EXISTS",
        }
        return suggestions.get(self, "Make statement idempotent")

    @property
    def fix_available(self) -> bool:
        """Check if automatic fix is available for this pattern."""
        fixable = {
            IdempotencyPattern.CREATE_TABLE,
            IdempotencyPattern.CREATE_INDEX,
            IdempotencyPattern.CREATE_UNIQUE_INDEX,
            IdempotencyPattern.CREATE_FUNCTION,
            IdempotencyPattern.CREATE_PROCEDURE,
            IdempotencyPattern.CREATE_VIEW,
            IdempotencyPattern.CREATE_EXTENSION,
            IdempotencyPattern.CREATE_SCHEMA,
            IdempotencyPattern.CREATE_SEQUENCE,
            IdempotencyPattern.ALTER_TABLE_ADD_COLUMN,
            IdempotencyPattern.DROP_TABLE,
            IdempotencyPattern.DROP_INDEX,
            IdempotencyPattern.DROP_FUNCTION,
            IdempotencyPattern.DROP_VIEW,
            IdempotencyPattern.DROP_TYPE,
            IdempotencyPattern.DROP_SCHEMA,
            IdempotencyPattern.DROP_SEQUENCE,
        }
        return self in fixable


@dataclass
class IdempotencyViolation:
    """Represents a single idempotency violation in a SQL migration.

    Attributes:
        pattern: The type of non-idempotent pattern detected
        sql_snippet: The SQL code that triggered the violation
        line_number: Line number in the file where violation occurs
        file_path: Path to the migration file
    """

    pattern: IdempotencyPattern
    sql_snippet: str
    line_number: int
    file_path: str

    @property
    def suggestion(self) -> str:
        """Get suggestion for fixing this violation."""
        return self.pattern.suggestion

    @property
    def fix_available(self) -> bool:
        """Check if automatic fix is available."""
        return self.pattern.fix_available

    def __str__(self) -> str:
        """Format violation for human-readable output."""
        return (
            f"{self.file_path}:{self.line_number} - {self.pattern.name}: {self.sql_snippet[:50]}..."
            if len(self.sql_snippet) > 50
            else f"{self.file_path}:{self.line_number} - {self.pattern.name}: {self.sql_snippet}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "pattern": self.pattern.name,
            "sql_snippet": self.sql_snippet,
            "line_number": self.line_number,
            "file_path": self.file_path,
            "suggestion": self.suggestion,
            "fix_available": self.fix_available,
        }


@dataclass
class IdempotencyReport:
    """Report of idempotency validation results.

    Tracks all violations found during validation and which files were scanned.

    Example:
        >>> report = IdempotencyReport()
        >>> report.add_file_scanned("001_init.up.sql")
        >>> report.add_violation(violation)
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} issues")
    """

    violations: list[IdempotencyViolation] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Check if any violations were found."""
        return len(self.violations) > 0

    @property
    def violation_count(self) -> int:
        """Get total number of violations."""
        return len(self.violations)

    @property
    def files_scanned(self) -> int:
        """Get number of files scanned."""
        return len(self.scanned_files)

    def add_violation(self, violation: IdempotencyViolation) -> None:
        """Add a violation to the report.

        Args:
            violation: The violation to add
        """
        self.violations.append(violation)

    def add_file_scanned(self, file_path: str) -> None:
        """Record that a file was scanned.

        Args:
            file_path: Path to the scanned file
        """
        if file_path not in self.scanned_files:
            self.scanned_files.append(file_path)

    def violations_by_file(self) -> dict[str, list[IdempotencyViolation]]:
        """Group violations by file path.

        Returns:
            Dictionary mapping file paths to their violations
        """
        by_file: dict[str, list[IdempotencyViolation]] = defaultdict(list)
        for violation in self.violations:
            by_file[violation.file_path].append(violation)
        return dict(by_file)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "violations": [v.to_dict() for v in self.violations],
            "violation_count": self.violation_count,
            "files_scanned": self.files_scanned,
            "scanned_files": self.scanned_files,
            "has_violations": self.has_violations,
        }

    def __str__(self) -> str:
        """Format report for human-readable output."""
        lines = [
            f"Idempotency Report: {self.files_scanned} files scanned, "
            f"{self.violation_count} violations found"
        ]
        if self.has_violations:
            for file_path, file_violations in self.violations_by_file().items():
                lines.append(f"\n{file_path}:")
                for v in file_violations:
                    lines.append(f"  Line {v.line_number}: {v.pattern.name}")
                    lines.append(f"    Suggestion: {v.suggestion}")
        return "\n".join(lines)
