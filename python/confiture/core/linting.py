"""Schema linting engine for validation of database schemas.

This module provides a pluggable schema linting system with 6 built-in rules:
- NamingConventionRule: Enforce snake_case naming
- PrimaryKeyRule: Require PRIMARY KEY on all tables
- DocumentationRule: Mandate COMMENT on tables
- MultiTenantRule: Enforce tenant_id in multi-tenant tables
- MissingIndexRule: Detect unindexed foreign keys
- SecurityRule: Flag password/secret columns
"""

import re
import time
from abc import ABC, abstractmethod
from typing import Any

from confiture.core.builder import SchemaBuilder
from confiture.core.differ import SchemaDiffer
from confiture.models.lint import (
    LintConfig,
    LintReport,
    LintSeverity,
    Violation,
)


class LintRule(ABC):
    """Abstract base class for schema linting rules.

    Subclasses must implement the lint() method to analyze a list of tables
    and return violations found.

    Attributes:
        name: Unique identifier for this rule
        description: Human-readable description of what this rule checks
        enabled_by_default: Whether this rule should be enabled by default
    """

    name: str
    description: str
    enabled_by_default: bool = True

    @abstractmethod
    def lint(
        self,
        tables: list[Any],
        config: dict[str, Any],
    ) -> list[Violation]:
        """Analyze tables and return violations found.

        Args:
            tables: List of Table objects from SchemaDiffer
            config: Rule-specific configuration dict

        Returns:
            List of Violation objects found by this rule
        """
        ...

    def _create_violation(
        self,
        severity: LintSeverity,
        message: str,
        location: str,
        suggested_fix: str | None = None,
    ) -> Violation:
        """Create a Violation with this rule's name.

        Args:
            severity: Severity level of the violation
            message: Human-readable description
            location: Where violation occurred (table, column, etc.)
            suggested_fix: Optional fix suggestion

        Returns:
            Violation instance
        """
        return Violation(
            rule_name=self.name,
            severity=severity,
            message=message,
            location=location,
            suggested_fix=suggested_fix,
        )


class NamingConventionRule(LintRule):
    """Enforce consistent naming conventions (snake_case by default)."""

    name = "NamingConventionRule"
    description = "Enforces snake_case naming for tables and columns"

    def lint(
        self,
        tables: list[Any],
        config: dict[str, Any],
    ) -> list[Violation]:
        """Check that tables and columns use consistent naming."""
        violations = []
        style = config.get("style", "snake_case")

        for table in tables:
            # Check table name
            if not self._is_valid_name(table.name, style):
                violations.append(
                    self._create_violation(
                        severity=LintSeverity.ERROR,
                        message=f"Table '{table.name}' should use {style}",
                        location=f"Table: {table.name}",
                        suggested_fix=self._suggest_name(table.name, style),
                    )
                )

            # Check column names
            for column in table.columns:
                if not self._is_valid_name(column.name, style):
                    violations.append(
                        self._create_violation(
                            severity=LintSeverity.ERROR,
                            message=(
                                f"Column '{column.name}' should use {style}"
                            ),
                            location=f"{table.name}.{column.name}",
                            suggested_fix=self._suggest_name(
                                column.name, style
                            ),
                        )
                    )

        return violations

    def _is_valid_name(self, name: str, style: str) -> bool:
        """Check if name matches the expected style."""
        if style == "snake_case":
            # Valid: [a-z0-9_], starting with letter
            return bool(re.match(r"^[a-z][a-z0-9_]*$", name))
        return True

    def _suggest_name(self, name: str, style: str) -> str:
        """Suggest corrected name in the given style."""
        if style == "snake_case":
            # Convert CamelCase/PascalCase to snake_case
            s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
            return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
        return name


class PrimaryKeyRule(LintRule):
    """Ensure all tables have a primary key."""

    name = "PrimaryKeyRule"
    description = "Ensures all tables have a PRIMARY KEY"

    def lint(
        self,
        tables: list[Any],
        _config: dict[str, Any],
    ) -> list[Violation]:
        """Check that all tables have a PRIMARY KEY."""
        violations = []

        for table in tables:
            # Skip system tables
            if table.name.startswith("pg_"):
                continue

            # Check if table has primary key
            has_pk = any(
                getattr(c, "is_primary_key", False) for c in table.columns
            )

            if not has_pk:
                violations.append(
                    self._create_violation(
                        severity=LintSeverity.ERROR,
                        message=f"Table '{table.name}' missing PRIMARY KEY",
                        location=f"Table: {table.name}",
                        suggested_fix="Add PRIMARY KEY constraint",
                    )
                )

        return violations


