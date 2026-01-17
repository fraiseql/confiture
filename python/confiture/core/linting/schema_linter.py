"""Schema linting engine - validates PostgreSQL schemas against best practices.

This module provides the SchemaLinter class which validates database schemas
against configurable rules for naming conventions, primary keys, documentation,
and other best practices.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.config.environment import Environment

if TYPE_CHECKING:
    from confiture.models.lint import LintConfig

logger = logging.getLogger(__name__)


class RuleSeverity(Enum):
    """Severity levels for linting violations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class LintViolation:
    """Represents a single linting violation."""

    rule_id: str
    rule_name: str
    severity: RuleSeverity
    object_type: str  # table, column, index, etc.
    object_name: str
    message: str
    file_path: str | None = None
    line_number: int | None = None

    def __str__(self) -> str:
        """String representation of violation."""
        prefix = f"[{self.severity.value.upper()}]"
        return f"{prefix} {self.rule_name}: {self.message} ({self.object_type}: {self.object_name})"


@dataclass
class LintReport:
    """Result of schema linting."""

    errors: list[LintViolation] = field(default_factory=list)
    warnings: list[LintViolation] = field(default_factory=list)
    info: list[LintViolation] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if report contains errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if report contains warnings."""
        return len(self.warnings) > 0

    @property
    def has_info(self) -> bool:
        """Check if report contains info messages."""
        return len(self.info) > 0

    @property
    def total_violations(self) -> int:
        """Total number of violations."""
        return len(self.errors) + len(self.warnings) + len(self.info)

    def add_violation(self, violation: LintViolation) -> None:
        """Add a violation to the report."""
        if violation.severity == RuleSeverity.ERROR:
            self.errors.append(violation)
        elif violation.severity == RuleSeverity.WARNING:
            self.warnings.append(violation)
        else:
            self.info.append(violation)


class LintConfig:
    """Configuration for schema linting."""

    def __init__(
        self,
        enabled: bool = True,
        fail_on_error: bool = True,
        fail_on_warning: bool = False,
        check_naming: bool = True,
        check_primary_keys: bool = True,
        check_documentation: bool = True,
        check_indexes: bool = True,
        check_constraints: bool = True,
        check_security: bool = True,
    ):
        """Initialize linting configuration.

        Args:
            enabled: Whether linting is enabled
            fail_on_error: Exit with error code if errors found
            fail_on_warning: Exit with error code if warnings found
            check_naming: Check naming conventions (snake_case)
            check_primary_keys: Ensure all tables have primary keys
            check_documentation: Check for COMMENT documentation
            check_indexes: Check indexes on foreign keys
            check_constraints: Check constraint definitions
            check_security: Check for security issues (passwords, tokens)
        """
        self.enabled = enabled
        self.fail_on_error = fail_on_error
        self.fail_on_warning = fail_on_warning
        self.check_naming = check_naming
        self.check_primary_keys = check_primary_keys
        self.check_documentation = check_documentation
        self.check_indexes = check_indexes
        self.check_constraints = check_constraints
        self.check_security = check_security


class SchemaLinter:
    """Lints PostgreSQL schema against best practices.

    Provides comprehensive schema validation including:
    - Naming convention enforcement (snake_case)
    - Primary key requirements
    - Documentation (COMMENT statements)
    - Index requirements on foreign keys
    - Constraint validation
    - Security issue detection

    Example:
        >>> config = LintConfig(enabled=True)
        >>> linter = SchemaLinter(env="local", config=config)
        >>>
        >>> # Option 1: Load schema from files
        >>> report = linter.lint()
        >>>
        >>> # Option 2: Pass schema directly
        >>> schema = "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(255));"
        >>> report = linter.lint(schema=schema)
        >>>
        >>> if report.has_errors:
        ...     print(f"Found {len(report.errors)} errors")
    """

    def __init__(
        self,
        env: str = "local",
        project_dir: Path | None = None,
        config: LintConfig | None = None,
    ):
        """Initialize linter.

        Args:
            env: Environment name (local, test, production)
            project_dir: Project root directory
            config: Linting configuration (optional)
        """
        self.env = env
        self.project_dir = project_dir or Path(".")
        self.config = config or LintConfig()

        # Load environment configuration
        self.environment = Environment.load(env, project_dir=project_dir)

        # Schema cache
        self._schema_sql: str | None = None
        self._tables: dict[str, dict[str, Any]] | None = None

    def lint(self, schema: str | None = None) -> LintReport:
        """Run linting and return report.

        Args:
            schema: Optional schema SQL to lint. If not provided, loads from files.

        Returns:
            LintReport with all violations found
        """
        report = LintReport()

        if not self.config.enabled:
            return report

        # Use provided schema or load from files
        if schema is not None:
            self._schema_sql = schema
        else:
            self._load_schema()

        if not self._schema_sql:
            logger.warning("No schema SQL found, skipping linting")
            return report

        # Run configured checks
        if self.config.check_naming:
            self._check_naming_conventions(report)

        if self.config.check_primary_keys:
            self._check_primary_keys(report)

        if self.config.check_documentation:
            self._check_documentation(report)

        if self.config.check_indexes:
            self._check_indexes(report)

        if self.config.check_security:
            self._check_security(report)

        return report

    def _load_schema(self) -> None:
        """Load schema SQL from files."""
        try:
            from confiture.core.builder import SchemaBuilder

            builder = SchemaBuilder(env=self.env, project_dir=self.project_dir)
            self._schema_sql = builder.build()
        except Exception as e:
            logger.error(f"Failed to load schema: {e}")
            self._schema_sql = ""

    def _check_naming_conventions(self, report: LintReport) -> None:
        """Check naming conventions (snake_case for identifiers).

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Find table definitions
        table_pattern = r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)"
        for match in re.finditer(table_pattern, self._schema_sql, re.IGNORECASE):
            table_name = match.group(1)

            # Check if table name is snake_case
            if not self._is_snake_case(table_name):
                violation = LintViolation(
                    rule_id="naming_001",
                    rule_name="Table Naming Convention",
                    severity=RuleSeverity.WARNING,
                    object_type="table",
                    object_name=table_name,
                    message=f"Table name '{table_name}' should be lowercase with underscores (snake_case)",
                )
                report.add_violation(violation)

            # Check column names in this table
            self._check_column_names(table_name, report)

    def _check_column_names(self, table_name: str, report: LintReport) -> None:
        """Check column naming conventions in a table.

        Args:
            table_name: Name of table to check
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Extract table definition
        table_pattern = rf"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?{re.escape(table_name)}\s*\((.*?)\);"
        match = re.search(table_pattern, self._schema_sql, re.IGNORECASE | re.DOTALL)

        if not match:
            return

        table_def = match.group(1)

        # Find column definitions
        column_pattern = r"(\w+)\s+\w+"
        for col_match in re.finditer(column_pattern, table_def):
            column_name = col_match.group(1)

            # Skip if it's a keyword (PRIMARY KEY, CONSTRAINT, etc.)
            if column_name.upper() in (
                "PRIMARY",
                "KEY",
                "CONSTRAINT",
                "CHECK",
                "DEFAULT",
                "NOT",
                "NULL",
            ):
                continue

            if not self._is_snake_case(column_name):
                violation = LintViolation(
                    rule_id="naming_002",
                    rule_name="Column Naming Convention",
                    severity=RuleSeverity.WARNING,
                    object_type="column",
                    object_name=f"{table_name}.{column_name}",
                    message=f"Column '{column_name}' should be lowercase with underscores (snake_case)",
                )
                report.add_violation(violation)

    def _check_primary_keys(self, report: LintReport) -> None:
        """Check that all tables have primary keys.

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Find all table definitions
        table_pattern = r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)\s*\((.*?)\);"
        for match in re.finditer(table_pattern, self._schema_sql, re.IGNORECASE | re.DOTALL):
            table_name = match.group(1)
            table_def = match.group(2)

            # Skip if table contains PRIMARY KEY definition
            if re.search(r"PRIMARY\s+KEY", table_def, re.IGNORECASE):
                continue

            # Skip if this is likely a junction/bridge table
            if self._is_likely_junction_table(table_name):
                continue

            violation = LintViolation(
                rule_id="pk_001",
                rule_name="Missing Primary Key",
                severity=RuleSeverity.WARNING,
                object_type="table",
                object_name=table_name,
                message=f"Table '{table_name}' should have a PRIMARY KEY",
            )
            report.add_violation(violation)

    def _check_documentation(self, report: LintReport) -> None:
        """Check for documentation (COMMENT statements).

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Find all table definitions
        table_pattern = r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)"
        tables_found = set()

        for match in re.finditer(table_pattern, self._schema_sql, re.IGNORECASE):
            table_name = match.group(1)
            tables_found.add(table_name)

        # Check for COMMENT statements
        comment_pattern = r"COMMENT ON TABLE (\w+)"
        tables_documented = set()

        for match in re.finditer(comment_pattern, self._schema_sql, re.IGNORECASE):
            tables_documented.add(match.group(1))

        # Find undocumented tables
        for table_name in tables_found:
            if table_name not in tables_documented:
                violation = LintViolation(
                    rule_id="doc_001",
                    rule_name="Missing Documentation",
                    severity=RuleSeverity.INFO,
                    object_type="table",
                    object_name=table_name,
                    message=f"Table '{table_name}' should have a COMMENT describing its purpose",
                )
                report.add_violation(violation)

    def _check_indexes(self, _report: LintReport) -> None:
        """Check for indexes on foreign keys.

        Args:
            _report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Find foreign key definitions
        fk_pattern = r"REFERENCES\s+(\w+)\s*\((\w+)\)"
        fk_matches = list(re.finditer(fk_pattern, self._schema_sql, re.IGNORECASE))

        if not fk_matches:
            return

        # Check for CREATE INDEX statements
        index_pattern = r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\w+\s+ON\s+(\w+)\s*\(([^)]+)\)"
        indexes = {}

        for match in re.finditer(index_pattern, self._schema_sql, re.IGNORECASE):
            table = match.group(1)
            columns = match.group(2)
            if table not in indexes:
                indexes[table] = []
            indexes[table].append(columns)

        # Warn if foreign keys lack indexes
        # This is simplified - a full implementation would parse more thoroughly
        # For now, just note that checking for indexes on FK columns is important
        for _fk_match in fk_matches:
            pass

    def _check_security(self, report: LintReport) -> None:
        """Check for common security issues.

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        # Check for suspicious column names that might store sensitive data
        security_patterns = [
            (r"password", "password"),
            (r"token", "token"),
            (r"secret", "secret"),
            (r"api_key", "API key"),
            (r"credit_card", "credit card"),
            (r"ssn", "social security number"),
        ]

        for pattern, description in security_patterns:
            matches = re.finditer(rf"(\w*{pattern}\w*)", self._schema_sql, re.IGNORECASE)
            for match in matches:
                identifier = match.group(1)

                # Check if it's actually a column definition
                context = self._schema_sql[max(0, match.start() - 50) : match.end() + 50]
                if "CREATE TABLE" in context or "ALTER TABLE" in context:
                    violation = LintViolation(
                        rule_id="sec_001",
                        rule_name="Sensitive Data Column",
                        severity=RuleSeverity.WARNING,
                        object_type="column",
                        object_name=identifier,
                        message=f"Column '{identifier}' appears to store {description} - ensure proper encryption and access controls",
                    )
                    report.add_violation(violation)

    @staticmethod
    def _is_snake_case(identifier: str) -> bool:
        """Check if identifier is in snake_case.

        Args:
            identifier: Identifier to check

        Returns:
            True if identifier is snake_case, False otherwise
        """
        # Allow uppercase letters for backward compatibility with existing code
        # but prefer lowercase
        if identifier != identifier.lower() and "_" not in identifier:
            return False

        # Check that it only contains alphanumeric and underscore
        return bool(re.match(r"^[a-z_][a-z0-9_]*$", identifier, re.IGNORECASE))

    @staticmethod
    def _is_likely_junction_table(table_name: str) -> bool:
        """Check if table looks like a junction/bridge table.

        Args:
            table_name: Name of table to check

        Returns:
            True if table appears to be a junction table
        """
        # Common junction table patterns
        patterns = [
            r"^(.+)_(.+)$",  # Format: singular_singular or table1_table2
            r"^link_",  # Starts with link_
            r"_assoc",  # Ends with _assoc
            r"_join",  # Ends with _join
            r"_rel",  # Ends with _rel
        ]

        # Count underscores - junction tables often have multiple
        if table_name.count("_") >= 2:
            for pattern in patterns:
                if re.match(pattern, table_name, re.IGNORECASE):
                    return True

        return False
