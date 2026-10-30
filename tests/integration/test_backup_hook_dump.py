"""The backup hook's dump, on a real server: pg_dump writes it, zstd-compressed."""

import asyncio
import os
from compression import zstd

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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


def _run(hook: BackupHook):
    return hook.execute(
        HookContext(
            phase=HookPhase.BEFORE_EXECUTE,
            data=ExecutionContext(metadata={"migration_name": "005_scoped"}),
        )
    )


#: Each one alone fails a ``pg_dump`` it reaches, before anything is dumped.
AMBIENT_POISONS = {
    "PGOPTIONS": "-c confiture_poison=on",
    "PGSERVICE": "confiture_no_such_service",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("variable", "value"), AMBIENT_POISONS.items())
async def test_env_keeps_the_ambient_environment_from_pg_dump(
    fresh_database, tmp_path, monkeypatch, variable, value
):
    """An ambient ``PG*`` variable reaches ``pg_dump`` unless ``env`` is given (#799)."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE tb_scoped (id bigint PRIMARY KEY)")
    monkeypatch.setenv(variable, value)

    control = await _run(
        BackupHook(BackupConfig(backup_dir=tmp_path / "c", database_url=fresh_database))
    )
    assert control.success is False

    scoped = await _run(
        BackupHook(
            BackupConfig(
                backup_dir=tmp_path / "s",
                database_url=fresh_database,
                env={"PATH": os.environ["PATH"]},
            )
        )
    )
    assert scoped.success is True, scoped.error
    dump = zstd.decompress((tmp_path / "s" / "005_scoped.sql.zst").read_bytes()).decode()
    assert "CREATE TABLE public.tb_scoped" in dump


@pytest.mark.asyncio
async def test_a_conninfo_dumps_with_its_password_off_argv(fresh_database, tmp_path, monkeypatch):
    """A keyword conninfo is dumped; its password reaches pg_dump only in PGPASSWORD."""
    params = conninfo_to_dict(fresh_database)
    params.setdefault("password", "unused-by-trust-or-peer")
    seen: list[tuple[str, ...]] = []
    spawn = asyncio.create_subprocess_exec

    async def recording(*argv, **kwargs):
        seen.append(tuple(argv))
        return await spawn(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording)
    config = BackupConfig(backup_dir=tmp_path, database_url=make_conninfo("", **params))

    result = await _run(BackupHook(config))

    assert result.success is True, result.error
    dump_argv = [argv for argv in seen if "--version" not in argv]
    assert len(dump_argv) == 1
    assert conninfo_to_dict(dump_argv[0][-1]).keys() == params.keys() - {"password"}
