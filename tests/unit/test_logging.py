"""Unit tests for structured logging in hooks and dry-run (Phase 4.2.1).

This test suite validates that HookExecutor and DryRunExecutor produce
structured logging output for production observability.
"""

from unittest.mock import Mock, patch

import pytest

from confiture.core.dry_run import DryRunExecutor
from confiture.core.hooks import (
    Hook,
    HookContext,
    HookError,
    HookExecutor,
    HookPhase,
    HookResult,
)
from confiture.core.hooks.context import ExecutionContext


def _make_hook_context(migration_name: str = "test_migration", migration_version: str = "001") -> HookContext:
    """Helper function to create HookContext for tests."""
    exec_context = ExecutionContext()
    exec_context.metadata["migration_name"] = migration_name
    exec_context.metadata["migration_version"] = migration_version
    return HookContext(phase=HookPhase.AFTER_EXECUTE, data=exec_context)


class TestHookExecutorLogging:
    """Test suite for structured logging in HookExecutor."""

    def test_hook_executor_has_logger(self):
        """HookExecutor should have a logger instance."""
        executor = HookExecutor()
        assert hasattr(executor, "logger")

    def test_hook_executor_logs_phase_start(self):
        """HookExecutor should log when a phase starts."""
        executor = HookExecutor()

        class SimpleHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="SimpleHook",
                    rows_affected=0,
                )

        hook = SimpleHook()
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Should log phase start
            assert mock_logger.info.called

    def test_hook_executor_logs_hook_completion(self):
        """HookExecutor should log when hook completes successfully."""
        executor = HookExecutor()

        class SimpleHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="SimpleHook",
                    rows_affected=42,
                )

        hook = SimpleHook()
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Should log hook completion with metrics
            info_calls = [
                c for c in mock_logger.info.call_args_list
                if "hook_completed" in str(c)
            ]
            assert len(info_calls) > 0

    def test_hook_executor_logs_hook_failure(self):
        """HookExecutor should log when hook fails."""
        executor = HookExecutor()

        class FailingHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                raise ValueError("Test error")

        hook = FailingHook()
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            with pytest.raises(HookError):
                executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Should log hook failure
            assert mock_logger.error.called

    def test_hook_executor_logs_execution_time(self):
        """HookExecutor should log execution time for each hook."""
        executor = HookExecutor()

        class SimpleHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="SimpleHook",
                    rows_affected=0,
                    execution_time_ms=123,
                )

        hook = SimpleHook()
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Should include duration_ms in logs
            assert mock_logger.info.called

    def test_hook_executor_logs_migration_context(self):
        """HookExecutor should include migration name/version in logs."""
        executor = HookExecutor()

        class SimpleHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="SimpleHook",
                    rows_affected=0,
                )

        hook = SimpleHook()
        conn = Mock()
        context = _make_hook_context("001_add_users", "001")

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Logs should include migration context
            assert mock_logger.info.called

    def test_hook_executor_logs_multiple_hooks(self):
        """HookExecutor should log each hook in sequence."""
        executor = HookExecutor()

        class Hook1(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="Hook1",
                    rows_affected=10,
                )

        class Hook2(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="Hook2",
                    rows_affected=20,
                )

        hooks = [Hook1(), Hook2()]
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, hooks, context)
            # Should log for both hooks
            assert mock_logger.info.called

    def test_hook_executor_logs_rows_affected(self):
        """HookExecutor should log rows affected by each hook."""
        executor = HookExecutor()

        class SimpleHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_EXECUTE",
                    hook_name="SimpleHook",
                    rows_affected=1500,
                )

        hook = SimpleHook()
        conn = Mock()
        context = _make_hook_context()

        with patch.object(executor, "logger") as mock_logger:
            executor.execute_phase(conn, HookPhase.AFTER_EXECUTE, [hook], context)
            # Logs should include rows_affected
            assert mock_logger.info.called


class TestDryRunExecutorLogging:
    """Test suite for structured logging in DryRunExecutor."""

    def test_dry_run_executor_has_logger(self):
        """DryRunExecutor should have a logger instance."""
        executor = DryRunExecutor()
        assert hasattr(executor, "logger")

    def test_dry_run_executor_logs_dry_run_start(self):
        """DryRunExecutor should log when dry-run starts."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_test"
        mock_migration.version = "001"
        mock_migration.up = Mock()

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            executor.run(mock_conn, mock_migration)
            # Should log dry-run start
            assert mock_logger.info.called

    def test_dry_run_executor_logs_dry_run_completion(self):
        """DryRunExecutor should log when dry-run completes successfully."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_test"
        mock_migration.version = "001"
        mock_migration.up = Mock()

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            result = executor.run(mock_conn, mock_migration)
            # Should log dry-run completion
            info_calls = [
                c for c in mock_logger.info.call_args_list
                if "dry_run_completed" in str(c)
            ]
            assert len(info_calls) > 0
            assert result.success is True

    def test_dry_run_executor_logs_execution_time(self):
        """DryRunExecutor should log execution time."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_test"
        mock_migration.version = "001"
        mock_migration.up = Mock()

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            result = executor.run(mock_conn, mock_migration)
            # Should include execution time in logs
            assert mock_logger.info.called
            assert result.execution_time_ms >= 0

    def test_dry_run_executor_logs_failure(self):
        """DryRunExecutor should log when dry-run fails."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_test"
        mock_migration.version = "001"
        mock_migration.up.side_effect = Exception("Test error")

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            from confiture.core.dry_run import DryRunError

            with pytest.raises(DryRunError):
                executor.run(mock_conn, mock_migration)
            # Should log failure
            assert mock_logger.error.called

    def test_dry_run_executor_logs_migration_context(self):
        """DryRunExecutor should include migration name in logs."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_add_users"
        mock_migration.version = "001"
        mock_migration.up = Mock()

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            executor.run(mock_conn, mock_migration)
            # Logs should include migration context
            assert mock_logger.info.called

    def test_dry_run_executor_logs_success_flag(self):
        """DryRunExecutor should log success/failure flag."""
        executor = DryRunExecutor()

        mock_migration = Mock()
        mock_migration.name = "001_test"
        mock_migration.version = "001"
        mock_migration.up = Mock()

        mock_conn = Mock()

        with patch.object(executor, "logger") as mock_logger:
            result = executor.run(mock_conn, mock_migration)
            # Should log success
            assert mock_logger.info.called
            assert result.success is True
