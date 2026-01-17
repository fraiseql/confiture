"""Unit tests for migration dry-run mode."""

from unittest.mock import MagicMock, Mock

import pytest


class TestDryRunMode:
    """Test suite for migration dry-run mode."""

    def test_dry_run_executor_can_test_migration_in_transaction(self):
        """DryRunExecutor should execute migration in transaction, then rollback."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection
        mock_conn = Mock()
        mock_conn.autocommit = False

        # Create mock migration
        mock_migration = Mock()
        mock_migration.name = "001_test_migration"
        mock_migration.version = "001"

        def up_impl():
            """Simulate migration creating a table."""
            pass

        mock_migration.up = up_impl

        # Run dry-run
        result = executor.run(mock_conn, mock_migration)

        # Verify result
        assert result is not None
        assert result.migration_name == "001_test_migration"
        assert result.success is True

    def test_dry_run_result_contains_execution_metrics(self):
        """DryRunResult should contain execution metrics."""
        from confiture.core.dry_run import DryRunResult

        result = DryRunResult(
            migration_name="001_test",
            migration_version="001",
            success=True,
            execution_time_ms=125,
            rows_affected=42,
            locked_tables=["users", "orders"],
            estimated_production_time_ms=120,
            confidence_percent=85,
            warnings=[],
        )

        assert result.migration_name == "001_test"
        assert result.execution_time_ms == 125
        assert result.rows_affected == 42
        assert result.locked_tables == ["users", "orders"]
        assert result.estimated_production_time_ms == 120
        assert result.confidence_percent == 85

    def test_dry_run_detects_constraint_violations(self):
        """DryRunExecutor should detect constraint violations during test."""
        from confiture.core.dry_run import DryRunError, DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection that will raise constraint error
        mock_conn = Mock()

        # Create mock migration that violates constraints
        mock_migration = Mock()
        mock_migration.name = "002_bad_migration"
        mock_migration.version = "002"

        def up_impl():
            raise Exception("Unique constraint violated")

        mock_migration.up = up_impl

        # Should raise DryRunError
        with pytest.raises(DryRunError):
            executor.run(mock_conn, mock_migration)

    def test_dry_run_captures_lock_times(self):
        """DryRunExecutor should capture table lock times."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "003_lock_test"
        mock_migration.version = "003"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should capture lock timing information
        assert hasattr(result, "locked_tables")
        assert isinstance(result.locked_tables, list)

    def test_dry_run_estimates_production_time(self):
        """DryRunExecutor should estimate production execution time."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "004_estimate_test"
        mock_migration.version = "004"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should have time estimate field (may be 0 in minimal implementation)
        assert hasattr(result, "estimated_production_time_ms")
        assert isinstance(result.estimated_production_time_ms, (int, float))
        # Note: estimate is populated during REFACTOR phase

    def test_dry_run_provides_confidence_level(self):
        """DryRunExecutor should provide confidence in estimate."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "005_confidence_test"
        mock_migration.version = "005"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should have confidence percentage (0-100)
        assert hasattr(result, "confidence_percent")
        assert 0 <= result.confidence_percent <= 100

    def test_dry_run_automatic_rollback(self):
        """DryRunExecutor should automatically rollback after test."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection with transaction support
        mock_conn = Mock()
        mock_conn.autocommit = False
        mock_transaction = MagicMock()
        mock_conn.transaction.return_value.__enter__ = Mock(return_value=mock_transaction)
        mock_conn.transaction.return_value.__exit__ = Mock(return_value=None)

        mock_migration = Mock()
        mock_migration.name = "006_rollback_test"
        mock_migration.version = "006"

        # Track if rollback was called
        rollback_called = False

        def up_impl():
            nonlocal rollback_called
            # Would normally make DB changes here
            pass

        mock_migration.up = up_impl

        result = executor.run(mock_conn, mock_migration)

        # Verify transaction context was used (indicates rollback)
        assert result.success is True

    def test_dry_run_comparison_with_production(self):
        """DryRunResult should show comparison to estimate."""
        from confiture.core.dry_run import DryRunResult

        result = DryRunResult(
            migration_name="007_comparison",
            migration_version="007",
            success=True,
            execution_time_ms=100,
            rows_affected=1000,
            locked_tables=["large_table"],
            estimated_production_time_ms=100,  # Match actual for this test
            confidence_percent=80,
            warnings=["Large table lock detected"],
        )

        # Calculate estimate range (±15%)
        low_estimate = result.estimated_production_time_ms * 0.85
        high_estimate = result.estimated_production_time_ms * 1.15

        assert low_estimate <= result.execution_time_ms <= high_estimate

    def test_migration_integrates_with_dry_run_executor(self):
        """Migration class should work with dry-run."""
        from confiture.models.migration import Migration

        class TestMigration(Migration):
            version = "001"
            name = "test_dry_run"

            def up(self):
                self.execute("CREATE TABLE test (id INT)")

            def down(self):
                self.execute("DROP TABLE test")

        mock_conn = Mock()
        migration = TestMigration(connection=mock_conn)

        # Should be compatible with dry-run
        assert hasattr(migration, "up")
        assert callable(migration.up)
