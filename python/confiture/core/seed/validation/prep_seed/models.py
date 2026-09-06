"""Data models for prep_seed validation.

Cycle 1 & 2: Core Models for tracking prep_seed pattern violations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PrepSeedPattern(Enum):
    """Patterns of prep_seed validation issues.

    These patterns represent issues specific to the prep_seed transformation
    pattern where UUID FKs in prep_seed schema transform to BIGINT FKs in
    final tables via resolution functions.
    """

    SCHEMA_DRIFT_IN_RESOLVER = "SCHEMA_DRIFT_IN_RESOLVER"
    """Resolution function references wrong schema (e.g., tenant vs catalog)."""

    MISSING_FK_TRANSFORMATION = "MISSING_FK_TRANSFORMATION"
    """Missing JOIN for FK transformation in resolution function."""

    MISSING_RESOLVER_FUNCTION = "MISSING_RESOLVER_FUNCTION"
    """prep_seed table has no corresponding resolution function."""

    MISSING_FK_MAPPING = "MISSING_FK_MAPPING"
    """prep_seed FK column has no corresponding column in final table."""

    PREP_SEED_TARGET_MISMATCH = "PREP_SEED_TARGET_MISMATCH"
    """Seed file targets wrong schema (not prep_seed)."""

    INVALID_FK_NAMING = "INVALID_FK_NAMING"
    """FK column in prep_seed doesn't use _id suffix."""

    INVALID_UUID_FORMAT = "INVALID_UUID_FORMAT"
    """Invalid UUID format in seed data."""

    UNION_TYPE_MISMATCH = "UNION_TYPE_MISMATCH"
    """UNION query has inconsistent column types across branches."""

    NULL_FK_AFTER_RESOLUTION = "NULL_FK_AFTER_RESOLUTION"
    """Resolution produced NULL foreign keys when non-NULL expected."""

    UNIQUE_CONSTRAINT_VIOLATION = "UNIQUE_CONSTRAINT_VIOLATION"
    """Duplicate identifiers found after resolution."""

    MISSING_SELF_REFERENCE_HANDLING = "MISSING_SELF_REFERENCE_HANDLING"
    """Self-referencing FK not handled with two-pass resolution."""

    UNION_INLINE_COMMENT = "UNION_INLINE_COMMENT"
    """Inline comment after UNION ALL breaks SQL concatenation."""

    UNION_UNCAST_NULL = "UNION_UNCAST_NULL"
    """Bare NULL without type cast in UNION query."""

    @property
    def description(self) -> str:
        """Get human-readable description of this pattern."""
        descriptions = {
            PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER: (
                "Resolution function references wrong schema (e.g., tenant.tb_x "
                "but table is in catalog.tb_x)"
            ),
            PrepSeedPattern.MISSING_FK_TRANSFORMATION: (
                "Resolution function missing JOIN for FK transformation"
            ),
            PrepSeedPattern.MISSING_RESOLVER_FUNCTION: (
                "prep_seed table has no corresponding resolution function"
            ),
            PrepSeedPattern.MISSING_FK_MAPPING: (
                "prep_seed FK column has no matching column in final table"
            ),
            PrepSeedPattern.PREP_SEED_TARGET_MISMATCH: (
                "Seed file INSERT targets wrong schema (not prep_seed)"
            ),
            PrepSeedPattern.INVALID_FK_NAMING: ("FK column in prep_seed missing _id suffix"),
            PrepSeedPattern.INVALID_UUID_FORMAT: ("Invalid UUID format in seed data"),
            PrepSeedPattern.UNION_TYPE_MISMATCH: (
                "UNION query has inconsistent column types (e.g., NULL vs NULL::timestamp)"
            ),
            PrepSeedPattern.NULL_FK_AFTER_RESOLUTION: (
                "NULL foreign keys in final table after resolution"
            ),
            PrepSeedPattern.UNIQUE_CONSTRAINT_VIOLATION: ("Duplicate identifiers after resolution"),
            PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING: (
                "Self-referencing FK not handled with two-pass resolution"
            ),
            PrepSeedPattern.UNION_INLINE_COMMENT: (
                "Inline comment after UNION ALL breaks SQL concatenation in seed files"
            ),
            PrepSeedPattern.UNION_UNCAST_NULL: (
                "Bare NULL value in UNION query without type cast (e.g., NULL::timestamp)"
            ),
        }
        return descriptions.get(self, "Prep-seed pattern violation")

    @property
    def fix_available(self) -> bool:
        """Check if automatic fix is available for this pattern."""
        fixable = {
            PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            PrepSeedPattern.MISSING_FK_TRANSFORMATION,
        }
        return self in fixable


class ViolationSeverity(Enum):
    """Severity levels for violations."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class PrepSeedViolation:
    """Represents a single prep_seed validation violation.

    Attributes:
        pattern: The type of prep_seed issue detected
        severity: Severity level (INFO, WARNING, ERROR, CRITICAL)
        message: Human-readable message describing the violation
        file_path: Path to the file containing the violation
        line_number: Line number where violation occurs
        impact: Optional description of impact if not fixed
        fix_available: Whether automatic fix is available
        suggestion: Optional suggestion for fixing the violation
    """

    pattern: PrepSeedPattern
    severity: ViolationSeverity
    message: str
    file_path: str
    line_number: int
    impact: str | None = None
    fix_available: bool = False
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "pattern": self.pattern.name,
            "severity": self.severity.name,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "impact": self.impact,
            "fix_available": self.fix_available,
            "suggestion": self.suggestion,
        }


@dataclass
class PrepSeedReport:
    """Report of prep_seed validation results.

    Attributes:
        violations: List of violations found
        scanned_files: List of files scanned
    """

    violations: list[PrepSeedViolation] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Check if any violations were found."""
        return len(self.violations) > 0

    @property
    def violation_count(self) -> int:
        """Get total number of violations."""
        return len(self.violations)

    def add_violation(self, violation: PrepSeedViolation) -> None:
        """Add a violation to the report."""
        self.violations.append(violation)

    def add_file_scanned(self, file_path: str) -> None:
        """Record that a file was scanned."""
        if file_path not in self.scanned_files:
            self.scanned_files.append(file_path)

    def violations_by_severity(
        self,
    ) -> dict[ViolationSeverity, list[PrepSeedViolation]]:
        """Group violations by severity level."""
        by_severity: dict[ViolationSeverity, list[PrepSeedViolation]] = defaultdict(list)
        for violation in self.violations:
            by_severity[violation.severity].append(violation)
        return dict(by_severity)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            "violations": [v.to_dict() for v in self.violations],
            "violation_count": self.violation_count,
            "files_scanned": len(self.scanned_files),
            "scanned_files": self.scanned_files,
            "has_violations": self.has_violations,
            "violations_by_severity": {
                k.name: [v.to_dict() for v in vs] for k, vs in self.violations_by_severity().items()
            },
        }
