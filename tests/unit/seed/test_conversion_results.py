"""Tests for seed conversion result models.

Phase 11, Cycle 1: Add ConversionResult and ConversionReport models.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.models.results import ConversionReport, ConversionResult


class TestConversionResult:
    """Test ConversionResult model for seed file conversion."""

    def test_conversion_result_success_minimal(self) -> None:
        """Test successful conversion result with minimal fields."""
        result = ConversionResult(
            file_path="test.sql",
            success=True,
            copy_format="COPY users (id) FROM stdin;\n1\n\\.\n",
            rows_converted=1,
        )

        assert result.file_path == "test.sql"
        assert result.success is True
        assert result.copy_format == "COPY users (id) FROM stdin;\n1\n\\.\n"
        assert result.rows_converted == 1
        assert result.reason is None

    def test_conversion_result_failure(self) -> None:
        """Test failed conversion result with reason."""
        reason = "Function call in VALUES: NOW()"
        result = ConversionResult(
            file_path="users.sql",
            success=False,
            reason=reason,
        )

        assert result.file_path == "users.sql"
        assert result.success is False
        assert result.reason == reason
        assert result.copy_format is None
        assert result.rows_converted is None

    def test_conversion_result_to_dict_success(self) -> None:
        """Test serialization of successful result to dict."""
        result = ConversionResult(
            file_path="test.sql",
            success=True,
            copy_format="COPY users (id) FROM stdin;\n1\n\\.\n",
            rows_converted=1,
        )

        result_dict = result.to_dict()

        assert result_dict["file_path"] == "test.sql"
        assert result_dict["success"] is True
        assert result_dict["copy_format"] == "COPY users (id) FROM stdin;\n1\n\\.\n"
        assert result_dict["rows_converted"] == 1
        assert result_dict["reason"] is None

    def test_conversion_result_to_dict_failure(self) -> None:
        """Test serialization of failed result to dict."""
        reason = "ON CONFLICT clause detected"
        result = ConversionResult(
            file_path="users.sql",
            success=False,
            reason=reason,
        )

        result_dict = result.to_dict()

        assert result_dict["file_path"] == "users.sql"
        assert result_dict["success"] is False
        assert result_dict["reason"] == reason
        assert result_dict["copy_format"] is None
        assert result_dict["rows_converted"] is None


class TestConversionReport:
    """Test ConversionReport model for batch conversion results."""

    def test_conversion_report_single_success(self) -> None:
        """Test report with single successful conversion."""
        result1 = ConversionResult(
            file_path="users.sql",
            success=True,
            copy_format="COPY users (id) FROM stdin;\n1\n\\.\n",
            rows_converted=1,
        )

        report = ConversionReport(
            total_files=1,
            successful=1,
            failed=0,
            results=[result1],
        )

        assert report.total_files == 1
        assert report.successful == 1
        assert report.failed == 0
        assert len(report.results) == 1
        assert report.success_rate == 100.0

    def test_conversion_report_mixed(self) -> None:
        """Test report with mix of successful and failed conversions."""
        result1 = ConversionResult(
            file_path="simple.sql",
            success=True,
            copy_format="COPY users (id) FROM stdin;\n1\n\\.\n",
            rows_converted=1,
        )
        result2 = ConversionResult(
            file_path="with_now.sql",
            success=False,
            reason="Function call in VALUES: NOW()",
        )

        report = ConversionReport(
            total_files=2,
            successful=1,
            failed=1,
            results=[result1, result2],
        )

        assert report.total_files == 2
        assert report.successful == 1
        assert report.failed == 1
        assert len(report.results) == 2
        assert report.success_rate == 50.0

    def test_conversion_report_all_failed(self) -> None:
        """Test report with all failed conversions."""
        result1 = ConversionResult(
            file_path="complex1.sql",
            success=False,
            reason="CTE detected",
        )
        result2 = ConversionResult(
            file_path="complex2.sql",
            success=False,
            reason="Subquery in VALUES",
        )

        report = ConversionReport(
            total_files=2,
            successful=0,
            failed=2,
            results=[result1, result2],
        )

        assert report.total_files == 2
        assert report.successful == 0
        assert report.failed == 2
        assert report.success_rate == 0.0

    def test_conversion_report_to_dict(self) -> None:
        """Test serialization of report to dict."""
        result1 = ConversionResult(
            file_path="simple.sql",
            success=True,
            copy_format="COPY users (id) FROM stdin;\n1\n\\.\n",
            rows_converted=1,
        )
        result2 = ConversionResult(
            file_path="with_now.sql",
            success=False,
            reason="Function call in VALUES: NOW()",
        )

        report = ConversionReport(
            total_files=2,
            successful=1,
            failed=1,
            results=[result1, result2],
        )

        report_dict = report.to_dict()

        assert report_dict["total_files"] == 2
        assert report_dict["successful"] == 1
        assert report_dict["failed"] == 1
        assert report_dict["success_rate"] == 50.0
        assert len(report_dict["results"]) == 2
        assert report_dict["results"][0]["success"] is True
        assert report_dict["results"][1]["success"] is False

    def test_conversion_report_success_rate_zero(self) -> None:
        """Test success rate calculation when no files."""
        report = ConversionReport(
            total_files=0,
            successful=0,
            failed=0,
            results=[],
        )

        assert report.success_rate == 0.0
