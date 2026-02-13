"""Tests for migrate command output formatter.

Tests JSON, CSV, and text formatting for migration results.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from confiture.cli.formatters.migrate_formatter import format_migrate_up_result
from confiture.models.results import MigrateUpResult, MigrationApplied


class TestMigrateUpFormatter:
    """Tests for migrate up result formatter."""

    def test_format_migrate_up_json_to_console(self):
        """Test formatting migrate up result as JSON to console."""
        migrations = [
            MigrationApplied("001", "initial", 100, 50),
            MigrationApplied("002", "add_users", 200, 0),
        ]
        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_execution_time_ms=300,
        )

        console = Console()

        # Should not raise
        format_migrate_up_result(result, "json", None, console)

    def test_format_migrate_up_json_to_file(self):
        """Test formatting migrate up result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "migrations.json"
            migrations = [
                MigrationApplied("001", "initial", 100),
                MigrationApplied("002", "add_users", 200),
            ]
            result = MigrateUpResult(
                success=True,
                migrations_applied=migrations,
                total_execution_time_ms=300,
                checksums_verified=True,
            )

            console = Console()
            format_migrate_up_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is True
            assert data["count"] == 2
            assert len(data["migrations_applied"]) == 2
            assert data["migrations_applied"][0]["version"] == "001"
            assert data["total_execution_time_ms"] == 300

    def test_format_migrate_up_csv_to_file(self):
        """Test formatting migrate up result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "migrations.csv"
            migrations = [
                MigrationApplied("001", "initial", 100, 50),
                MigrationApplied("002", "add_users", 200, 0),
            ]
            result = MigrateUpResult(
                success=True,
                migrations_applied=migrations,
                total_execution_time_ms=300,
            )

            console = Console()
            format_migrate_up_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            # Should have headers
            assert "version,name" in content
            # Should have migration data
            assert "001" in content
            assert "initial" in content

    def test_format_migrate_up_text_to_console(self):
        """Test formatting migrate up result as text to console."""
        migrations = [
            MigrationApplied("001", "initial", 100),
        ]
        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_execution_time_ms=100,
        )

        console = Console()

        # Should not raise
        format_migrate_up_result(result, "text", None, console)

    def test_format_migrate_up_failure_json(self):
        """Test formatting failed migrate up result as JSON."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "migrations.json"
            result = MigrateUpResult(
                success=False,
                migrations_applied=[],
                total_execution_time_ms=0,
                error="Lock timeout",
            )

            console = Console()
            format_migrate_up_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is False
            assert data["error"] == "Lock timeout"
            assert data["count"] == 0

    def test_format_migrate_up_empty_migrations(self):
        """Test formatting migrate up with no migrations applied."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
        )

        console = Console()

        # Should not raise
        format_migrate_up_result(result, "text", None, console)

    def test_format_migrate_up_with_warnings(self):
        """Test formatting migrate up with warnings."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "migrations.json"
            migrations = [
                MigrationApplied("001", "initial", 100),
            ]
            result = MigrateUpResult(
                success=True,
                migrations_applied=migrations,
                total_execution_time_ms=100,
                warnings=["Checksum mismatch for 002"],
            )

            console = Console()
            format_migrate_up_result(result, "json", output_file, console)

            data = json.loads(output_file.read_text())
            assert len(data["warnings"]) == 1
            assert "Checksum mismatch" in data["warnings"][0]

    def test_format_migrate_up_dry_run(self):
        """Test formatting migrate up in dry-run mode."""
        migrations = [
            MigrationApplied("001", "initial", 50),
        ]
        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_execution_time_ms=50,
            dry_run=True,
        )

        console = Console()

        # Should not raise
        format_migrate_up_result(result, "text", None, console)
