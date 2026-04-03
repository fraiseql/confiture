"""Pre-migration database backup via pg_dump."""

from __future__ import annotations

import asyncio
import gzip
import logging
from dataclasses import dataclass
from pathlib import Path

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupConfig:
    """Configuration for database backup hook."""

    backup_dir: Path
    database_url: str
    compress: bool = True
    max_backups: int = 10  # retention: keep N most recent


class BackupHook(Hook[ExecutionContext]):
    """Create a pg_dump backup before each migration.

    Registers on HookPhase.before_execute. Creates timestamped
    backup files with optional gzip compression.
    """

    def __init__(self, config: BackupConfig) -> None:
        super().__init__(
            hook_id="builtin.backup",
            name="Database Backup",
            priority=1,  # run first
        )
        self._config = config

    async def execute(
        self,
        context: HookContext[ExecutionContext],
    ) -> HookResult:
        ctx = context.get_data()

        # Extract migration info from metadata or context
        migration_name = ctx.metadata.get("migration_name", "unknown_migration")

        backup_dir = self._config.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)

        suffix = ".sql.gz" if self._config.compress else ".sql"
        backup_path = backup_dir / f"{migration_name}{suffix}"

        # Run pg_dump as subprocess
        cmd = ["pg_dump", "--no-owner", "--no-acl", self._config.database_url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return HookResult(
                    success=False,
                    error=f"pg_dump failed: {stderr.decode().strip()}",
                )

            # Write backup (optionally compressed)
            if self._config.compress:
                backup_path.write_bytes(gzip.compress(stdout))
            else:
                backup_path.write_bytes(stdout)

            # Enforce retention
            self._enforce_retention(backup_dir, suffix)

            size_kb = backup_path.stat().st_size / 1024
            logger.info("Backup created: %s (%.1f KB)", backup_path, size_kb)

            return HookResult(
                success=True,
                stats={"backup_path": str(backup_path), "size_kb": size_kb},
            )
        except FileNotFoundError:
            return HookResult(
                success=False,
                error="pg_dump not found. Install PostgreSQL client tools.",
            )

    def _enforce_retention(self, backup_dir: Path, suffix: str) -> None:
        """Keep only the N most recent backups."""
        backups = sorted(
            backup_dir.glob(f"*{suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[self._config.max_backups :]:
            old.unlink()
            logger.debug("Removed old backup: %s", old)
