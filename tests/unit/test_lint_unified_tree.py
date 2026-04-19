"""Tests for lint-unified tree check functionality.

Tests for the --check tree option in lint-unified command that calls lint_tree().
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import (
    LintReport,
    LintViolation,
    RuleSeverity,
)

# Create test runner
runner = CliRunner()


class TestLintUnifiedTree:
    """Tests for the lint-unified --check tree functionality."""

    def test_lint_unified_accepts_check_tree_flag(self, tmp_path):
        """Should accept --check tree flag without crashing."""
        # Create a temp schema directory with clean files
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE test (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock tree report with no violations
            mock_tree_report = LintReport(errors=[], warnings=[], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Run command
            result = runner.invoke(app, ["lint-unified", "--check", "tree", str(schema_dir)])

            # Should succeed (exit code 0, no crash)
            assert result.exit_code == 0

    def test_lint_unified_tree_reports_gen001_duplicate_prefix(self, tmp_path):
        """Should report GEN001 duplicate prefix violations."""
        # Create temp dir with duplicate prefixes
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_foo.sql").write_text("CREATE TABLE foo (id INT);")
        (schema_dir / "01_bar.sql").write_text("CREATE TABLE bar (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock violation for GEN001
            violation = LintViolation(
                rule_id="GEN001",
                rule_name="DuplicatePrefix",
                severity=RuleSeverity.ERROR,
                object_type="file",
                object_name="01_foo.sql",
                message="Multiple files with prefix '01'",
                file_path=str(schema_dir / "01_foo.sql"),
                line_number=1,
            )
            mock_tree_report = LintReport(errors=[violation], warnings=[], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Run command
            result = runner.invoke(app, ["lint-unified", "--check", "tree", "--schema-dir", str(schema_dir)])

            # Should fail due to ERROR severity
            assert result.exit_code == 1
            assert "GEN001" in result.stdout

    def test_lint_unified_tree_reports_gen003_gap(self, tmp_path):
        """Should report GEN003 gap violations."""
        # Create temp dir with gap (01, 03 but no 02)
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_foo.sql").write_text("CREATE TABLE foo (id INT);")
        (schema_dir / "03_bar.sql").write_text("CREATE TABLE bar (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock violation for GEN003
            violation = LintViolation(
                rule_id="GEN003",
                rule_name="GapInSequence",
                severity=RuleSeverity.WARNING,
                object_type="directory",
                object_name=str(schema_dir),
                message="Gap in numbering sequence at position 02",
                file_path=None,
                line_number=None,
            )
            mock_tree_report = LintReport(errors=[], warnings=[violation], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Run command
            result = runner.invoke(app, ["lint-unified", "--check", "tree", "--schema-dir", str(schema_dir)])

            # Should succeed (exit code 0, WARNING not ERROR)
            assert result.exit_code == 0
            assert "GEN003" in result.stdout

    def test_lint_unified_tree_json_output_includes_tree_tool(self, tmp_path):
        """Should include tree tool in JSON output."""
        # Create temp schema dir
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE test (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock violation
            violation = LintViolation(
                rule_id="GEN001",
                rule_name="DuplicatePrefix",
                severity=RuleSeverity.ERROR,
                object_type="file",
                object_name="01_tables.sql",
                message="Test violation",
                file_path=str(schema_dir / "01_tables.sql"),
                line_number=1,
            )
            mock_tree_report = LintReport(errors=[violation], warnings=[], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Run command with JSON format
            result = runner.invoke(
                app,
                ["lint-unified", "--check", "tree", "--format", "json", "--schema-dir", str(schema_dir)]
            )

            assert result.exit_code == 1  # Has errors

            # Parse JSON and check for tree tool
            output = json.loads(result.stdout)
            issues = output.get("issues", [])
            assert len(issues) > 0

            # Find the tree issue
            tree_issues = [issue for issue in issues if issue.get("tool") == "tree"]
            assert len(tree_issues) > 0

    def test_lint_unified_no_check_includes_tree(self, tmp_path):
        """Should include tree checks when no --check filter is given."""
        # Create temp dir with GEN001 violation
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_foo.sql").write_text("CREATE TABLE foo (id INT);")
        (schema_dir / "01_bar.sql").write_text("CREATE TABLE bar (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock violation for GEN001
            violation = LintViolation(
                rule_id="GEN001",
                rule_name="DuplicatePrefix",
                severity=RuleSeverity.ERROR,
                object_type="file",
                object_name="01_foo.sql",
                message="Multiple files with prefix '01'",
                file_path=str(schema_dir / "01_foo.sql"),
                line_number=1,
            )
            mock_tree_report = LintReport(errors=[violation], warnings=[], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Mock schema lint to return clean
            mock_schema_report = LintReport(errors=[], warnings=[], info=[])
            mock_linter.lint.return_value = mock_schema_report

            # Run command without --check (should include all, including tree)
            result = runner.invoke(app, ["lint-unified", "--schema-dir", str(schema_dir)])

            # Should fail due to tree violation
            assert result.exit_code == 1
            assert "GEN001" in result.stdout

    def test_lint_unified_check_schema_does_not_run_tree(self, tmp_path):
        """Should NOT run tree checks when --check schema is specified."""
        # Create temp dir with GEN001 violation
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_foo.sql").write_text("CREATE TABLE foo (id INT);")
        (schema_dir / "01_bar.sql").write_text("CREATE TABLE bar (id INT);")

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock schema lint to return clean
            mock_schema_report = LintReport(errors=[], warnings=[], info=[])
            mock_linter.lint.return_value = mock_schema_report

            # Run command with --check schema only
            result = runner.invoke(app, ["lint-unified", "--check", "schema", "--schema-dir", str(schema_dir)])

            # Should succeed (no tree checks run)
            assert result.exit_code == 0
            # Verify lint_tree was NOT called
            mock_linter.lint_tree.assert_not_called()

    def test_lint_unified_tree_with_overrides_dir(self, tmp_path):
        """Should pass --overrides-dir to lint_tree."""
        # Create temp directories
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE test (id INT);")

        overrides_dir = tmp_path / "overrides"
        overrides_dir.mkdir()

        with patch("confiture.core.linting.SchemaLinter") as mock_linter_class:
            mock_linter = MagicMock()
            mock_linter_class.return_value = mock_linter

            # Mock clean report
            mock_tree_report = LintReport(errors=[], warnings=[], info=[])
            mock_linter.lint_tree.return_value = mock_tree_report

            # Run command with --overrides-dir
            result = runner.invoke(
                app,
                ["lint-unified", "--check", "tree", "--overrides-dir", str(overrides_dir), "--schema-dir", str(schema_dir)]
            )

            # Should succeed (exit code 0, no crash)
            assert result.exit_code == 0
            # Verify lint_tree was called with overrides_dir
            mock_linter.lint_tree.assert_called_once_with(
                schema_dir=schema_dir,
                overrides_dir=overrides_dir,
            )
