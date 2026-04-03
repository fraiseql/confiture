"""Unit tests for builtin backup hook."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confiture.core.hooks.base import HookResult
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


class TestBackupHook:
    """Test suite for database backup hook."""

    @pytest.fixture
    def backup_config(self, tmp_path):
        """Create test backup configuration."""
        return BackupConfig(
            backup_dir=tmp_path / "backups",
            database_url="postgresql://test:test@localhost/test",
            compress=True,
            max_backups=3,
        )

    @pytest.fixture
    def execution_context(self):
        """Create test execution context."""
        return ExecutionContext(metadata={"migration_name": "test_migration"})

    @pytest.fixture
    def hook_context(self, execution_context):
        """Create test hook context."""
        return HookContext(
            phase=HookPhase.BEFORE_EXECUTE,
            data=execution_context,
        )

    def test_backup_hook_initialization(self, backup_config):
        """BackupHook should initialize with correct properties."""
        hook = BackupHook(backup_config)

        assert hook.id == "builtin.backup"
        assert hook.name == "Database Backup"
        assert hook.priority == 1

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_backup_hook_successful_backup(
        self,
        mock_subprocess,
        backup_config,
        hook_context,
    ):
        """BackupHook should create compressed backup successfully."""
        # Mock successful pg_dump
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"test sql dump", b"")
        mock_subprocess.return_value = mock_proc

        hook = BackupHook(backup_config)
        result = await hook.execute(hook_context)

        assert result.success is True
        assert "backup_path" in result.stats
        assert "size_kb" in result.stats

        # Verify backup directory was created
        assert backup_config.backup_dir.exists()

        # Verify pg_dump was called correctly
        mock_subprocess.assert_called_once_with(
            "pg_dump",
            "--no-owner",
            "--no-acl",
            backup_config.database_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_backup_hook_pg_dump_failure(
        self,
        mock_subprocess,
        backup_config,
        hook_context,
    ):
        """BackupHook should handle pg_dump failures gracefully."""
        # Mock failed pg_dump
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"pg_dump: connection failed")
        mock_subprocess.return_value = mock_proc

        hook = BackupHook(backup_config)
        result = await hook.execute(hook_context)

        assert result.success is False
        assert "pg_dump failed" in result.error

    @pytest.mark.asyncio
    async def test_backup_hook_pg_dump_not_found(
        self,
        backup_config,
        hook_context,
    ):
        """BackupHook should handle missing pg_dump gracefully."""
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            hook = BackupHook(backup_config)
            result = await hook.execute(hook_context)

        assert result.success is False
        assert "pg_dump not found" in result.error

    @pytest.mark.asyncio
    async def test_backup_hook_uncompressed_backup(
        self,
        backup_config,
        hook_context,
    ):
        """BackupHook should create uncompressed backups when configured."""
        backup_config = BackupConfig(
            backup_dir=backup_config.backup_dir,
            database_url=backup_config.database_url,
            compress=False,
        )

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"test sql dump", b"")
            mock_subprocess.return_value = mock_proc

            hook = BackupHook(backup_config)
            result = await hook.execute(hook_context)

            assert result.success is True
            backup_path = backup_config.backup_dir / "test_migration.sql"
            assert backup_path.exists()

    def test_backup_hook_enforce_retention(self, backup_config):
        """BackupHook should enforce backup retention limits."""
        hook = BackupHook(backup_config)

        # Create some fake backup files
        backup_dir = backup_config.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)

        for i in range(5):  # More than max_backups (3)
            backup_file = backup_dir / f"old_backup_{i}.sql.gz"
            backup_file.write_text("fake backup")
            # Set different modification times
            backup_file.touch()

        # Should keep only 3 most recent
        hook._enforce_retention(backup_dir, ".sql.gz")

        remaining = list(backup_dir.glob("*.sql.gz"))
        assert len(remaining) == 3
