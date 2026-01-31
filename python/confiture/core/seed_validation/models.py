"""Data models for seed validation.

This module defines the core data structures used for tracking and reporting
seed data validation violations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SeedValidationPattern(Enum):
    """Patterns of seed data validation issues.

    Each pattern represents a type of issue that can occur in seed files
    and should be corrected for data consistency.
    """

    DOUBLE_SEMICOLON = "DOUBLE_SEMICOLON"
    NON_INSERT_STATEMENT = "NON_INSERT_STATEMENT"
    MISSING_ON_CONFLICT = "MISSING_ON_CONFLICT"
    INVALID_UUID_FORMAT = "INVALID_UUID_FORMAT"
    COLUMN_VALUE_MISMATCH = "COLUMN_VALUE_MISMATCH"

    @property
    def suggestion(self) -> str:
        """Get the suggestion for fixing this pattern."""
        suggestions = {
            SeedValidationPattern.DOUBLE_SEMICOLON: "Remove the extra semicolon (;;)",
            SeedValidationPattern.NON_INSERT_STATEMENT: (
                "Seed files should only contain INSERT statements"
            ),
            SeedValidationPattern.MISSING_ON_CONFLICT: (
                "Add ON CONFLICT clause to handle duplicate inserts"
            ),
            SeedValidationPattern.INVALID_UUID_FORMAT: "Use valid UUID format (v4)",
            SeedValidationPattern.COLUMN_VALUE_MISMATCH: (
                "Ensure column count matches value count"
            ),
        }
        return suggestions.get(self, "Fix the seed data issue")

    @property
    def fix_available(self) -> bool:
        """Check if automatic fix is available for this pattern."""
        fixable = {
            SeedValidationPattern.MISSING_ON_CONFLICT,
        }
        return self in fixable


@dataclass
class SeedViolation:
    """Represents a single seed validation violation.

    Attributes:
        pattern: The type of seed validation issue detected
        sql_snippet: The SQL code that triggered the violation
        line_number: Line number in the file where violation occurs
        file_path: Path to the seed file
    """

    pattern: SeedValidationPattern
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
        snippet = (
            f"{self.sql_snippet[:50]}..."
            if len(self.sql_snippet) > 50
            else self.sql_snippet
        )
        return f"{self.file_path}:{self.line_number} - {self.pattern.name}: {snippet}"

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
class SeedValidationReport:
    """Report of seed validation results.

    Tracks all violations found during validation and which files were scanned.

    Example:
        >>> report = SeedValidationReport()
        >>> report.add_file_scanned("001_seed.sql")
        >>> report.add_violation(violation)
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} issues")
    """

    violations: list[SeedViolation] = field(default_factory=list)
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

    def add_violation(self, violation: SeedViolation) -> None:
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

    def violations_by_file(self) -> dict[str, list[SeedViolation]]:
        """Group violations by file path.

        Returns:
            Dictionary mapping file paths to their violations
        """
        by_file: dict[str, list[SeedViolation]] = defaultdict(list)
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
            f"Seed Validation Report: {self.files_scanned} files scanned, "
            f"{self.violation_count} violations found"
        ]
        if self.has_violations:
            for file_path, file_violations in self.violations_by_file().items():
                lines.append(f"\n{file_path}:")
                for v in file_violations:
                    lines.append(f"  Line {v.line_number}: {v.pattern.name}")
                    lines.append(f"    Suggestion: {v.suggestion}")
        return "\n".join(lines)
