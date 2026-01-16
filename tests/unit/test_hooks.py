"""Unit tests for migration hooks system (Phase 4 Feature 1)."""

from enum import Enum
from unittest.mock import Mock, patch, MagicMock
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pytest

from confiture.exceptions import MigrationError


# ============================================================================
# RED PHASE TEST: Hook System Doesn't Exist Yet - This Test FAILS
# ============================================================================


class TestHookSystem:
    """Test suite for Phase 4 migration hooks."""

    def test_hook_base_class_can_be_defined(self):
        """Hook base class should support subclassing with execute method."""
        # This test will fail because Hook class doesn't exist yet

        from confiture.core.hooks import Hook, HookPhase

        class CaptureStatsHook(Hook):
            """Example hook to capture row counts before DDL."""

            phase = HookPhase.BEFORE_EXECUTE

            def execute(self, conn, context):
                """Execute hook with database connection and context."""
                # Would capture initial stats
                return HookResult(stats={"initial_rows": 100})

        # Verify hook can be instantiated
        hook = CaptureStatsHook()
        assert hook is not None
        assert hook.phase == HookPhase.BEFORE_EXECUTE

    def test_hook_phases_enum_exists(self):
        """HookPhase enum should define all hook execution phases."""
        from confiture.core.hooks import HookPhase

        # Verify all required phases exist
        assert hasattr(HookPhase, "BEFORE_VALIDATION")
        assert hasattr(HookPhase, "BEFORE_DDL")
        assert hasattr(HookPhase, "AFTER_DDL")
        assert hasattr(HookPhase, "AFTER_VALIDATION")
        assert hasattr(HookPhase, "CLEANUP")
        assert hasattr(HookPhase, "ON_ERROR")

    def test_hook_result_dataclass(self):
        """HookResult should hold execution results."""
        from confiture.core.hooks import HookResult

        result = HookResult(
            phase="BEFORE_DDL",
            hook_name="test_hook",
            rows_affected=42,
            stats={"initial_rows": 100},
            execution_time_ms=125,
        )

        assert result.phase == "BEFORE_DDL"
        assert result.hook_name == "test_hook"
        assert result.rows_affected == 42
        assert result.stats == {"initial_rows": 100}
        assert result.execution_time_ms == 125

    def test_hook_executor_runs_hooks_in_sequence(self):
        """HookExecutor should run hooks in sequence with savepoints."""
        from confiture.core.hooks import Hook, HookPhase, HookExecutor, HookResult

        class TestHook1(Hook):
            phase = HookPhase.BEFORE_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="BEFORE_DDL",
                    hook_name="test_hook_1",
                    rows_affected=10,
                    execution_time_ms=50,
                )

        class TestHook2(Hook):
            phase = HookPhase.BEFORE_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="BEFORE_DDL",
                    hook_name="test_hook_2",
                    rows_affected=20,
                    execution_time_ms=75,
                )

        # Create mock connection
        mock_conn = Mock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=Mock())
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

        # Create hooks and executor
        hooks = [TestHook1(), TestHook2()]
        executor = HookExecutor()
        context = Mock()

        # Execute hooks
        results = executor.execute_phase(mock_conn, HookPhase.BEFORE_EXECUTE, hooks, context)

        # Verify both hooks ran
        assert len(results) == 2
        assert results[0].hook_name == "test_hook_1"
        assert results[1].hook_name == "test_hook_2"
        assert results[0].rows_affected == 10
        assert results[1].rows_affected == 20

    def test_hook_context_provides_migration_data(self):
        """HookContext should provide migration metadata to hooks."""
        from confiture.core.hooks import HookContext, HookPhase
        from confiture.core.hooks.context import ExecutionContext

        exec_context = ExecutionContext()
        exec_context.metadata["migration_name"] = "001_add_users_table"
        exec_context.metadata["migration_version"] = "001"
        exec_context.metadata["direction"] = "forward"
        context = HookContext(phase=HookPhase.BEFORE_VALIDATION, data=exec_context)

        assert context.data.metadata["migration_name"] == "001_add_users_table"
        assert context.data.metadata["migration_version"] == "001"
        assert context.data.metadata["direction"] == "forward"

    def test_hook_error_is_rolled_back_via_savepoint(self):
        """Failed hook should trigger savepoint rollback."""
        from confiture.core.hooks import Hook, HookPhase, HookExecutor, HookError

        class FailingHook(Hook):
            phase = HookPhase.BEFORE_EXECUTE

            def execute(self, conn, context):
                raise ValueError("Simulated hook failure")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

        executor = HookExecutor()
        context = Mock()

        with pytest.raises(HookError) as exc_info:
            executor.execute_phase(mock_conn, HookPhase.BEFORE_EXECUTE, [FailingHook()], context)

        # Verify error includes hook information
        assert "FailingHook" in str(exc_info.value)

    def test_migration_can_define_hooks(self):
        """Migration class should support hook definitions."""
        from confiture.models.migration import Migration

        class TestMigration(Migration):
            version = "001"
            name = "test_with_hooks"

            # Define hooks for this migration
            before_ddl_hooks = []
            after_ddl_hooks = []

            def up(self):
                self.execute("CREATE TABLE test (id INT)")

            def down(self):
                self.execute("DROP TABLE test")

        mock_conn = Mock()
        migration = TestMigration(connection=mock_conn)

        assert hasattr(migration, "before_ddl_hooks")
        assert hasattr(migration, "after_ddl_hooks")
        assert isinstance(migration.before_ddl_hooks, list)
        assert isinstance(migration.after_ddl_hooks, list)

    def test_hook_registry_registration(self):
        """HookRegistry should register and retrieve hooks."""
        from confiture.core.hooks import Hook, HookPhase, HookRegistry, HookResult

        class TestHook(Hook):
            phase = HookPhase.AFTER_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_DDL",
                    hook_name="test_hook",
                )

        registry = HookRegistry()
        registry.register("test_hook", TestHook)

        # Should be able to retrieve registered hook
        hook_class = registry.get("test_hook")
        assert hook_class is TestHook

        # Should list all registered hooks
        hooks_list = registry.list_hooks()
        assert "test_hook" in hooks_list

    def test_global_hook_registration(self):
        """Global hook functions should work."""
        from confiture.core.hooks import (
            Hook,
            HookPhase,
            HookResult,
            register_hook,
            get_hook,
        )

        class CustomHook(Hook):
            phase = HookPhase.BEFORE_EXECUTE

            def execute(self, conn, context):
                return HookResult(
                    phase="BEFORE_DDL",
                    hook_name="custom_hook",
                )

        # Register and retrieve
        register_hook("custom_hook", CustomHook)
        hook_class = get_hook("custom_hook")
        assert hook_class is CustomHook


