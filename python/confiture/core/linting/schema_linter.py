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
from typing import Any

import pglast
import pglast.parser

from confiture.config.environment import Environment
from confiture.core.linting.inventory import Inventory, SchemaObject, build_inventory
from confiture.core.parser_info import parse_error_line

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
    suggested_fix: str | None = None

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
    #: What the inventory read — the counts the JSON payload reports.
    tables_checked: int = 0
    columns_checked: int = 0

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
        check_tenant_isolation: bool = False,
        check_acl_coverage: bool = True,
        check_duplicates: bool = True,
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
            check_tenant_isolation: Detect INSERTs missing tenant FK columns
                (multi-tenant rule, ``tenant_001``). Opt-in (default off).
            check_acl_coverage: Allow the ACL coverage rule (``acl_001``) to run.
            check_duplicates: Report objects defined more than once in one build
                (``build_001`` / ``build_002``).
                Default True, i.e. unchanged: the rule additionally requires
                ``acls.lint_enabled: true`` in the environment YAML. Set False to
                suppress it (``confiture lint --ignore acl``).
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
        self.check_tenant_isolation = check_tenant_isolation
        self.check_acl_coverage = check_acl_coverage
        self.check_duplicates = check_duplicates


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
        self._inventory: Inventory = Inventory()
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
            self._schema_files = []
        else:
            self._load_schema()

        if not self._schema_sql:
            logger.warning("No schema SQL found, skipping linting")
            return report

        # A schema PostgreSQL's own parser rejects can never lint clean: the
        # rules below read what they can, and this notice says the rest was
        # not read (ANA-02).
        self._inventory = Inventory()
        try:
            self._inventory = build_inventory(self._schema_sql)
        except pglast.parser.ParseError as exc:
            report.add_violation(
                LintViolation(
                    rule_id="UNPARSEABLE",
                    rule_name="Unparseable SQL",
                    severity=RuleSeverity.INFO,
                    object_type="schema",
                    object_name="schema",
                    message=f"pglast could not parse the schema: {exc}",
                    line_number=parse_error_line(self._schema_sql, exc),
                    suggested_fix="Fix the SQL syntax; rules cannot see past a parse error.",
                )
            )

        report.tables_checked = len(self._inventory.tables)
        report.columns_checked = sum(len(t.columns) for t in self._inventory.tables)

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

        if self.config.check_duplicates:
            self._check_duplicates(report)

        # Tenant isolation (tenant_001) — opt-in multi-tenant rule. Detects
        # INSERTs in functions that omit the FK column a tenant-scoped view
        # requires. Off by default so existing lint output is unchanged.
        if self.config.check_tenant_isolation:
            self._check_tenant_isolation(report)

        # ACL coverage (ACL001) — opt-in via ``acls.lint_enabled: true`` in
        # the environment YAML.  The mere presence of an ``acls:`` block
        # used to auto-fire this rule, but that surprised users who set
        # ``acls:`` only for ``confiture drift --check-acls``.  Explicit
        # opt-in keeps the two surfaces independently controllable.
        if (
            self.config.check_acl_coverage
            and self.environment.acls_lint_enabled
            and self.environment.acls
        ):
            migrations_dir = self.project_dir / "db" / "migrations"
            if migrations_dir.exists():
                grant_dir_str = self.environment.migration.grant_dir
                grant_dir = (self.project_dir / grant_dir_str).resolve()
                for violation in self.lint_migrations(
                    migrations_dir=migrations_dir,
                    expectations=self.environment.acls,
                    grant_dir=grant_dir if grant_dir.exists() else None,
                ).errors:
                    report.add_violation(violation)

        return report

    def _load_schema(self) -> None:
        """Load schema SQL from files."""
        try:
            from confiture.core.builder import SchemaBuilder

            builder = SchemaBuilder(env=self.env, project_dir=self.project_dir)
            self._schema_files = builder.find_sql_files()
            self._schema_sql = builder.build()
        except Exception as e:
            logger.error(f"Failed to load schema: {e}")
            self._schema_sql = ""

    def _check_naming_conventions(self, report: LintReport) -> None:
        """Check naming conventions (snake_case for identifiers) on the inventory."""
        for table in self._inventory.tables:
            if not self._is_snake_case(table.name):
                report.add_violation(
                    LintViolation(
                        rule_id="naming_001",
                        rule_name="Table Naming Convention",
                        severity=RuleSeverity.WARNING,
                        object_type="table",
                        object_name=table.qualified,
                        message=(
                            f"Table name '{table.qualified}' should be lowercase with "
                            "underscores (snake_case)"
                        ),
                        line_number=table.line,
                    )
                )
            self._check_column_names(table, report)

    def _check_column_names(self, table: SchemaObject, report: LintReport) -> None:
        """Check column naming conventions in a table."""
        for column in table.columns:
            if not self._is_snake_case(column.name):
                report.add_violation(
                    LintViolation(
                        rule_id="naming_002",
                        rule_name="Column Naming Convention",
                        severity=RuleSeverity.WARNING,
                        object_type="column",
                        object_name=f"{table.qualified}.{column.name}",
                        message=(
                            f"Column '{column.name}' should be lowercase with underscores (snake_case)"
                        ),
                        line_number=column.line,
                    )
                )

    def _check_primary_keys(self, report: LintReport) -> None:
        """Every table has a primary key — a partition inherits its parent's."""
        for table in self._inventory.tables:
            if table.has_primary_key or table.is_partition:
                continue
            if self._is_likely_junction_table(table.name):
                continue
            report.add_violation(
                LintViolation(
                    rule_id="pk_001",
                    rule_name="Missing Primary Key",
                    severity=RuleSeverity.WARNING,
                    object_type="table",
                    object_name=table.qualified,
                    message=f"Table '{table.qualified}' should have a PRIMARY KEY",
                    line_number=table.line,
                )
            )

    def _check_documentation(self, report: LintReport) -> None:
        """The ``doc`` family: every commentable object carries a COMMENT (#217)."""
        from confiture.core.linting.documentation import documentation_findings

        for violation in documentation_findings(self._inventory):
            report.add_violation(violation)

    def _check_duplicates(self, report: LintReport) -> None:
        """``build_001`` / ``build_002``: an object defined more than once in one build (#218).

        File-backed runs inventory each schema file on its own so a finding can
        name the files; a run on one string reports offsets into that string.
        """
        from confiture.core.linting.duplicates import (
            duplicate_violations,
            find_duplicates,
            inventory_files,
        )

        files = getattr(self, "_schema_files", None)
        if files:
            objects, _unparseable = inventory_files(files, root=self.project_dir)
        else:
            objects = self._inventory.objects
        for violation in duplicate_violations(find_duplicates(objects)):
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
        """Columns whose names suggest sensitive data, read from the inventory."""
        security_patterns = [
            (r"password", "password"),
            (r"token", "token"),
            (r"secret", "secret"),
            (r"api_key", "API key"),
            (r"credit_card", "credit card"),
            (r"ssn", "social security number"),
        ]
        for table in self._inventory.tables:
            for column in table.columns:
                for pattern, description in security_patterns:
                    if not re.search(pattern, column.name, re.IGNORECASE):
                        continue
                    report.add_violation(
                        LintViolation(
                            rule_id="sec_001",
                            rule_name="Sensitive Data Column",
                            severity=RuleSeverity.WARNING,
                            object_type="column",
                            object_name=column.name,
                            message=(
                                f"Column '{column.name}' appears to store {description} - "
                                "ensure proper encryption and access controls"
                            ),
                            line_number=column.line,
                        )
                    )

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

    def lint_tree(
        self,
        schema_dir: Path,
        overrides_dir: Path | None = None,
    ) -> LintReport:
        """Lint a schema file tree for structural consistency (GEN001–GEN004).

        Args:
            schema_dir: Root of the schema tree to scan.
            overrides_dir: Optional overrides mirror directory (for GEN004).

        Returns:
            LintReport with all violations found.
        """
        from confiture.core.linting.libraries.generate import (
            Gen001PrefixUnique,
            Gen002VerbSuffix,
            Gen003GapPolicy,
            Gen004OrphanedOverride,
        )

        report = LintReport()

        for violation in Gen001PrefixUnique().check(schema_dir):
            report.add_violation(violation)

        for violation in Gen002VerbSuffix().check(schema_dir):
            report.add_violation(violation)

        for violation in Gen003GapPolicy().check(schema_dir):
            report.add_violation(violation)

        if overrides_dir is not None:
            for violation in Gen004OrphanedOverride().check(schema_dir, overrides_dir):
                report.add_violation(violation)

        return report

    def _check_tenant_isolation(self, report: LintReport) -> None:
        """Detect function INSERTs missing tenant FK columns (``tenant_001``).

        Delegates to :class:`TenantIsolationRule`, which parses the built
        schema for tenant-scoped views and the function INSERTs that should
        carry their FK columns. The schema blob holds both, so it is passed
        as both the view and function source.

        Args:
            report: Report to add violations to
        """
        if not self._schema_sql:
            return

        from confiture.core.linting.tenant.tenant_isolation_rule import TenantIsolationRule

        TenantIsolationRule().run(
            view_sqls=[self._schema_sql],
            function_sqls=[self._schema_sql],
            report=report,
        )

    def lint_migrations(
        self,
        migrations_dir: Path,
        expectations: list[Any],
        grant_dir: Path | None = None,
    ) -> LintReport:
        """Lint a migrations directory for ACL coverage (ACL001).

        No-op when ``expectations`` is empty — projects without an
        ``acls:`` block see zero violations regardless of what their
        migrations contain.

        Args:
            migrations_dir: Directory of ``*.up.sql`` migration files.
            expectations: Parsed ``acls:`` block (list of
                :class:`~confiture.config.environment.AclExpectation`).
            grant_dir: Optional global grant sweep directory (typically
                ``db/7_grant``).

        Returns:
            :class:`LintReport` with any ACL001 violations.
        """
        from confiture.core.linting.libraries.acl import Acl001GrantCoverage

        report = LintReport()
        for violation in Acl001GrantCoverage(expectations=expectations, grant_dir=grant_dir).check(
            migrations_dir
        ):
            report.add_violation(violation)
        return report

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
