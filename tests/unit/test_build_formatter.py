"""Tests for build command output formatter.

Tests JSON, CSV, and text formatting for build results.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from confiture.cli.formatters.build_formatter import format_build_result
from confiture.models.results import BuildResult


class TestBuildFormatter:
    """Tests for build result formatter."""

    def test_format_build_result_json_to_console(self):
        """Test formatting build result as JSON to console."""
        result = BuildResult(
            success=True,
            files_processed=10,
            schema_size_bytes=5000,
            output_path="/tmp/schema.sql",
            hash="abc123",
            execution_time_ms=150,
        )

        console = Console()

        # Should not raise
        format_build_result(result, "json", None, console)

    def test_format_build_result_json_to_file(self):
        """Test formatting build result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "result.json"
            result = BuildResult(
                success=True,
                files_processed=10,
                schema_size_bytes=5000,
                output_path="/tmp/schema.sql",
                hash="abc123",
                execution_time_ms=150,
                seed_files_applied=3,
            )

            console = Console()
            format_build_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is True
            assert data["files_processed"] == 10
            assert data["schema_size_bytes"] == 5000
            assert data["hash"] == "abc123"
            assert data["execution_time_ms"] == 150
            assert data["seed_files_applied"] == 3

    def test_format_build_result_csv_to_file(self):
        """Test formatting build result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "result.csv"
            result = BuildResult(
                success=True,
                files_processed=10,
                schema_size_bytes=5000,
                output_path="/tmp/schema.sql",
                hash="abc123",
            )

            console = Console()
            format_build_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            # Should have metric,value header
            assert "metric,value" in content
            # Should have success row
            assert "True" in content or "true" in content
            # Should have file count
            assert "10" in content

    def test_format_build_result_text_to_console(self):
        """Test formatting build result as text to console."""
        result = BuildResult(
            success=True,
            files_processed=10,
            schema_size_bytes=5000,
            output_path="/tmp/schema.sql",
        )

        console = Console()

        # Should not raise
        format_build_result(result, "text", None, console)

    def test_format_build_result_failure_json(self):
        """Test formatting failed build result as JSON."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "result.json"
            result = BuildResult(
                success=False,
                files_processed=0,
                schema_size_bytes=0,
                output_path="",
                error="Connection failed",
            )

            console = Console()
            format_build_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["success"] is False
            assert data["error"] == "Connection failed"

    def test_format_build_result_with_warnings(self):
        """Test formatting build result with warnings."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "result.json"
            result = BuildResult(
                success=True,
                files_processed=10,
                schema_size_bytes=5000,
                output_path="/tmp/schema.sql",
                warnings=["Warning 1", "Warning 2"],
            )

            console = Console()
            format_build_result(result, "json", output_file, console)

            data = json.loads(output_file.read_text())
            assert len(data["warnings"]) == 2
            assert "Warning 1" in data["warnings"]
