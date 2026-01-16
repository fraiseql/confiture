"""Unit tests for hook base classes and executor.

Tests:
- HookError exception with detailed context
- HookResult dataclass
- Hook abstract base class
- HookExecutor basic functionality
"""

import pytest
from unittest.mock import Mock, patch
from confiture.core.hooks.base import (
    HookError,
    HookResult,
    Hook,
    HookExecutor,
)


class TestHookError:
    """Test HookError exception."""

    def test_hook_error_basic_message(self):
        """Test HookError with just a message."""
        error = HookError("Test error")
        assert str(error) == "Test error"
        assert error.hook_id is None
        assert error.hook_name is None
        assert error.phase is None
        assert error.cause is None

    def test_hook_error_with_hook_name(self):
        """Test HookError with hook name."""
        error = HookError("Test error", hook_name="my_hook")
        assert "my_hook" in str(error)
        assert error.hook_name == "my_hook"

    def test_hook_error_with_hook_id(self):
        """Test HookError with hook ID."""
        error = HookError("Test error", hook_id="hook-123")
        assert error.hook_id == "hook-123"

    def test_hook_error_with_phase(self):
        """Test HookError with phase."""
        error = HookError("Test error", phase="pre_migration")
        assert "pre_migration" in str(error)
        assert error.phase == "pre_migration"

    def test_hook_error_with_cause(self):
        """Test HookError with underlying cause."""
        cause = ValueError("Original error")
        error = HookError("Wrapper error", cause=cause)
        assert error.cause == cause

    def test_hook_error_full_context(self):
        """Test HookError with all parameters."""
        cause = RuntimeError("Database connection failed")
        error = HookError(
            "Hook failed",
            hook_id="hook-001",
            hook_name="validate_schema",
            phase="pre_migration",
            cause=cause,
        )

        error_str = str(error)
        assert "Hook failed" in error_str
        assert "validate_schema" in error_str
        assert "pre_migration" in error_str
        assert error.hook_id == "hook-001"
        assert error.cause == cause

    def test_hook_error_repr(self):
        """Test HookError representation."""
        error = HookError(
            "Test error",
            hook_name="test_hook",
            phase="pre_migration"
        )
        error_repr = repr(error)
        assert error_repr  # Just verify it's not empty


class TestHookResult:
    """Test HookResult dataclass."""

    def test_hook_result_success(self):
        """Test successful hook result."""
        result = HookResult(success=True, rows_affected=100)
        assert result.success is True
        assert result.rows_affected == 100
        assert result.error is None
        assert result.stats is None

    def test_hook_result_failure(self):
        """Test failed hook result."""
        result = HookResult(
            success=False,
            rows_affected=0,
            error="Invalid data found",
        )
        assert result.success is False
        assert result.error == "Invalid data found"

    def test_hook_result_with_stats(self):
        """Test hook result with statistics."""
        stats = {"duration_ms": 150.5, "cache_hits": 42}
        result = HookResult(
            success=True,
            rows_affected=1000,
            stats=stats,
        )
        assert result.stats == stats
        assert result.stats["duration_ms"] == 150.5

    def test_hook_result_defaults(self):
        """Test HookResult default values."""
        result = HookResult(success=True)
        assert result.success is True
        assert result.rows_affected == 0
        assert result.error is None
        assert result.stats is None

    def test_hook_result_with_multiple_stats(self):
        """Test hook result with multiple stat entries."""
        stats = {
            "duration_ms": 200.0,
            "rows_processed": 500,
            "cache_hits": 150,
            "cache_misses": 50,
        }
        result = HookResult(success=True, stats=stats)
        assert len(result.stats) == 4
        assert result.stats["cache_hits"] == 150


