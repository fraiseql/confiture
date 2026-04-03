"""Test hook integration with migration engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from confiture.core._migrator.engine import Migrator
from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase
from confiture.models.migration import Migration


class TestHookIntegration:
    """Test that hooks are properly integrated with migration execution."""

    def test_migrator_has_hook_registry(self):
        """Migrator should have a hook registry."""
        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        assert hasattr(migrator, "hook_registry")
        assert hasattr(migrator, "register_hook")

    def test_hook_registration(self):
        """Should be able to register hooks with migrator."""
        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        # Create a simple test hook
        class TestHook(Hook[ExecutionContext]):
            def __init__(self):
                super().__init__(hook_id="test.hook", name="Test Hook")

            async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
                return HookResult(success=True)

        hook = TestHook()
        migrator.register_hook(HookPhase.BEFORE_EXECUTE, hook)

        # Verify hook is registered
        assert "before_execute" in migrator.hook_registry.hooks
        assert len(migrator.hook_registry.hooks["before_execute"]) == 1

    @pytest.mark.asyncio
    async def test_hook_triggering_during_migration(self):
        """Hooks should be triggered during migration execution."""
        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        # Create a mock hook that tracks calls
        hook_calls = []

        class TrackingHook(Hook[ExecutionContext]):
            def __init__(self):
                super().__init__(hook_id="tracking.hook", name="Tracking Hook")

            async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
                hook_calls.append(
                    {
                        "phase": context.phase,
                        "migration_name": context.data.metadata.get("migration_name"),
                        "success": context.data.metadata.get("success"),
                    }
                )
                return HookResult(success=True)

        hook = TrackingHook()

        # Register for both before and after execute
        migrator.register_hook(HookPhase.BEFORE_EXECUTE, hook)
        migrator.register_hook(HookPhase.AFTER_EXECUTE, hook)

        # Create a mock migration
        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test_migration"
        mock_migration.up = MagicMock()
        mock_migration.transactional = True

        # Mock the savepoint methods
        migrator._create_savepoint = MagicMock()
        migrator._release_savepoint = MagicMock()
        migrator._rollback_to_savepoint = MagicMock()
        migrator._record_migration = MagicMock()
        migrator._is_applied = MagicMock(return_value=False)

        # Apply the migration
        migrator.apply(mock_migration)

        # Verify hooks were called
        assert len(hook_calls) == 2

        # Check before execute call
        before_call = next(call for call in hook_calls if call["phase"] == "before_execute")
        assert before_call["migration_name"] == "test_migration"
        assert before_call["success"] is False  # Before execution

        # Check after execute call
        after_call = next(call for call in hook_calls if call["phase"] == "after_execute")
        assert after_call["migration_name"] == "test_migration"
        assert after_call["success"] is True  # After successful execution
