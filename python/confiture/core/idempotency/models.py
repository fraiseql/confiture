"""Data models for idempotency validation.

This module defines the core data structures used for tracking and reporting
idempotency violations in SQL migrations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confiture.core.idempotency.python_migration_extractor import ExtractionWarning


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
    ALTER_TABLE_ADD_CONSTRAINT_CHECK = "ALTER_TABLE_ADD_CONSTRAINT_CHECK"
    ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY = "ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY"
    ALTER_TABLE_ADD_CONSTRAINT_UNIQUE = "ALTER_TABLE_ADD_CONSTRAINT_UNIQUE"
    ALTER_TABLE_RENAME_COLUMN = "ALTER_TABLE_RENAME_COLUMN"
    ALTER_TABLE_OWNER = "ALTER_TABLE_OWNER"
    ALTER_VIEW_OWNER = "ALTER_VIEW_OWNER"
    ALTER_MATVIEW_OWNER = "ALTER_MATVIEW_OWNER"
    DROP_TABLE = "DROP_TABLE"
    DROP_INDEX = "DROP_INDEX"
    DROP_FUNCTION = "DROP_FUNCTION"
    DROP_VIEW = "DROP_VIEW"
    DROP_TYPE = "DROP_TYPE"
    DROP_SCHEMA = "DROP_SCHEMA"
    DROP_SEQUENCE = "DROP_SEQUENCE"
    CREATE_OR_REPLACE_VIEW_SHAPE_RISK = "CREATE_OR_REPLACE_VIEW_SHAPE_RISK"
    CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK = "CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK"
    CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK = "CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK"

    @property
    def suggestion(self) -> str:
        """Get the suggestion for making this pattern idempotent."""
        suggestions = {
            IdempotencyPattern.CREATE_TABLE: "Use CREATE TABLE IF NOT EXISTS",
            IdempotencyPattern.CREATE_INDEX: "Use CREATE INDEX IF NOT EXISTS",
            IdempotencyPattern.CREATE_UNIQUE_INDEX: "Use CREATE UNIQUE INDEX IF NOT EXISTS",
            IdempotencyPattern.CREATE_FUNCTION: "Use CREATE OR REPLACE FUNCTION",
            IdempotencyPattern.CREATE_PROCEDURE: "Use CREATE OR REPLACE PROCEDURE",
            IdempotencyPattern.CREATE_VIEW: "Use DROP VIEW IF EXISTS CASCADE + CREATE VIEW",
            IdempotencyPattern.CREATE_TYPE: "Wrap in DO block with pg_type check",
            IdempotencyPattern.CREATE_EXTENSION: "Use CREATE EXTENSION IF NOT EXISTS",
            IdempotencyPattern.CREATE_SCHEMA: "Use CREATE SCHEMA IF NOT EXISTS",
            IdempotencyPattern.CREATE_SEQUENCE: "Use CREATE SEQUENCE IF NOT EXISTS",
            IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: (
                "Wrap in DO block with EXCEPTION handler for duplicate_column"
            ),
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK: (
                "Use DROP CONSTRAINT IF EXISTS <name> before ADD, or wrap in a "
                "DO block guarded by a pg_constraint existence check"
            ),
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY: (
                "Use DROP CONSTRAINT IF EXISTS <name> before ADD, or guard with "
                "a pg_constraint check on contype = 'p'"
            ),
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE: (
                "Use DROP CONSTRAINT IF EXISTS <name> before ADD, or wrap in a "
                "DO block guarded by a pg_constraint existence check"
            ),
            IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN: (
                "Wrap in DO block guarded by information_schema.columns lookups "
                "for both the source and destination column names"
            ),
            IdempotencyPattern.ALTER_TABLE_OWNER: (
                "Wrap in DO block with a pg_class existence check before "
                "issuing OWNER TO (the prior CREATE may have been undone)"
            ),
            IdempotencyPattern.ALTER_VIEW_OWNER: (
                "Wrap in DO block with a pg_class existence check before "
                "issuing OWNER TO on the view"
            ),
            IdempotencyPattern.ALTER_MATVIEW_OWNER: (
                "Wrap in DO block with a pg_matviews existence check before "
                "issuing OWNER TO on the materialized view"
            ),
            IdempotencyPattern.DROP_TABLE: "Use DROP TABLE IF EXISTS",
            IdempotencyPattern.DROP_INDEX: "Use DROP INDEX IF EXISTS",
            IdempotencyPattern.DROP_FUNCTION: "Use DROP FUNCTION IF EXISTS",
            IdempotencyPattern.DROP_VIEW: "Use DROP VIEW IF EXISTS",
            IdempotencyPattern.DROP_TYPE: "Use DROP TYPE IF EXISTS",
            IdempotencyPattern.DROP_SCHEMA: "Use DROP SCHEMA IF EXISTS",
            IdempotencyPattern.DROP_SEQUENCE: "Use DROP SEQUENCE IF EXISTS",
            IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: (
                "CREATE OR REPLACE VIEW only succeeds when the column set is "
                "unchanged. For shape changes, use DROP VIEW IF EXISTS + "
                "CREATE VIEW. If other views or functions depend on this "
                "view's columns, they will also break on shape change."
            ),
            IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK: (
                "CREATE OR REPLACE FUNCTION fails when an input parameter is "
                "renamed. For signature changes, use DROP FUNCTION IF EXISTS "
                "+ CREATE FUNCTION. Note: DROP+CREATE drops privileges and "
                "dependencies, unlike a true OR REPLACE."
            ),
            IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK: (
                "CREATE OR REPLACE PROCEDURE fails on parameter renames. For "
                "signature changes, use DROP PROCEDURE IF EXISTS + CREATE "
                "PROCEDURE."
            ),
        }
        return suggestions.get(self, "Make statement idempotent")

    @property
    def fix_available(self) -> bool:
        """Check if automatic fix is available for this pattern.

        Reads from :data:`confiture.core.idempotency.fixer.FIXABLE_PATTERNS`,
        which is derived from the fixer's dispatch table — the single
        source of truth. Lazy import avoids a models→fixer cycle at
        package-load time.
        """
        # Lazy import to break models→fixer→models cycle.
        from confiture.core.idempotency.fixer import FIXABLE_PATTERNS

        return self in FIXABLE_PATTERNS


@dataclass
class IdempotencyViolation:
    """Represents a single idempotency violation in a SQL migration.

    Attributes:
        pattern: The type of non-idempotent pattern detected
        sql_snippet: The SQL code that triggered the violation
        line_number: Line number in the file where violation occurs
        file_path: Path to the migration file
        suggestion: Filled-in fix template (set by the detector) or the
            generic pattern suggestion when no captures were available.
            Pass ``None`` to fall back to :attr:`IdempotencyPattern.suggestion`.
    """

    pattern: IdempotencyPattern
    sql_snippet: str
    line_number: int
    file_path: str
    source_line: int | None = None
    severity: str = "error"
    suggestion: str | None = None

    def __post_init__(self) -> None:
        if self.suggestion is None:
            self.suggestion = self.pattern.suggestion

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
        """Convert to dictionary for serialization.

        ``source_line`` is omitted when ``None`` so .sql-origin output is
        byte-identical to releases before 0.12.1.
        """
        payload: dict[str, Any] = {
            "pattern": self.pattern.name,
            "sql_snippet": self.sql_snippet,
            "line_number": self.line_number,
            "file_path": self.file_path,
            "suggestion": self.suggestion,
            "fix_available": self.fix_available,
            "severity": self.severity,
        }
        if self.source_line is not None:
            payload["source_line"] = self.source_line
        return payload


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
    warnings: list[ExtractionWarning] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Check if any violations were found."""
        return len(self.violations) > 0

    @property
    def has_blocking_violations(self) -> bool:
        """Check if any error-severity violations exist.

        ``info``-severity findings (e.g. ``CREATE OR REPLACE VIEW`` heuristic
        notes) don't fail the gate by default; this property is what the
        CLI consults for its exit-code branch.
        """
        return any(v.severity == "error" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        """Check if any extractor warnings were collected."""
        return len(self.warnings) > 0

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

        ``warnings`` and ``has_warnings`` were added in 0.12.1; existing keys
        keep their names and types (additive-only contract).
        """
        return {
            "violations": [v.to_dict() for v in self.violations],
            "violation_count": self.violation_count,
            "files_scanned": self.files_scanned,
            "scanned_files": self.scanned_files,
            "has_violations": self.has_violations,
            "has_blocking_violations": self.has_blocking_violations,
            "warnings": [
                {
                    "kind": w.kind.value,
                    "source_file": str(w.source_file),
                    "source_line": w.source_line,
                    "message": w.message,
                }
                for w in self.warnings
            ],
            "has_warnings": self.has_warnings,
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