class TestHook:
    """Test Hook abstract base class."""

    def test_hook_initialization(self):
        """Test Hook initialization."""

        class SimpleHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = SimpleHook(hook_id="hook-1", name="test_hook")
        assert hook.id == "hook-1"
        assert hook.name == "test_hook"
        assert hook.priority == 5  # default priority
        assert hook.depends_on == []

    def test_hook_with_priority(self):
        """Test Hook with custom priority."""

        class PriorityHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = PriorityHook(hook_id="hook-2", name="priority_hook", priority=2)
        assert hook.priority == 2

    def test_hook_with_high_priority(self):
        """Test Hook with high priority value."""

        class LowPriorityHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = LowPriorityHook(hook_id="hook-10", name="low_priority", priority=10)
        assert hook.priority == 10

    def test_hook_with_dependencies(self):
        """Test Hook with dependencies."""

        class DependentHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = DependentHook(
            hook_id="hook-3",
            name="dependent",
            depends_on=["hook-1", "hook-2"],
        )
        assert hook.depends_on == ["hook-1", "hook-2"]

    def test_hook_with_single_dependency(self):
        """Test Hook with single dependency."""

        class SingleDepHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = SingleDepHook(
            hook_id="hook-4",
            name="single_dep",
            depends_on=["parent_hook"],
        )
        assert len(hook.depends_on) == 1
        assert hook.depends_on[0] == "parent_hook"

    def test_hook_cannot_be_instantiated_directly(self):
        """Test that Hook cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Hook(hook_id="direct", name="direct_hook")


class TestHookExecutor:
    """Test HookExecutor class."""

    def test_executor_initialization(self):
        """Test HookExecutor initialization."""
        executor = HookExecutor()
        assert executor.registry is None
        assert executor._executed_hooks == set()
        assert executor._hook_results == {}

    def test_executor_with_registry(self):
        """Test HookExecutor with registry."""
        registry = Mock()
        executor = HookExecutor(registry=registry)
        assert executor.registry == registry

    def test_executor_initialized_with_empty_state(self):
        """Test HookExecutor initializes with empty state."""
        executor = HookExecutor()
        assert len(executor._executed_hooks) == 0
        assert len(executor._hook_results) == 0

    @pytest.mark.asyncio
    async def test_execute_phase_no_registry(self):
        """Test executing phase without registry."""
        executor = HookExecutor()
        results = await executor.execute_phase("pre_migration", Mock())
        assert results == {}

    @pytest.mark.asyncio
    async def test_execute_phase_no_hooks(self):
        """Test executing phase with no hooks registered."""
        registry = Mock()
        registry.get_hooks = Mock(return_value=[])

        executor = HookExecutor(registry=registry)
        results = await executor.execute_phase("pre_migration", Mock())

        assert results == {}
        registry.get_hooks.assert_called_once_with("pre_migration")

    @pytest.mark.asyncio
    async def test_execute_phase_registry_without_get_hooks(self):
        """Test with registry that doesn't have get_hooks method."""
        registry = Mock(spec=[])  # Mock with no get_hooks

        executor = HookExecutor(registry=registry)
        results = await executor.execute_phase("pre_migration", Mock())

        assert results == {}

    def test_executor_state_after_initialization(self):
        """Test executor state after initialization."""
        executor = HookExecutor()
        assert isinstance(executor._executed_hooks, set)
        assert isinstance(executor._hook_results, dict)

    @pytest.mark.asyncio
    async def test_execute_phase_returns_dict(self):
        """Test execute_phase always returns a dictionary."""
        executor = HookExecutor()
        result = await executor.execute_phase("any_phase", Mock())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_execute_phase_different_phase_names(self):
        """Test execute_phase with different phase names."""
        executor = HookExecutor()

        result1 = await executor.execute_phase("pre_migration", Mock())
        result2 = await executor.execute_phase("post_migration", Mock())
        result3 = await executor.execute_phase("cleanup", Mock())

        assert all(isinstance(r, dict) for r in [result1, result2, result3])

    def test_hook_executor_attributes(self):
        """Test HookExecutor has expected attributes."""
        executor = HookExecutor()
        assert hasattr(executor, "registry")
        assert hasattr(executor, "_executed_hooks")
        assert hasattr(executor, "_hook_results")

    def test_hook_error_initialization(self):
        """Test HookError initialization and attributes."""
        error = HookError("test", hook_id="h1", hook_name="h_name", phase="pre")
        assert error.hook_id == "h1"
        assert error.hook_name == "h_name"
        assert error.phase == "pre"

    def test_hook_result_comparison(self):
        """Test HookResult can be compared."""
        result1 = HookResult(success=True, rows_affected=10)
        result2 = HookResult(success=True, rows_affected=10)
        # Same values
        assert result1.success == result2.success
        assert result1.rows_affected == result2.rows_affected

    def test_hook_result_with_none_stats(self):
        """Test HookResult with None stats defaults to None."""
        result = HookResult(success=True, stats=None)
        assert result.stats is None

    @pytest.mark.asyncio
    async def test_execute_phase_exception_handling(self):
        """Test execute_phase handles registry errors gracefully."""
        registry = Mock()
        registry.get_hooks = Mock(side_effect=RuntimeError("Registry error"))

        executor = HookExecutor(registry=registry)

        with pytest.raises(HookError):
            await executor.execute_phase("pre_migration", Mock())

    def test_hook_priority_range(self):
        """Test Hook with various priority values."""

        class TestHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        for priority in [1, 5, 10]:
            hook = TestHook(hook_id=f"h-{priority}", name=f"hook-{priority}", priority=priority)
            assert hook.priority == priority

    def test_hook_with_empty_dependencies(self):
        """Test Hook with explicitly empty dependencies."""

        class NoDepHook(Hook):
            async def execute(self, context):
                return HookResult(success=True)

        hook = NoDepHook(hook_id="h-nodep", name="no_deps", depends_on=[])
        assert hook.depends_on == []

    def test_hook_error_preserves_all_context(self):
        """Test HookError preserves all context information."""
        original_error = RuntimeError("root cause")
        hook_error = HookError(
            "Failed to execute",
            hook_id="hook-123",
            hook_name="validator",
            phase="pre_validation",
            cause=original_error,
        )

        assert hook_error.hook_id == "hook-123"
        assert hook_error.hook_name == "validator"
        assert hook_error.phase == "pre_validation"
        assert hook_error.cause is original_error
