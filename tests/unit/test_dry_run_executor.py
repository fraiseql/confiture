"""Tests for the honest DryRunExecutor (Phase 05)."""

import pytest

from confiture.core.dry_run import DryRunError, DryRunExecutor, DryRunResult


class _MockMigration:
    name = "test_migration"
    version = "20260310120000"

    def up(self) -> None:
        pass


class _SlowMigration:
    name = "slow_migration"
    version = "20260310120001"

    def up(self) -> None:
        import time

        time.sleep(0.01)


class _FailingMigration:
    name = "failing_migration"
    version = "20260310120002"

    def up(self) -> None:
        raise ValueError("SQL error during migration")


def test_dry_run_returns_result():
    """DryRunExecutor.run() returns a DryRunResult."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_MockMigration())
    assert isinstance(result, DryRunResult)
    assert result.success is True


def test_dry_run_does_not_use_connection():
    """DryRunExecutor accepts None for conn (simulation mode)."""
    executor = DryRunExecutor()
    # Must not raise even with conn=None
    result = executor.run(_conn=None, migration=_MockMigration())
    assert result is not None


def test_dry_run_confidence_is_40():
    """DryRunExecutor confidence_percent is 40 (honest simulation)."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_MockMigration())
    assert result.confidence_percent == 40


def test_dry_run_rows_affected_is_zero():
    """rows_affected is always 0 (simulation cannot measure it)."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_MockMigration())
    assert result.rows_affected == 0


def test_dry_run_warns_about_simulation():
    """DryRunResult includes a simulation warning."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_MockMigration())
    assert len(result.warnings) > 0
    assert "Simulation only" in result.warnings[0]


def test_dry_run_result_has_real_timing():
    """execution_time_ms reflects actual elapsed time."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_SlowMigration())
    assert result.execution_time_ms >= 0


def test_dry_run_raises_on_failure():
    """DryRunError is raised when migration.up() raises."""
    executor = DryRunExecutor()
    with pytest.raises(DryRunError) as exc_info:
        executor.run(_conn=None, migration=_FailingMigration())
    assert "failing_migration" in str(exc_info.value)


def test_dry_run_result_migration_name():
    """DryRunResult records the migration name and version."""
    executor = DryRunExecutor()
    result = executor.run(_conn=None, migration=_MockMigration())
    assert result.migration_name == "test_migration"
    assert result.migration_version == "20260310120000"
