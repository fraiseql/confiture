"""Tests for DryRunResult report formatting."""

from confiture.core.dry_run import DryRunResult


class TestDryRunResult:
    """Tests for DryRunResult class."""

    def test_dry_run_result_creation(self):
        """Test creating a DryRunResult instance."""
        result = DryRunResult(
            migration_name="test_migration",
            migration_version="001",
            success=True,
            execution_time_ms=100,
            rows_affected=10,
            locked_tables=["users"],
            estimated_production_time_ms=500,
        )

        assert result.migration_name == "test_migration"
        assert result.migration_version == "001"
        assert result.success is True
        assert result.execution_time_ms == 100
        assert result.rows_affected == 10
        assert result.locked_tables == ["users"]
        assert result.estimated_production_time_ms == 500

    def test_dry_run_result_defaults(self):
        """Test DryRunResult with default values."""
        result = DryRunResult(
            migration_name="test",
            migration_version="001",
            success=False,
        )

        assert result.execution_time_ms == 0
        assert result.rows_affected == 0
        assert result.locked_tables == []
        assert result.estimated_production_time_ms == 0
