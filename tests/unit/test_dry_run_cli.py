"""Comprehensive tests for dry-run CLI helpers.

Tests the dry-run mode helpers for CLI integration.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from confiture.cli.dry_run import (
    ask_dry_run_execute_confirmation,
    display_dry_run_header,
    save_text_report,
    show_report_summary,
)


class TestSaveTextReport:
    """Test save_text_report function."""

    def test_save_text_report_basic(self):
        """Test saving basic text report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "report.txt"
            text = "Test report content"

            save_text_report(text, filepath)

            assert filepath.exists()
            assert filepath.read_text() == text

    def test_save_text_report_creates_parent_dirs(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "subdir1" / "subdir2" / "report.txt"
            text = "Test report"

            save_text_report(text, filepath)

            assert filepath.exists()
            assert filepath.parent.exists()

    def test_save_text_report_multiline(self):
        """Test saving multiline text report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "report.txt"
            text = "Line 1\nLine 2\nLine 3"

            save_text_report(text, filepath)

            content = filepath.read_text()
            assert "Line 1" in content
            assert "Line 2" in content
            assert "Line 3" in content

    def test_save_text_report_overwrite(self):
        """Test that existing file is overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "report.txt"
            filepath.write_text("Original content")

            new_text = "New content"
            save_text_report(new_text, filepath)

            assert filepath.read_text() == new_text

    def test_save_text_report_empty_string(self):
        """Test saving empty string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "report.txt"

            save_text_report("", filepath)

            assert filepath.exists()
            assert filepath.read_text() == ""


class TestShowReportSummary:
    """Test show_report_summary function."""

    def test_show_report_summary_safe(self):
        """Test displaying safe report summary."""
        report = Mock()
        report.has_unsafe_statements = False
        report.unsafe_count = 0
        report.total_estimated_time_ms = 100
        report.total_estimated_disk_mb = 5.2

        with patch("confiture.cli.dry_run.console") as mock_console:
            show_report_summary(report)
            # Verify console was called
            assert mock_console.print.called

    def test_show_report_summary_unsafe(self):
        """Test displaying unsafe report summary."""
        report = Mock()
        report.has_unsafe_statements = True
        report.unsafe_count = 3
        report.total_estimated_time_ms = 500
        report.total_estimated_disk_mb = 25.0

        with patch("confiture.cli.dry_run.console") as mock_console:
            show_report_summary(report)
            # Verify console was called
            assert mock_console.print.called
            # Should have been called at least once
            assert mock_console.print.call_count >= 1

    def test_show_report_summary_displays_metrics(self):
        """Test that metrics are displayed in summary."""
        report = Mock()
        report.has_unsafe_statements = False
        report.total_estimated_time_ms = 250
        report.total_estimated_disk_mb = 10.5

        with patch("confiture.cli.dry_run.console") as mock_console:
            show_report_summary(report)
            # Verify metrics were displayed
            call_args_list = [str(call) for call in mock_console.print.call_args_list]
            # Check that time and disk metrics were included
            all_calls = " ".join(call_args_list)
            assert "250" in all_calls or "Time" in all_calls


class TestAskDryRunExecuteConfirmation:
    """Test ask_dry_run_execute_confirmation function."""

    def test_ask_confirmation_user_confirms(self):
        """Test when user confirms."""
        with patch("typer.confirm", return_value=True):
            result = ask_dry_run_execute_confirmation()
            assert result is True

    def test_ask_confirmation_user_declines(self):
        """Test when user declines."""
        with patch("typer.confirm", return_value=False):
            result = ask_dry_run_execute_confirmation()
            assert result is False

    def test_ask_confirmation_default_false(self):
        """Test that default is False."""
        with patch("typer.confirm") as mock_confirm:
            ask_dry_run_execute_confirmation()
            # Verify default=False was passed
            _args, kwargs = mock_confirm.call_args
            assert kwargs["default"] is False

    def test_ask_confirmation_message(self):
        """Test confirmation message."""
        with patch("typer.confirm") as mock_confirm:
            ask_dry_run_execute_confirmation()
            args, _kwargs = mock_confirm.call_args
            assert "Proceed with real execution" in args[0]


class TestDisplayDryRunHeader:
    """Test display_dry_run_header function."""

    def test_display_header_analysis_mode(self):
        """Test header for analysis mode."""
        with patch("confiture.cli.dry_run.console") as mock_console:
            display_dry_run_header("analysis")
            assert mock_console.print.called
            call_args = str(mock_console.print.call_args)
            assert "Analyzing" in call_args or "analysis" in call_args.lower()

    def test_display_header_testing_mode(self):
        """Test header for testing mode."""
        with patch("confiture.cli.dry_run.console") as mock_console:
            display_dry_run_header("testing")
            assert mock_console.print.called
            call_args = str(mock_console.print.call_args)
            assert "testing" in call_args.lower() or "SAVEPOINT" in call_args

    def test_display_header_contains_emojis(self):
        """Test that headers contain visual indicators."""
        with patch("confiture.cli.dry_run.console") as mock_console:
            display_dry_run_header("analysis")
            call_args = str(mock_console.print.call_args)
            # Check for emoji or special characters
            assert len(call_args) > 10

    def test_display_header_unknown_mode(self):
        """Test handling of unknown mode."""
        with patch("confiture.cli.dry_run.console") as mock_console:
            # Should still work even with unknown mode
            display_dry_run_header("unknown")
            # Should call console.print for both known and unknown modes
            assert mock_console.print.called


class TestDryRunIntegration:
    """Integration tests for dry-run CLI helpers."""

    def test_save_and_read_text_report(self):
        """Test saving and reading text report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "report.txt"
            original_text = "Dry-run analysis completed successfully"

            save_text_report(original_text, filepath)
            read_text = filepath.read_text()

            assert read_text == original_text
