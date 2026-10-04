"""The backup hook's dump, on a real server: pg_dump writes it, zstd-compressed."""

from compression import zstd

import psycopg
import pytest

from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


@pytest.mark.asyncio
async def test_the_backup_is_a_zstd_dump_of_the_database(fresh_database, tmp_path):
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE tb_backed_up (id bigint PRIMARY KEY, label text)")

    hook = BackupHook(BackupConfig(backup_dir=tmp_path, database_url=fresh_database))
    result = await hook.execute(
        HookContext(
            phase=HookPhase.BEFORE_EXECUTE,
            data=ExecutionContext(metadata={"migration_name": "004_add_label"}),
        )
    )

    assert result.success is True, result.error
    backup = tmp_path / "004_add_label.sql.zst"
    assert sorted(p.name for p in tmp_path.iterdir()) == [backup.name]
    dump = zstd.decompress(backup.read_bytes()).decode()
    assert "CREATE TABLE public.tb_backed_up" in dump
