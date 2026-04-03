"""Unit tests for builtin hook registration."""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.hooks.builtin import AuditHook, BackupHook, SlackNotificationHook
from confiture.core.hooks.phases import HookPhase
from confiture.core.hooks.registry import HookRegistry


class TestBuiltinRegistration:
    """Test suite for registering builtin hooks."""

    def test_register_backup_hook(self):
        """Should be able to register BackupHook with HookRegistry."""
        registry = HookRegistry()

        from confiture.core.hooks.builtin.backup_hook import BackupConfig
        from pathlib import Path

        config = BackupConfig(
            backup_dir=Path("/tmp/backups"),
            database_url="postgresql://test:test@localhost/test",
        )
        hook = BackupHook(config)

        # Register hook
        registry.register("before_execute", hook)

        # Verify registration
        assert "before_execute" in registry.hooks
        assert len(registry.hooks["before_execute"]) == 1
        assert registry.hooks["before_execute"][0].id == "builtin.backup"

    def test_register_audit_hook(self):
        """Should be able to register AuditHook with HookRegistry."""
        registry = HookRegistry()

        from confiture.core.hooks.builtin.audit_hook import AuditConfig

        config = AuditConfig(
            database_url="postgresql://test:test@localhost/test",
            signing_key="test_key",
            environment="test",
        )
        hook = AuditHook(config)

        # Register hook
        registry.register("after_execute", hook)

        # Verify registration
        assert "after_execute" in registry.hooks
        assert len(registry.hooks["after_execute"]) == 1
        assert registry.hooks["after_execute"][0].id == "builtin.audit"

    def test_register_slack_hook(self):
        """Should be able to register SlackNotificationHook with HookRegistry."""
        registry = HookRegistry()

        from confiture.core.hooks.builtin.notification_hook import SlackConfig

        config = SlackConfig(
            webhook_url="https://hooks.slack.com/test",
        )
        hook = SlackNotificationHook(config)

        # Register hook
        registry.register("after_execute", hook)

        # Verify registration
        assert "after_execute" in registry.hooks
        assert len(registry.hooks["after_execute"]) == 1
        assert registry.hooks["after_execute"][0].id == "builtin.slack"

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_builtin_hooks_can_execute(self, mock_subprocess):
        """Builtin hooks should be executable through registry."""
        registry = HookRegistry()

        # Mock subprocess for backup hook
        from unittest.mock import AsyncMock

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"test dump", b"")
        mock_subprocess.return_value = mock_proc

        # Register backup hook
        from confiture.core.hooks.builtin.backup_hook import BackupConfig
        from pathlib import Path

        config = BackupConfig(
            backup_dir=Path("/tmp/backups"),
            database_url="postgresql://test:test@localhost/test",
        )
        backup_hook = BackupHook(config)
        registry.register(HookPhase.BEFORE_EXECUTE, backup_hook)

        # Create execution context
        from confiture.core.hooks.context import ExecutionContext, HookContext

        ctx = ExecutionContext(metadata={"migration_name": "test_migration"})
        hook_context = HookContext(
            phase=HookPhase.BEFORE_EXECUTE,
            data=ctx,
        )

        # Trigger hook execution
        result = await registry.trigger(HookPhase.BEFORE_EXECUTE, hook_context)

        assert result.hooks_executed == 1
        assert result.phase == "before_execute"