class DocumentationRule(LintRule):
    """Require COMMENT on all tables."""

    name = "DocumentationRule"
    description = "Requires COMMENT on all tables"

    def lint(
        self,
        tables: list[Any],
        _config: dict[str, Any],
    ) -> list[Violation]:
        """Check that all tables have documentation."""
        violations = []

        for table in tables:
            # Skip system tables
            if table.name.startswith("pg_"):
                continue

            comment = getattr(table, "comment", None)
            if not comment or not comment.strip():
                violations.append(
                    self._create_violation(
                        severity=LintSeverity.WARNING,
                        message=(
                            f"Table '{table.name}' missing documentation"
                        ),
                        location=f"Table: {table.name}",
                        suggested_fix=(
                            f"Add: COMMENT ON TABLE {table.name} IS "
                            "'Description...'"
                        ),
                    )
                )

        return violations


class MultiTenantRule(LintRule):
    """Enforce tenant_id in multi-tenant tables."""

    name = "MultiTenantRule"
    description = "Enforces tenant_id in multi-tenant tables"

    def lint(
        self,
        tables: list[Any],
        config: dict[str, Any],
    ) -> list[Violation]:
        """Check that multi-tenant tables have tenant identifier."""
        violations = []
        identifier = config.get("identifier", "tenant_id")

        # Heuristic: these table names suggest multi-tenancy
        multi_tenant_patterns = [
            "customer",
            "tenant",
            "organization",
            "account",
            "workspace",
            "company",
        ]

        for table in tables:
            # Check if table looks like it should be multi-tenant
            table_name_lower = table.name.lower()
            is_multi_tenant = any(
                pattern in table_name_lower for pattern in multi_tenant_patterns
            )

            if is_multi_tenant:
                # Check if tenant_id column exists
                has_tenant_id = any(
                    c.name == identifier for c in table.columns
                )

                if not has_tenant_id:
                    violations.append(
                        self._create_violation(
                            severity=LintSeverity.ERROR,
                            message=(
                                f"Multi-tenant table '{table.name}' "
                                f"missing '{identifier}'"
                            ),
                            location=f"Table: {table.name}",
                            suggested_fix=(
                                f"Add column: {identifier} UUID "
                                f"REFERENCES tenants(id)"
                            ),
                        )
                    )

        return violations


class MissingIndexRule(LintRule):
    """Warn about unindexed foreign key columns."""

    name = "MissingIndexRule"
    description = "Detects unindexed foreign keys"

    def lint(
        self,
        tables: list[Any],
        _config: dict[str, Any],
    ) -> list[Violation]:
        """Check that foreign keys are indexed."""
        violations = []

        for table in tables:
            for column in table.columns:
                # Check if column is a foreign key
                if not getattr(column, "is_foreign_key", False):
                    continue

                # Check if column is indexed
                is_indexed = any(
                    column.name in getattr(idx, "columns", [])
                    for idx in getattr(table, "indexes", [])
                )

                if not is_indexed:
                    violations.append(
                        self._create_violation(
                            severity=LintSeverity.WARNING,
                            message=(
                                f"Foreign key '{column.name}' "
                                "should be indexed"
                            ),
                            location=f"{table.name}.{column.name}",
                            suggested_fix=(
                                f"Add: CREATE INDEX ON "
                                f"{table.name}({column.name})"
                            ),
                        )
                    )

        return violations


class SecurityRule(LintRule):
    """Validate security best practices."""

    name = "SecurityRule"
    description = "Checks for security best practices"

    def lint(
        self,
        tables: list[Any],
        _config: dict[str, Any],
    ) -> list[Violation]:
        """Check for security best practices."""
        violations = []

        for table in tables:
            for column in table.columns:
                # Check for "password" columns
                if "password" in column.name.lower():
                    col_type = getattr(column, "column_type", "").upper()
                    if col_type in ("VARCHAR", "TEXT", "CHAR"):
                        violations.append(
                            self._create_violation(
                                severity=LintSeverity.WARNING,
                                message=(
                                    f"Column '{column.name}' may contain "
                                    "passwords - should be hashed"
                                ),
                                location=f"{table.name}.{column.name}",
                                suggested_fix=(
                                    "Use bcrypt/argon2 hashing, "
                                    "never store plain passwords"
                                ),
                            )
                        )

                # Check for "token" or "secret" or "key" columns
                sensitive_words = ["token", "secret", "key"]
                if any(word in column.name.lower() for word in sensitive_words):
                    violations.append(
                        self._create_violation(
                            severity=LintSeverity.WARNING,
                            message=(
                                f"Column '{column.name}' contains "
                                "sensitive data - should be encrypted"
                            ),
                            location=f"{table.name}.{column.name}",
                            suggested_fix=(
                                "Use encrypted column or external "
                                "secrets manager"
                            ),
                        )
                    )

        return violations


