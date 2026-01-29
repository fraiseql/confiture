"""Tenant isolation linting rule for schema linter integration.

This module provides a linting rule that detects INSERT statements
missing FK columns required for tenant filtering.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.schema_linter import LintReport, LintViolation, RuleSeverity
from confiture.core.linting.tenant.function_parser import FunctionParser
from confiture.core.linting.tenant.tenant_detector import TenantDetector


class TenantIsolationRule:
    """Linting rule for tenant isolation validation.

    Detects INSERT statements in PostgreSQL functions that are missing
    FK columns required for tenant filtering in multi-tenant systems.

    Example:
        >>> rule = TenantIsolationRule()
        >>> report = LintReport()
        >>> rule.run(view_sqls=[...], function_sqls=[...], report=report)
        >>> if report.has_warnings:
        ...     print("Found tenant isolation issues")
    """

    rule_id = "tenant_001"
    rule_name = "Tenant Isolation"
    description = "Detects INSERT statements missing FK columns required for tenant filtering"

    def __init__(
        self,
        tenant_patterns: list[str] | None = None,
        severity: RuleSeverity = RuleSeverity.WARNING,
    ):
        """Initialize the tenant isolation rule.

        Args:
            tenant_patterns: List of tenant column patterns to detect.
                Defaults to ["tenant_id", "organization_id", "org_id"].
            severity: Severity level for violations. Defaults to WARNING.
        """
        self.tenant_patterns = tenant_patterns
        self.severity = severity
        self.detector = TenantDetector(tenant_patterns=tenant_patterns)
        self.function_parser = FunctionParser()

    def run(
        self,
        view_sqls: list[str],
        function_sqls: list[str],
        report: LintReport,
        file_path: str | None = None,
    ) -> None:
        """Run the tenant isolation rule.

        Args:
            view_sqls: List of CREATE VIEW SQL statements
            function_sqls: List of CREATE FUNCTION SQL statements
            report: LintReport to add violations to
            file_path: Optional file path for violation reporting
        """
        # Parse functions to extract INSERT statements
        functions = []
        for sql in function_sqls:
            parsed = self.function_parser.extract_functions(sql)
            functions.extend(parsed)

        # Analyze schema for violations
        violations = self.detector.analyze_schema(
            view_sqls=view_sqls,
            functions=functions,
            file_path=file_path or "unknown",
        )

        # Convert to LintViolations and add to report
        for violation in violations:
            lint_violation = LintViolation(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                severity=self.severity,
                object_type="function",
                object_name=violation.function_name,
                message=self._build_message(violation),
                file_path=violation.file_path if violation.file_path != "unknown" else None,
                line_number=violation.line_number,
            )
            report.add_violation(lint_violation)

    def run_from_files(
        self,
        view_paths: list[Path],
        function_paths: list[Path],
        report: LintReport,
    ) -> None:
        """Run the rule against SQL files.

        Args:
            view_paths: Paths to VIEW SQL files
            function_paths: Paths to function SQL files
            report: LintReport to add violations to
        """
        # Read view files
        view_sqls = []
        for path in view_paths:
            if path.exists():
                view_sqls.append(path.read_text())

        # Read and analyze function files
        for func_path in function_paths:
            if not func_path.exists():
                continue

            func_sql = func_path.read_text()
            self.run(
                view_sqls=view_sqls,
                function_sqls=[func_sql],
                report=report,
                file_path=str(func_path),
            )

    def run_from_directories(
        self,
        view_dirs: list[Path],
        function_dirs: list[Path],
        report: LintReport,
        pattern: str = "*.sql",
    ) -> None:
        """Run the rule against SQL files in directories.

        Args:
            view_dirs: Directories containing VIEW SQL files
            function_dirs: Directories containing function SQL files
            report: LintReport to add violations to
            pattern: Glob pattern for SQL files (default: "*.sql")
        """
        # Collect view files
        view_paths = []
        for dir_path in view_dirs:
            if dir_path.exists():
                view_paths.extend(dir_path.glob(pattern))

        # Collect function files
        function_paths = []
        for dir_path in function_dirs:
            if dir_path.exists():
                function_paths.extend(dir_path.glob(pattern))

        self.run_from_files(
            view_paths=view_paths,
            function_paths=function_paths,
            report=report,
        )

    def _build_message(self, violation) -> str:
        """Build human-readable message from violation.

        Args:
            violation: TenantViolation object

        Returns:
            Formatted message string
        """
        cols = ", ".join(violation.missing_columns)
        views = ", ".join(violation.affected_views)

        return (
            f"INSERT into '{violation.table_name}' is missing FK column(s): {cols}. "
            f"Required for tenant filtering in view(s): {views}"
        )
