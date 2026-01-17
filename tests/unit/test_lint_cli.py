"""Tests for lint CLI command.

These tests verify the lint command integrates properly with the CLI framework.
"""

from unittest.mock import ANY, MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import (
    LintReport,
    LintViolation,
    RuleSeverity,
)

# Create test runner
runner = CliRunner()


class TestLintCommand:
    """Tests for the lint CLI command."""

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_basic(self, mock_linter_class):
        """Should execute lint command and display results."""
        # Mock the linter
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        # Mock report with no violations (using schema_linter.LintReport format)
        mock_report = LintReport(errors=[], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run command
        result = runner.invoke(app, ["lint"])

        # Should succeed
        assert result.exit_code == 0
        assert "No violations found" in result.stdout

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_with_env(self, mock_linter_class):
        """Should respect --env option."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        mock_report = LintReport(errors=[], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run with --env
        result = runner.invoke(app, ["lint", "--env", "production"])

        assert result.exit_code == 0
        mock_linter_class.assert_called_with(env="production", config=ANY)

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_with_errors_fail_on_error(self, mock_linter_class):
        """Should fail with exit code 1 when errors found and fail_on_error=True."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        # Create report with errors
        violation = LintViolation(
            rule_id="pk_001",
            rule_name="PrimaryKeyRule",
            severity=RuleSeverity.ERROR,
            object_type="table",
            object_name="users",
            message="Table 'users' missing PRIMARY KEY",
        )
        mock_report = LintReport(errors=[violation], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run command (fail_on_error defaults to True)
        result = runner.invoke(app, ["lint"])

        # Should fail
        assert result.exit_code == 1

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_with_warnings_fail_on_warning(self, mock_linter_class):
        """Should fail with exit code 1 when warnings found and fail_on_warning=True."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        # Create report with warnings
        violation = LintViolation(
            rule_id="doc_001",
            rule_name="DocumentationRule",
            severity=RuleSeverity.WARNING,
            object_type="table",
            object_name="users",
            message="Table 'users' missing documentation",
        )
        mock_report = LintReport(errors=[], warnings=[violation], info=[])
        mock_linter.lint.return_value = mock_report

        # Run with --fail-on-warning
        result = runner.invoke(app, ["lint", "--fail-on-warning"])

        # Should fail
        assert result.exit_code == 1

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_with_warnings_no_fail(self, mock_linter_class):
        """Should succeed when warnings found but fail_on_warning=False."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        # Create report with warnings
        violation = LintViolation(
            rule_id="doc_001",
            rule_name="DocumentationRule",
            severity=RuleSeverity.WARNING,
            object_type="table",
            object_name="users",
            message="Table 'users' missing documentation",
        )
        mock_report = LintReport(errors=[], warnings=[violation], info=[])
        mock_linter.lint.return_value = mock_report

        # Run without --fail-on-warning (defaults to False)
        result = runner.invoke(app, ["lint"])

        # Should succeed
        assert result.exit_code == 0

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_json_format(self, mock_linter_class):
        """Should output JSON format when --format json specified."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        mock_report = LintReport(errors=[], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run with --format json
        result = runner.invoke(app, ["lint", "--format", "json"])

        assert result.exit_code == 0
        assert '"schema_name": "local"' in result.stdout
        assert '"violations"' in result.stdout

    @patch("confiture.cli.main.SchemaLinter")
    def test_lint_command_csv_format(self, mock_linter_class):
        """Should output CSV format when --format csv specified."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        violation = LintViolation(
            rule_id="test_001",
            rule_name="TestRule",
            severity=RuleSeverity.ERROR,
            object_type="table",
            object_name="test_table",
            message="Test message",
        )
        mock_report = LintReport(errors=[violation], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run with --format csv
        result = runner.invoke(app, ["lint", "--format", "csv"])

        assert result.exit_code == 1  # Has errors
        assert "rule_name,severity,location,message" in result.stdout
        assert "TestRule" in result.stdout

    @patch("confiture.cli.main.SchemaLinter")
    @patch("confiture.cli.main.save_report")
    def test_lint_command_save_json_output(self, mock_save, mock_linter_class):
        """Should save JSON output to file when --output specified."""
        mock_linter = MagicMock()
        mock_linter_class.return_value = mock_linter

        mock_report = LintReport(errors=[], warnings=[], info=[])
        mock_linter.lint.return_value = mock_report

        # Run with --output and --format json
        result = runner.invoke(
            app,
            ["lint", "--format", "json", "--output", "/tmp/report.json"],
        )

        assert result.exit_code == 0
        mock_save.assert_called_once()

    def test_lint_command_invalid_format(self):
        """Should fail with invalid format option."""
        result = runner.invoke(app, ["lint", "--format", "invalid"])

        assert result.exit_code == 1
        assert "Invalid format" in result.stdout or "Invalid format" in result.stderr