class SchemaLinter:
    """Main orchestrator for schema linting.

    Loads schema DDL, parses it into tables, and runs all enabled linting
    rules, collecting violations into a report.

    Attributes:
        env: Environment name (local, test, production, etc.)
        config: LintConfig with rule settings
        rules: Dict mapping rule names to LintRule instances
    """

    def __init__(
        self,
        env: str,
        config: LintConfig | None = None,
        conn: Any = None,
    ):
        """Initialize linter for given environment.

        Args:
            env: Environment name
            config: LintConfig (uses default if not provided)
            conn: Optional psycopg connection for database access
        """
        self.env = env
        self.config = config or LintConfig.default()
        self.conn = conn
        self.builder = SchemaBuilder(env)
        self.differ = SchemaDiffer()
        self.rules: dict[str, LintRule] = {}
        self._register_rules()

    def _register_rules(self) -> None:
        """Register all built-in linting rules."""
        self.rules = {
            "naming_convention": NamingConventionRule(),
            "primary_key": PrimaryKeyRule(),
            "documentation": DocumentationRule(),
            "multi_tenant": MultiTenantRule(),
            "missing_index": MissingIndexRule(),
            "security": SecurityRule(),
        }

    def lint(self) -> LintReport:
        """Run all enabled rules and return aggregated report.

        Returns:
            LintReport with all violations found and metrics

        Example:
            >>> linter = SchemaLinter(env="local")
            >>> report = linter.lint()
            >>> print(f"Found {report.errors_count} errors")
        """
        start_time = time.time()

        # Build and parse schema
        tables = self._load_and_parse_schema()

        # Execute linting rules
        all_violations = self._execute_rules(tables)

        # Build and return report
        execution_time_ms = int((time.time() - start_time) * 1000)
        return self._create_report(all_violations, tables, execution_time_ms)

    def _load_and_parse_schema(self) -> list[Any]:
        """Load schema from DDL files and parse into table objects.

        Returns:
            List of parsed table objects
        """
        # Build schema from DDL files
        schema_content = self.builder.build()

        # Parse into table objects
        tables = self.differ.parse_sql(schema_content)

        # Filter excluded tables
        excluded_tables = set(self.config.exclude_tables)
        return [
            t for t in tables
            if t.name not in excluded_tables
        ]

    def _execute_rules(self, tables: list[Any]) -> list[Violation]:
        """Execute all enabled linting rules against tables.

        Args:
            tables: List of parsed table objects

        Returns:
            List of all violations found by all rules
        """
        all_violations = []
        for rule_name, rule in self.rules.items():
            if rule_name not in self.config.rules:
                continue  # Skip if not in config

            rule_config = self.config.rules[rule_name]
            violations = rule.lint(tables, rule_config)
            all_violations.extend(violations)

        return all_violations

    def _create_report(
        self,
        violations: list[Violation],
        tables: list[Any],
        execution_time_ms: int,
    ) -> LintReport:
        """Create a LintReport from violations and metrics.

        Args:
            violations: List of violations found
            tables: List of tables that were checked
            execution_time_ms: Time taken to lint in milliseconds

        Returns:
            Populated LintReport instance
        """
        errors = [
            v for v in violations
            if v.severity == LintSeverity.ERROR
        ]
        warnings = [
            v for v in violations
            if v.severity == LintSeverity.WARNING
        ]
        infos = [
            v for v in violations
            if v.severity == LintSeverity.INFO
        ]

        return LintReport(
            violations=violations,
            schema_name=self.env,
            tables_checked=len(tables),
            columns_checked=sum(len(t.columns) for t in tables),
            errors_count=len(errors),
            warnings_count=len(warnings),
            info_count=len(infos),
            execution_time_ms=execution_time_ms,
        )
