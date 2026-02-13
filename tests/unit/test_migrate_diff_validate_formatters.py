"""Tests for migrate diff and validate formatters."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from confiture.cli.formatters.migrate_formatter import (
    format_migrate_diff_result,
    format_migrate_validate_result,
)
from confiture.models.results import (
    MigrateDiffResult,
    MigrateValidateResult,
    SchemaChange,
)
from rich.console import Console


class TestMigrateDiffFormatter:
    """Tests for migrate diff formatter."""

    def test_format_diff_json_to_file(self):
        """Test formatting diff result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "diff.json"
            changes = [
                SchemaChange("ADD_TABLE", "users table"),
                SchemaChange("ADD_COLUMN", "email column to users"),
            ]
            result = MigrateDiffResult(
                success=True,
                has_changes=True,
                changes=changes,
                migration_generated=True,
                migration_file="003_add_email.py",
            )

            console = Console()
            format_migrate_diff_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is True
            assert data["has_changes"] is True
            assert data["change_count"] == 2
            assert data["migration_generated"] is True
            assert data["migration_file"] == "003_add_email.py"

    def test_format_diff_csv_to_file(self):
        """Test formatting diff result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "diff.csv"
            changes = [
                SchemaChange("ADD_TABLE", "users table"),
                SchemaChange("MODIFY_COLUMN", "user_id type change"),
            ]
            result = MigrateDiffResult(
                success=True,
                has_changes=True,
                changes=changes,
            )

            console = Console()
            format_migrate_diff_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            assert "type,details" in content
            assert "ADD_TABLE" in content
            assert "users table" in content

    def test_format_diff_text_no_changes(self):
        """Test formatting diff result with no changes."""
        result = MigrateDiffResult(
            success=True,
            has_changes=False,
        )

        console = Console()
        # Should not raise
        format_migrate_diff_result(result, "text", None, console)

    def test_format_diff_text_with_changes(self):
        """Test formatting diff result with changes."""
        changes = [
            SchemaChange("ADD_TABLE", "orders table"),
        ]
        result = MigrateDiffResult(
            success=True,
            has_changes=True,
            changes=changes,
            migration_generated=True,
            migration_file="004_add_orders.py",
        )

        console = Console()
        # Should not raise
        format_migrate_diff_result(result, "text", None, console)


class TestMigrateValidateFormatter:
    """Tests for migrate validate formatter."""

    def test_format_validate_json_to_file(self):
        """Test formatting validate result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "validate.json"
            result = MigrateValidateResult(
                success=True,
                orphaned_files=[],
                duplicate_versions={},
                fixed_files=[],
            )

            console = Console()
            format_migrate_validate_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is True
            assert data["orphaned_files_count"] == 0

    def test_format_validate_csv_to_file(self):
        """Test formatting validate result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "validate.csv"
            result = MigrateValidateResult(
                success=True,
                orphaned_files=["old_migration.sql"],
                duplicate_versions={"001": ["001_v1.py", "001_v2.py"]},
                fixed_files=["001_renamed.py"],
            )

            console = Console()
            format_migrate_validate_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            assert "check,count" in content
            assert "orphaned_files" in content

    def test_format_validate_text_success(self):
        """Test formatting successful validation."""
        result = MigrateValidateResult(
            success=True,
            orphaned_files=[],
            duplicate_versions={},
            fixed_files=[],
        )

        console = Console()
        # Should not raise
        format_migrate_validate_result(result, "text", None, console)

    def test_format_validate_text_with_issues(self):
        """Test formatting validation with issues."""
        result = MigrateValidateResult(
            success=False,
            orphaned_files=["old.sql"],
            duplicate_versions={"001": ["001_a.py", "001_b.py"]},
            fixed_files=[],
            error="Validation failed",
        )

        console = Console()
        # Should not raise
        format_migrate_validate_result(result, "text", None, console)