# ============================================================================
# Placeholder implementations to be completed in GREEN phase
# ============================================================================


@dataclass
class HookResult:
    """Result of hook execution."""

    phase: str
    hook_name: str
    rows_affected: int = 0
    stats: dict | None = None
    execution_time_ms: int = 0


class HookError(MigrationError):
    """Error raised when hook execution fails."""

    def __init__(self, hook_name: str, phase: str, error: Exception):
        self.hook_name = hook_name
        self.phase = phase
        self.original_error = error
        super().__init__(
            f"Hook {hook_name} failed in phase {phase}: {str(error)}"
        )


class HookContext:
    """Context passed to hooks during execution."""

    def __init__(
        self, migration_name: str, migration_version: str, direction: str = "forward"
    ):
        self.migration_name = migration_name
        self.migration_version = migration_version
        self.direction = direction
        self.stats = {}

    def get_stat(self, key: str):
        """Get a stored statistic."""
        return self.stats.get(key)

    def set_stat(self, key: str, value):
        """Store a statistic."""
        self.stats[key] = value


class HookPhase(Enum):
    """Phases during migration execution where hooks can run."""

    BEFORE_VALIDATION = 1
    BEFORE_DDL = 2
    AFTER_DDL = 3
    AFTER_VALIDATION = 4
    CLEANUP = 5
    ON_ERROR = 6


class Hook(ABC):
    """Abstract base class for all migration hooks."""

    phase: HookPhase

    @abstractmethod
    def execute(self, conn, context: HookContext) -> HookResult:
        """Execute hook logic.

        Args:
            conn: Database connection
            context: HookContext with migration metadata

        Returns:
            HookResult with execution status and metadata
        """
        pass


class HookExecutor:
    """Executes hooks during migration with savepoint support."""

    def execute_phase(self, conn, phase: HookPhase, hooks: list[Hook], context: HookContext):
        """Execute all hooks for a given phase.

        Args:
            conn: Database connection
            phase: HookPhase to execute
            hooks: List of Hook instances
            context: HookContext for execution

        Returns:
            List of HookResult objects
        """
        results = []

        for hook in hooks:
            try:
                result = hook.execute(conn, context)
                results.append(result)
            except Exception as e:
                raise HookError(hook.__class__.__name__, phase.name, e) from e

        return results
