"""Tests for DryRunResult report formatting."""

from confiture.core.dry_run import DryRunResult, StatementResult


class TestDryRunResult:
    """Tests for DryRunResult class."""

    def test_dry_run_result_creation(self):
        """Test creating a DryRunResult instance."""
        statements = [
            StatementResult(
                sql="ALTER TABLE users ADD COLUMN bio TEXT",
                success=True,
                execution_time_ms=100,
                rows_affected=10,
            ),
        ]

        result = DryRunResult(
            migration_name="test_migration",
            success=True,
            total_time_ms=100,
            confidence_pct=85,
            statements=statements,
        )

        assert result.migration_name == "test_migration"
        assert result.migration_version == "test_migration"  # compat property
        assert result.success is True
        assert result.execution_time_ms == 100  # compat property
        assert result.rows_affected == 10  # computed from statements
        assert result.confidence_percent == 85  # compat property

    def test_dry_run_result_defaults(self):
        """Test DryRunResult with default values."""
        result = DryRunResult(
            migration_name="test",
            success=False,
            total_time_ms=0,
            confidence_pct=40,
        )

        assert result.execution_time_ms == 0  # compat property
        assert result.rows_affected == 0  # no statements
        assert result.statements == []
        assert result.confidence_percent == 40  # compat property
