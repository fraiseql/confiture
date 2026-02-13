"""Tests for migrate down command output formatter."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from confiture.cli.formatters.migrate_formatter import format_migrate_down_result
from confiture.models.results import MigrateDownResult, MigrationApplied
from rich.console import Console


class TestMigrateDownFormatter:
    """Tests for migrate down result formatter."""

    def test_format_migrate_down_json_to_file(self):
        """Test formatting migrate down result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "rollback.json"
            migrations = [
                MigrationApplied("003", "add_indexes", 150),
                MigrationApplied("002", "add_users", 200),
            ]
            result = MigrateDownResult(
                success=True,
                migrations_rolled_back=migrations,
                total_execution_time_ms=350,
            )

            console = Console()
            format_migrate_down_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is True
            assert data["count"] == 2
            assert len(data["migrations_rolled_back"]) == 2

    def test_format_migrate_down_csv_to_file(self):
        """Test formatting migrate down result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "rollback.csv"
            migrations = [
                MigrationApplied("003", "add_indexes", 150),
            ]
            result = MigrateDownResult(
                success=True,
                migrations_rolled_back=migrations,
                total_execution_time_ms=150,
            )

            console = Console()
            format_migrate_down_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            assert "version,name" in content
            assert "003" in content

    def test_format_migrate_down_text_to_console(self):
        """Test formatting migrate down result as text to console."""
        migrations = [
            MigrationApplied("002", "add_users", 200),
        ]
        result = MigrateDownResult(
            success=True,
            migrations_rolled_back=migrations,
            total_execution_time_ms=200,
        )

        console = Console()

        # Should not raise
        format_migrate_down_result(result, "text", None, console)

    def test_format_migrate_down_failure(self):
        """Test formatting failed migrate down result."""
        result = MigrateDownResult(
            success=False,
            migrations_rolled_back=[],
            total_execution_time_ms=0,
            error="Rollback failed",
        )

        console = Console()

        # Should not raise
        format_migrate_down_result(result, "text", None, console)
