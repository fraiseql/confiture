"""Tests for linting models (Violation, LintConfig, LintReport)."""

import pytest
from pathlib import Path
from datetime import datetime

from confiture.models.lint import (
    LintSeverity,
    Violation,
    LintConfig,
    LintReport,
)


class TestLintSeverity:
    """Tests for LintSeverity enum."""

    def test_severity_values(self):
        """LintSeverity should have ERROR, WARNING, INFO."""
        assert LintSeverity.ERROR.value == "error"
        assert LintSeverity.WARNING.value == "warning"
        assert LintSeverity.INFO.value == "info"

    def test_severity_string_comparison(self):
        """LintSeverity should compare as string."""
        assert str(LintSeverity.ERROR) == "LintSeverity.ERROR"
        assert LintSeverity.ERROR == LintSeverity.ERROR


class TestViolation:
    """Tests for Violation dataclass."""

    def test_violation_creation_minimal(self):
        """Violation should require rule_name, severity, message, location."""
        violation = Violation(
            rule_name="TestRule",
            severity=LintSeverity.ERROR,
            message="Test message",
            location="test_location",
        )

        assert violation.rule_name == "TestRule"
        assert violation.severity == LintSeverity.ERROR
        assert violation.message == "Test message"
        assert violation.location == "test_location"
        assert violation.suggested_fix is None

    def test_violation_creation_with_suggested_fix(self):
        """Violation should accept optional suggested_fix."""
        violation = Violation(
            rule_name="NamingConvention",
            severity=LintSeverity.ERROR,
            message="Table 'UserTable' should be 'user_table'",
            location="Table: UserTable",
            suggested_fix="Rename to 'user_table'",
        )

        assert violation.suggested_fix == "Rename to 'user_table'"

    def test_violation_string_representation(self):
        """Violation should have readable string representation."""
        violation = Violation(
            rule_name="TestRule",
            severity=LintSeverity.ERROR,
            message="Test message",
            location="test_location",
        )

        str_repr = str(violation)
        assert "ERROR" in str_repr.upper()
        assert "test_location" in str_repr
        assert "Test message" in str_repr


class TestLintConfig:
    """Tests for LintConfig dataclass."""

    def test_lint_config_default(self):
        """LintConfig.default() should return sensible defaults."""
        config = LintConfig.default()

        assert config.enabled is True
        assert config.fail_on_error is True
        assert config.fail_on_warning is False
        assert len(config.rules) == 6

    def test_lint_config_default_has_all_rules(self):
        """LintConfig.default() should have all 6 rules."""
        config = LintConfig.default()

        required_rules = [
            "naming_convention",
            "primary_key",
            "documentation",
            "multi_tenant",
            "missing_index",
            "security",
        ]

        for rule in required_rules:
            assert rule in config.rules
            assert isinstance(config.rules[rule], dict)

    def test_lint_config_default_naming_convention(self):
        """LintConfig.default() should configure naming_convention rule."""
        config = LintConfig.default()

        assert "naming_convention" in config.rules
        assert config.rules["naming_convention"].get("style") == "snake_case"

    def test_lint_config_default_multi_tenant(self):
        """LintConfig.default() should configure multi_tenant rule."""
        config = LintConfig.default()

        assert "multi_tenant" in config.rules
        assert config.rules["multi_tenant"].get("identifier") == "tenant_id"

    def test_lint_config_custom(self):
        """LintConfig should accept custom rules."""
        config = LintConfig(
            enabled=True,
            rules={
                "naming_convention": {"style": "PascalCase"},
                "primary_key": {"enabled": True},
            },
        )

        assert config.rules["naming_convention"]["style"] == "PascalCase"

    def test_lint_config_exclude_tables(self):
        """LintConfig should support excluding tables."""
        config = LintConfig(
            enabled=True,
            exclude_tables=["pg_*", "information_schema.*"],
        )

        assert "pg_*" in config.exclude_tables
        assert "information_schema.*" in config.exclude_tables

    def test_lint_config_fail_modes(self):
        """LintConfig should support fail_on_error and fail_on_warning."""
        config = LintConfig(
            fail_on_error=True,
            fail_on_warning=True,
        )

        assert config.fail_on_error is True
        assert config.fail_on_warning is True

    def test_lint_config_disabled(self):
        """LintConfig should support disabling linting entirely."""
        config = LintConfig(enabled=False)

        assert config.enabled is False


