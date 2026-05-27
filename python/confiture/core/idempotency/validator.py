"""Idempotency validator for SQL migrations.

This module provides the IdempotencyValidator class which scans SQL files
and strings for non-idempotent patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from confiture.core.idempotency.models import (
    IdempotencyPattern,
    IdempotencyReport,
    IdempotencyViolation,
)
from confiture.core.idempotency.patterns import (
    detect_non_idempotent_patterns,
)

if TYPE_CHECKING:
    from confiture.core.idempotency.python_migration_extractor import ExtractedSQL


@dataclass(frozen=True)
class _SnippetOrigin:
    """Where a ``.py``-extracted snippet lives in the combined SQL.

    The combined SQL is the concatenation of every ``self.execute(...)``
    snippet extracted from a single migration file, joined with ``";\\n"``.
    Each origin records the line range the snippet occupies in the
    combined string plus the ``self.execute()`` call's source line in
    the ``.py`` file, so violations can be back-mapped to the user-visible
    call site.
    """

    combined_start_line: int
    combined_end_line: int
    source_line: int


def _combine_python_snippets(
    snippets: list[ExtractedSQL],
) -> tuple[str, list[_SnippetOrigin]]:
    """Concatenate Python-extracted snippets into one parseable SQL string.

    Each snippet is appended with a terminating ``;`` (added when absent
    so the next statement parses cleanly) and joined with newlines. The
    returned origins let :func:`_map_combined_line_to_source` translate
    a violation in the combined SQL back to its ``self.execute()`` call.

    A single :func:`detect_non_idempotent_patterns` pass over the
    combined string is what makes cross-snippet DROP+CREATE pairs
    recognizable — previously each snippet went through the detector
    independently, so a DROP in one call and a CREATE in the next looked
    like an unpaired violation.
    """
    parts: list[str] = []
    origins: list[_SnippetOrigin] = []
    cursor_line = 1
    for snippet in snippets:
        sql = snippet.sql.rstrip()
        if not sql.endswith(";"):
            sql = sql + ";"
        line_count = sql.count("\n") + 1
        origins.append(
            _SnippetOrigin(
                combined_start_line=cursor_line,
                combined_end_line=cursor_line + line_count - 1,
                source_line=snippet.source_line,
            )
        )
        parts.append(sql)
        # ``"\n".join`` doesn't add an extra blank line between parts —
        # snippet N+1's first line is the line right after snippet N's
        # last, so advancing the cursor by ``line_count`` lands us on
        # the next snippet's starting line.
        cursor_line += line_count
    return "\n".join(parts), origins


def _map_combined_line_to_source(
    combined_line: int, origins: list[_SnippetOrigin]
) -> _SnippetOrigin | None:
    """Find the snippet origin that owns ``combined_line``, or None."""
    for origin in origins:
        if origin.combined_start_line <= combined_line <= origin.combined_end_line:
            return origin
    return None


class IdempotencyValidator:
    """Validates SQL migrations for idempotency issues.

    Scans SQL files and strings for patterns that are not idempotent,
    such as CREATE TABLE without IF NOT EXISTS.

    Example:
        >>> validator = IdempotencyValidator()
        >>> report = validator.validate_file(Path("db/migrations/001_init.up.sql"))
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} idempotency issues")
        ...     for v in report.violations:
        ...         print(f"  {v.file_path}:{v.line_number} - {v.suggestion}")
    """

    def __init__(
        self,
        ignore_patterns: list[IdempotencyPattern] | None = None,
        severity: str = "warning",
    ):
        """Initialize the validator.

        Args:
            ignore_patterns: Patterns to ignore when validating.
                Use this to suppress warnings for patterns you've intentionally
                made non-idempotent.
            severity: Default severity level for violations.
                Options: "error", "warning", "info"
        """
        self.ignore_patterns = set(ignore_patterns) if ignore_patterns else set()
        self.severity = severity

    def validate_sql(self, sql: str, file_path: str = "<string>") -> IdempotencyReport:
        """Validate SQL content for idempotency issues.

        Args:
            sql: The SQL content to validate
            file_path: Path to associate with violations (for reporting)

        Returns:
            IdempotencyReport with any violations found

        Example:
            >>> validator = IdempotencyValidator()
            >>> report = validator.validate_sql(
            ...     "CREATE TABLE users (id INT);",
            ...     file_path="test.sql"
            ... )
            >>> report.has_violations
            True
        """
        report = IdempotencyReport()
        report.add_file_scanned(file_path)

        # Pre-process SQL to handle comments and strings
        processed_sql = self._preprocess_sql(sql)

        # Detect non-idempotent patterns
        matches = detect_non_idempotent_patterns(processed_sql)

        # Convert matches to violations, filtering ignored patterns
        for match in matches:
            if match.pattern in self.ignore_patterns:
                continue

            # Map line numbers from processed SQL back to original
            # (for now they're the same since we preserve structure)
            original_line = self._map_line_number(sql, processed_sql, match.line_number)

            violation = IdempotencyViolation(
                pattern=match.pattern,
                sql_snippet=match.sql_snippet,
                line_number=original_line,
                file_path=file_path,
                severity=match.severity,
                suggestion=match.suggestion,
            )
            report.add_violation(violation)

        return report

    def validate_file(self, file_path: Path) -> IdempotencyReport:
        """Validate a SQL file for idempotency issues.

        Args:
            file_path: Path to the SQL file to validate

        Returns:
            IdempotencyReport with any violations found

        Raises:
            FileNotFoundError: If the file doesn't exist
            PermissionError: If the file can't be read

        Example:
            >>> validator = IdempotencyValidator()
            >>> report = validator.validate_file(Path("migrations/001_init.up.sql"))
        """
        sql = file_path.read_text(encoding="utf-8")
        return self.validate_sql(sql, file_path=str(file_path))

    def validate_directory(
        self,
        directory: Path,
        pattern: str = "*.sql",
        recursive: bool = False,
        include_python: bool = True,
    ) -> IdempotencyReport:
        """Validate all SQL files in a directory.

        Args:
            directory: Directory to scan for SQL files
            pattern: Glob pattern for matching files (default: ``"*.sql"``)
            recursive: If True, scan subdirectories recursively
            include_python: When True (default), also scan ``*.py`` Confiture
                migrations in the directory using the AST extractor. Set to
                False to preserve the pre-0.13.0 SQL-only behavior. Added in
                0.13.0.

        Returns:
            IdempotencyReport with violations from all files

        Example:
            >>> validator = IdempotencyValidator()
            >>> report = validator.validate_directory(
            ...     Path("db/migrations"),
            ...     pattern="*.up.sql"
            ... )
        """
        from confiture.core.idempotency.python_migration_extractor import (
            extract_sql_from_python_migration,
            is_migration_file,
        )

        report = IdempotencyReport()

        # Find matching SQL files
        files = list(directory.rglob(pattern)) if recursive else list(directory.glob(pattern))
        files.sort()

        for file_path in files:
            if not file_path.is_file():
                continue

            file_report = self.validate_file(file_path)
            for scanned in file_report.scanned_files:
                report.add_file_scanned(scanned)
            for violation in file_report.violations:
                report.add_violation(violation)

        if include_python:
            py_iter = directory.rglob("*.py") if recursive else directory.glob("*.py")
            py_files = sorted(p for p in py_iter if is_migration_file(p))
            for py_path in py_files:
                extraction = extract_sql_from_python_migration(py_path)
                report.add_file_scanned(str(py_path))
                report.warnings.extend(extraction.warnings)
                if not extraction.snippets:
                    continue
                combined_sql, origins = _combine_python_snippets(extraction.snippets)
                combined_report = self.validate_sql(combined_sql, file_path=str(py_path))
                for violation in combined_report.violations:
                    origin = _map_combined_line_to_source(violation.line_number, origins)
                    if origin is not None:
                        # Preserve the pre-0.14.0 contract: ``line_number``
                        # is snippet-local (so users can see "line 1 of
                        # the snippet"); ``source_line`` is the .py file
                        # line of the originating ``self.execute()`` call.
                        violation.line_number = (
                            violation.line_number - origin.combined_start_line + 1
                        )
                        violation.source_line = origin.source_line
                    report.add_violation(violation)

        return report

    def _preprocess_sql(self, sql: str) -> str:
        """Preprocess SQL to handle comments and string literals.

        Removes or masks content that shouldn't be scanned for patterns:
        - Single-line comments (-- ...)
        - Multi-line comments (/* ... */)
        - String literals that might contain SQL-like text

        Args:
            sql: Raw SQL content

        Returns:
            Preprocessed SQL with comments and problematic strings handled

        Note:
            We preserve line structure so line numbers remain accurate.
        """
        # Remove single-line comments but preserve line structure
        # Replace comment content with spaces to maintain positions
        result = re.sub(
            r"--[^\n]*",
            lambda m: " " * len(m.group()),
            sql,
        )

        # Remove multi-line comments, preserving newlines
        def replace_multiline_comment(match: re.Match[str]) -> str:
            content = match.group()
            # Count newlines and preserve them
            newlines = content.count("\n")
            return "\n" * newlines

        result = re.sub(
            r"/\*.*?\*/",
            replace_multiline_comment,
            result,
            flags=re.DOTALL,
        )

        # Handle dollar-quoted strings (PostgreSQL function bodies)
        # These might contain SQL-like text that shouldn't trigger detection
        # We preserve the CREATE OR REPLACE FUNCTION header but mask the body
        def mask_dollar_quoted(match: re.Match[str]) -> str:
            content = match.group()
            # Preserve newlines
            newlines = content.count("\n")
            # Keep the outer structure but mask inner content
            return "$MASKED$" + "\n" * newlines + "$MASKED$"

        # Match $tag$...$tag$ but be careful not to break pattern detection
        # Only mask if this looks like a function body (has SQL keywords inside)
        result = re.sub(
            r"\$\w*\$.*?\$\w*\$",
            mask_dollar_quoted,
            result,
            flags=re.DOTALL,
        )

        return result

    def _map_line_number(
        self,
        _original_sql: str,
        _processed_sql: str,
        processed_line: int,
    ) -> int:
        """Map a line number from processed SQL back to original.

        Since we preserve line structure during preprocessing, the line
        numbers should be the same. This method exists for future cases
        where that might change.

        Args:
            _original_sql: The original SQL content (unused, for future use)
            _processed_sql: The preprocessed SQL content (unused, for future use)
            processed_line: Line number in processed SQL

        Returns:
            Corresponding line number in original SQL
        """
        # Currently line numbers are preserved
        return processed_line
