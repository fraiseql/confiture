"""Linting models for schema validation.

This module provides data structures for schema linting including:
- Violation: A single schema quality issue
- LintSeverity: Severity level of violations
- LintConfig: Configuration for linting rules
- LintReport: Aggregated linting results
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LintSeverity(str, Enum):
    """Severity levels for linting violations.

    Attributes:
        ERROR: Blocking issue - must fix before migration
        WARNING: Should fix but optional
        INFO: Informational only
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Violation:
    """A single schema quality violation.

    Attributes:
        rule_name: Name of the rule that detected this violation
        severity: Severity level (ERROR, WARNING, INFO)
        message: Human-readable description of the issue
        location: Where the violation occurred (table name, column, etc.)
        suggested_fix: Optional suggestion on how to fix it
    """

    rule_name: str
    severity: LintSeverity
    message: str
    location: str
    suggested_fix: str | None = None

    def __str__(self) -> str:
        """Format violation for human consumption."""
        return f"[{self.severity.upper()}] {self.location}: {self.message}"

    def __repr__(self) -> str:
        """Return repr for debugging."""
        return (
            f"Violation(rule={self.rule_name}, severity={self.severity}, location={self.location})"
        )


@dataclass
class LintConfig:
    """Configuration for schema linting.

    Attributes:
        enabled: Whether linting is enabled
        rules: Dict mapping rule names to their configs
        fail_on_error: Exit with error code if violations found
        fail_on_warning: Exit with error code if warnings found (stricter)
        exclude_tables: List of table name patterns to exclude from linting
    """

    enabled: bool = True
    rules: dict[str, Any] = field(default_factory=dict)
    fail_on_error: bool = True
    fail_on_warning: bool = False
    exclude_tables: list[str] = field(default_factory=list)

    @classmethod
    def default(cls) -> "LintConfig":
        """Create LintConfig with sensible defaults for all rules.

        Returns:
            LintConfig with all 6 rules enabled with default settings

        Example:
            >>> config = LintConfig.default()
            >>> config.rules.keys()
            dict_keys(['naming_convention', 'primary_key', ...])
        """
        return cls(
            enabled=True,
            fail_on_error=True,
            fail_on_warning=False,
            rules={
                "naming_convention": {
                    "enabled": True,
                    "style": "snake_case",
                },
                "primary_key": {
                    "enabled": True,
                },
                "documentation": {
                    "enabled": True,
                },
                "multi_tenant": {
                    "enabled": True,
                    "identifier": "tenant_id",
                },
                "missing_index": {
                    "enabled": True,
                },
                "security": {
                    "enabled": True,
                },
            },
        )


@dataclass
class LintReport:
    """Results of a complete linting pass.

    Attributes:
        violations: List of all violations found
        schema_name: Name of schema that was linted
        tables_checked: Total number of tables checked
        columns_checked: Total number of columns checked
        errors_count: Number of ERROR level violations
        warnings_count: Number of WARNING level violations
        info_count: Number of INFO level violations
        execution_time_ms: Time taken to lint in milliseconds
    """

    violations: list[Violation]
    schema_name: str
    tables_checked: int
    columns_checked: int
    errors_count: int
    warnings_count: int
    info_count: int
    execution_time_ms: int

    @property
    def has_errors(self) -> bool:
        """Whether there are any ERROR level violations.

        Returns:
            True if errors_count > 0, False otherwise
        """
        return self.errors_count > 0

    @property
    def has_warnings(self) -> bool:
        """Whether there are any WARNING level violations.

        Returns:
            True if warnings_count > 0, False otherwise
        """
        return self.warnings_count > 0

    def violations_by_severity(self) -> dict[LintSeverity, list[Violation]]:
        """Group violations by their severity level.

        Returns:
            Dict mapping LintSeverity to list of violations at that level

        Example:
            >>> report.violations_by_severity()
            {
                <LintSeverity.ERROR: 'error'>: [Violation(...), ...],
                <LintSeverity.WARNING: 'warning'>: [...],
                <LintSeverity.INFO: 'info'>: [...],
            }
        """
        grouped: dict[LintSeverity, list[Violation]] = {}

        for severity in LintSeverity:
            grouped[severity] = [v for v in self.violations if v.severity == severity]

        return grouped

    def __str__(self) -> str:
        """Format report for human consumption.

        Returns:
            Multi-line string with summary of linting results
        """
        tables_with_violations = {v.location.split(".")[0] for v in self.violations}
        lines = [
            f"Schema: {self.schema_name}",
            f"Tables: {self.tables_checked} checked, {len(tables_with_violations)} with violations",
            f"Violations: {self.errors_count} errors, {self.warnings_count} warnings, {self.info_count} info",
            f"Time: {self.execution_time_ms}ms",
        ]
        return "\n".join(lines)