class TestLintReport:
    """Tests for LintReport dataclass."""

    def test_lint_report_creation(self):
        """LintReport should store all information."""
        violations = [
            Violation(
                rule_name="NamingConvention",
                severity=LintSeverity.ERROR,
                message="Bad name",
                location="table1",
            ),
            Violation(
                rule_name="PrimaryKey",
                severity=LintSeverity.ERROR,
                message="Missing PK",
                location="table2",
            ),
            Violation(
                rule_name="Documentation",
                severity=LintSeverity.WARNING,
                message="Missing comment",
                location="table1",
            ),
        ]

        report = LintReport(
            violations=violations,
            schema_name="local",
            tables_checked=10,
            columns_checked=50,
            errors_count=2,
            warnings_count=1,
            info_count=0,
            execution_time_ms=123,
        )

        assert report.schema_name == "local"
        assert report.tables_checked == 10
        assert report.columns_checked == 50
        assert report.errors_count == 2
        assert report.warnings_count == 1
        assert report.info_count == 0
        assert report.execution_time_ms == 123
        assert len(report.violations) == 3

    def test_lint_report_has_errors_property(self):
        """LintReport.has_errors should be True if errors_count > 0."""
        report_with_errors = LintReport(
            violations=[],
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=1,
            warnings_count=0,
            info_count=0,
            execution_time_ms=100,
        )

        report_without_errors = LintReport(
            violations=[],
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=0,
            warnings_count=1,
            info_count=0,
            execution_time_ms=100,
        )

        assert report_with_errors.has_errors is True
        assert report_without_errors.has_errors is False

    def test_lint_report_has_warnings_property(self):
        """LintReport.has_warnings should be True if warnings_count > 0."""
        report_with_warnings = LintReport(
            violations=[],
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=0,
            warnings_count=1,
            info_count=0,
            execution_time_ms=100,
        )

        report_without_warnings = LintReport(
            violations=[],
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=0,
            warnings_count=0,
            info_count=1,
            execution_time_ms=100,
        )

        assert report_with_warnings.has_warnings is True
        assert report_without_warnings.has_warnings is False

    def test_lint_report_violations_by_severity(self):
        """LintReport.violations_by_severity() should group violations."""
        violations = [
            Violation(
                rule_name="Rule1",
                severity=LintSeverity.ERROR,
                message="Error 1",
                location="loc1",
            ),
            Violation(
                rule_name="Rule2",
                severity=LintSeverity.ERROR,
                message="Error 2",
                location="loc2",
            ),
            Violation(
                rule_name="Rule3",
                severity=LintSeverity.WARNING,
                message="Warning 1",
                location="loc3",
            ),
            Violation(
                rule_name="Rule4",
                severity=LintSeverity.INFO,
                message="Info 1",
                location="loc4",
            ),
        ]

        report = LintReport(
            violations=violations,
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=2,
            warnings_count=1,
            info_count=1,
            execution_time_ms=100,
        )

        grouped = report.violations_by_severity()

        assert len(grouped[LintSeverity.ERROR]) == 2
        assert len(grouped[LintSeverity.WARNING]) == 1
        assert len(grouped[LintSeverity.INFO]) == 1

    def test_lint_report_empty_violations(self):
        """LintReport should handle empty violations list."""
        report = LintReport(
            violations=[],
            schema_name="test",
            tables_checked=10,
            columns_checked=50,
            errors_count=0,
            warnings_count=0,
            info_count=0,
            execution_time_ms=50,
        )

        assert len(report.violations) == 0
        assert report.has_errors is False
        assert report.has_warnings is False

    def test_lint_report_string_representation(self):
        """LintReport should have readable string representation."""
        violations = [
            Violation(
                rule_name="TestRule",
                severity=LintSeverity.ERROR,
                message="Test error",
                location="test_loc",
            ),
        ]

        report = LintReport(
            violations=violations,
            schema_name="local",
            tables_checked=5,
            columns_checked=20,
            errors_count=1,
            warnings_count=0,
            info_count=0,
            execution_time_ms=100,
        )

        # Should not raise an error
        str_repr = str(report)
        assert isinstance(str_repr, str)
