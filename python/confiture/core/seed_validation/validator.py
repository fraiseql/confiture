"""Seed data validator for SQL seed files.

This module provides the SeedValidator class which scans seed SQL files
and detects data consistency issues.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.seed_validation.models import (
    SeedValidationPattern,
    SeedValidationReport,
    SeedViolation,
)
from confiture.core.seed_validation.patterns import (
    detect_seed_issues,
)


class SeedValidator:
    """Validates seed files for data consistency issues.

    Scans seed SQL files for patterns that indicate data inconsistencies,
    such as double semicolons or missing ON CONFLICT clauses.

    Example:
        >>> validator = SeedValidator()
        >>> report = validator.validate_file(Path("db/seeds/001_users.sql"))
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} issues")
        ...     for v in report.violations:
        ...         print(f"  {v.file_path}:{v.line_number} - {v.suggestion}")
    """

    def __init__(
        self,
        ignore_patterns: list[SeedValidationPattern] | None = None,
    ):
        """Initialize the validator.

        Args:
            ignore_patterns: Patterns to ignore when validating.
                Use this to suppress warnings for patterns you've intentionally
                chosen not to fix.
        """
        self.ignore_patterns = set(ignore_patterns) if ignore_patterns else set()

    def validate_sql(
        self, sql: str, file_path: str = "<string>"
    ) -> SeedValidationReport:
        """Validate SQL content for seed data issues.

        Args:
            sql: The SQL content to validate
            file_path: Path to associate with violations (for reporting)

        Returns:
            SeedValidationReport with any violations found

        Example:
            >>> validator = SeedValidator()
            >>> report = validator.validate_sql(
            ...     "INSERT INTO users VALUES (1);;",
            ...     file_path="bad.sql"
            ... )
            >>> report.has_violations
            True
        """
        report = SeedValidationReport()
        report.add_file_scanned(file_path)

        # Detect issues
        matches = detect_seed_issues(sql)

        # Convert matches to violations, filtering ignored patterns
        for match in matches:
            if match.pattern in self.ignore_patterns:
                continue

            violation = SeedViolation(
                pattern=match.pattern,
                sql_snippet=match.sql_snippet,
                line_number=match.line_number,
                file_path=file_path,
            )
            report.add_violation(violation)

        return report

    def validate_file(self, file_path: Path) -> SeedValidationReport:
        """Validate a single seed file.

        Args:
            file_path: Path to the seed file to validate

        Returns:
            SeedValidationReport with any violations found

        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Seed file not found: {file_path}")

        sql = file_path.read_text(encoding="utf-8")
        return self.validate_sql(sql, file_path=str(file_path))

    def validate_directory(
        self,
        directory: Path,
        pattern: str = "*.sql",
        recursive: bool = False,
    ) -> SeedValidationReport:
        """Validate all seed files in a directory.

        Args:
            directory: Directory containing seed files
            pattern: Glob pattern to match files (default: "*.sql")
            recursive: If True, scan subdirectories recursively

        Returns:
            SeedValidationReport combining violations from all files
        """
        report = SeedValidationReport()

        # Find all matching files
        glob_pattern = f"**/{pattern}" if recursive else pattern
        files = sorted(directory.glob(glob_pattern))

        for file_path in files:
            if file_path.is_file():
                file_report = self.validate_file(file_path)
                for violation in file_report.violations:
                    report.add_violation(violation)
                for scanned_file in file_report.scanned_files:
                    report.add_file_scanned(scanned_file)

        return report
