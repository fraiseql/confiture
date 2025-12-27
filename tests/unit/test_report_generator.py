"""Tests for DryRunReportGenerator report formatting."""

from datetime import datetime

import pytest

from confiture.core.migration.dry_run.dry_run_mode import (
    DryRunAnalysis,
    DryRunReport,
)
from confiture.core.migration.dry_run.estimator import CostEstimate
from confiture.core.migration.dry_run.models import (
    ConcurrencyAnalysis,
    StatementClassification,
)
from confiture.core.migration.dry_run.report import DryRunReportGenerator


class TestDryRunReportGenerator:
    """Tests for DryRunReportGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create generator instance."""
        return DryRunReportGenerator(use_colors=False, verbose=False)

    @pytest.fixture
    def sample_report(self):
        """Create sample report for testing."""
        report = DryRunReport(
            migration_id="test_migration_001",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_execution_time_ms=100.0,
            statements_analyzed=3,
        )

        # Add safe statement
        analysis1 = DryRunAnalysis(
            statement="SELECT COUNT(*) FROM users",
            classification=StatementClassification.SAFE,
            execution_time_ms=10.0,
            success=True,
        )
        report.add_analysis(analysis1)

        # Add unsafe statement
        analysis2 = DryRunAnalysis(
            statement="DELETE FROM users WHERE id = 1",
            classification=StatementClassification.UNSAFE,
            execution_time_ms=50.0,
            success=True,
        )
        analysis2.cost = CostEstimate(
            statement=analysis2.statement,
            estimated_duration_ms=500,
            estimated_disk_usage_mb=0.0,
            estimated_cpu_percent=20.0,
            recommended_batch_size=1000,
        )
        report.add_analysis(analysis2)

        # Add warning statement
        analysis3 = DryRunAnalysis(
            statement="ALTER TABLE users ADD COLUMN bio TEXT",
            classification=StatementClassification.WARNING,
            execution_time_ms=100.0,
            success=True,
        )
        analysis3.cost = CostEstimate(
            statement=analysis3.statement,
            estimated_duration_ms=1000,
            estimated_disk_usage_mb=5.0,
            estimated_cpu_percent=50.0,
            recommended_batch_size=100,
        )
        analysis3.concurrency = ConcurrencyAnalysis(
            statement=analysis3.statement,
            risk_level="high",
            tables_locked=["users"],
            lock_duration_estimate_ms=1000,
        )
        report.add_analysis(analysis3)

        return report

    def test_generate_text_report(self, generator, sample_report):
        """Test generating plain text report."""
        text = generator.generate_text_report(sample_report)

        assert isinstance(text, str)
        assert len(text) > 0
        assert "DRY-RUN MIGRATION ANALYSIS REPORT" in text
        assert "SUMMARY" in text

    def test_text_report_includes_warnings(self, generator, sample_report):
        """Test text report includes warning section if warnings present."""
        # Add warning to trigger warning section
        sample_report.warnings.append("⚠️  Test warning")

        text_with_warnings = generator.generate_text_report(sample_report)

        assert "WARNINGS" in text_with_warnings
        assert "Test warning" in text_with_warnings

    def test_text_report_includes_statement_details(self, generator, sample_report):
        """Test verbose text report includes statement details."""
        verbose_gen = DryRunReportGenerator(use_colors=False, verbose=True)
        text = verbose_gen.generate_text_report(sample_report)

        assert "STATEMENT DETAILS" in text
        assert "SELECT COUNT" in text

    def test_generate_json_report(self, generator, sample_report):
        """Test generating JSON report."""
        json_data = generator.generate_json_report(sample_report)

        assert isinstance(json_data, dict)
        assert "migration_id" in json_data
        assert "statements_analyzed" in json_data
        assert "summary" in json_data
        assert "analyses" in json_data
        assert len(json_data["analyses"]) == 3

    def test_json_report_summary(self, generator, sample_report):
        """Test JSON report includes summary data."""
        json_data = generator.generate_json_report(sample_report)

        assert json_data["summary"]["unsafe_count"] == 1
        assert json_data["summary"]["has_unsafe_statements"] is True

    def test_json_report_analyses(self, generator, sample_report):
        """Test JSON report includes statement analyses."""
        json_data = generator.generate_json_report(sample_report)

        analyses = json_data["analyses"]
        assert analyses[0]["classification"] == "safe"
        assert analyses[1]["classification"] == "unsafe"
        assert analyses[2]["classification"] == "warning"

    def test_summary_line_safe(self, generator, sample_report):
        """Test generating summary line for safe migration."""
        # Clear unsafe statements and update count
        sample_report.analyses = [sample_report.analyses[0]]
        sample_report.statements_analyzed = 1

        summary = generator.generate_summary_line(sample_report)

        assert "✓ SAFE" in summary
        assert "1 statements" in summary

    def test_summary_line_unsafe(self, generator, sample_report):
        """Test generating summary line for unsafe migration."""
        summary = generator.generate_summary_line(sample_report)

        assert "⚠️  UNSAFE" in summary or "UNSAFE" in summary
        assert "3 statements" in summary

    def test_summary_line_includes_costs(self, generator, sample_report):
        """Test summary line includes cost estimates."""
        summary = generator.generate_summary_line(sample_report)

        assert "ms" in summary  # Time estimate
        assert "MB" in summary  # Disk estimate

    def test_get_classification_icon(self, generator):
        """Test getting icon for classifications."""
        safe_icon = generator._get_classification_icon(StatementClassification.SAFE)
        warning_icon = generator._get_classification_icon(
            StatementClassification.WARNING
        )
        unsafe_icon = generator._get_classification_icon(StatementClassification.UNSAFE)

        assert safe_icon == "✓"
        assert warning_icon == "⚠️"
        assert unsafe_icon == "❌"

    def test_text_report_recommendations(self, generator, sample_report):
        """Test text report includes recommendations."""
        text = generator.generate_text_report(sample_report)

        assert "RECOMMENDATIONS" in text
        # Should have recommendations for unsafe statements and high risk
        assert "UNSAFE" in text or "unsafe" in text.lower()
