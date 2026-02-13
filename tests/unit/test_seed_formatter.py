"""Tests for seed apply command output formatter.

Tests JSON, CSV, and text formatting for seed results.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from confiture.cli.formatters.seed_formatter import format_apply_result
from confiture.core.seed_applier import ApplyResult


class TestSeedApplyFormatter:
    """Tests for seed apply result formatter."""

    def test_format_apply_json_to_console(self):
        """Test formatting apply result as JSON to console."""
        result = ApplyResult(
            total=5,
            succeeded=5,
            failed=0,
            failed_files=[],
        )

        console = Console()

        # Should not raise
        format_apply_result(result, "json", None, console)

    def test_format_apply_json_to_file(self):
        """Test formatting apply result as JSON to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "seeds.json"
            result = ApplyResult(
                total=10,
                succeeded=9,
                failed=1,
                failed_files=["05_data.sql"],
            )

            console = Console()
            format_apply_result(result, "json", output_file, console)

            assert output_file.exists()
            data = json.loads(output_file.read_text())

            assert data["total"] == 10
            assert data["succeeded"] == 9
            assert data["failed"] == 1
            assert "05_data.sql" in data["failed_files"]
            assert data["success"] is False

    def test_format_apply_csv_to_file(self):
        """Test formatting apply result as CSV to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "seeds.csv"
            result = ApplyResult(
                total=5,
                succeeded=5,
                failed=0,
                failed_files=[],
            )

            console = Console()
            format_apply_result(result, "csv", output_file, console)

            assert output_file.exists()
            content = output_file.read_text()

            # Should have headers
            assert "metric,value" in content
            # Should have data
            assert "5" in content  # total and succeeded

    def test_format_apply_text_success(self):
        """Test formatting successful apply result as text."""
        result = ApplyResult(
            total=3,
            succeeded=3,
            failed=0,
            failed_files=[],
        )

        console = Console()

        # Should not raise
        format_apply_result(result, "text", None, console)

    def test_format_apply_text_with_failures(self):
        """Test formatting apply result with failures as text."""
        result = ApplyResult(
            total=5,
            succeeded=4,
            failed=1,
            failed_files=["03_users.sql"],
        )

        console = Console()

        # Should not raise
        format_apply_result(result, "text", None, console)

    def test_format_apply_json_all_failed(self):
        """Test formatting apply result where all files failed."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "seeds.json"
            result = ApplyResult(
                total=2,
                succeeded=0,
                failed=2,
                failed_files=["01_tables.sql", "02_data.sql"],
            )

            console = Console()
            format_apply_result(result, "json", output_file, console)

            data = json.loads(output_file.read_text())
            assert data["success"] is False
            assert data["failed"] == 2
            assert len(data["failed_files"]) == 2

    def test_format_apply_text_no_seeds(self):
        """Test formatting apply result with no seeds."""
        result = ApplyResult(
            total=0,
            succeeded=0,
            failed=0,
            failed_files=[],
        )

        console = Console()

        # Should not raise
        format_apply_result(result, "text", None, console)
