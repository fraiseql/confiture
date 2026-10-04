"""The built-in backup hook: pg_dump compresses the dump and writes the file.

The argv is a pure function of the config and the paths; the rest runs a fake
``pg_dump`` put on ``PATH``, which answers ``--version`` and writes the ``-f``
file the way the real one does.
"""

import asyncio
import os
import stat
import time
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from confiture.core.hooks.builtin.backup_hook import (
    BackupConfig,
    BackupHook,
    Compression,
    client_major,
    pg_dump_argv,
)
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase

URL = "postgresql://test:secret@localhost/test"
SAFE_URL = "postgresql://test@localhost/test"

FAKE_PG_DUMP = """#!/bin/sh
echo "$@" >> "$FAKE_PG_DUMP_LOG"
if [ "$1" = "--version" ]; then
    echo "pg_dump (PostgreSQL) $FAKE_PG_DUMP_VERSION"
    exit 0
fi
out=""
prev=""
for arg in "$@"; do
    if [ "$prev" = "-f" ]; then out="$arg"; fi
    prev="$arg"
done
printf 'half a dump' > "$out"
if [ -n "$FAKE_PG_DUMP_HANG" ]; then exec sleep 30; fi
if [ "$FAKE_PG_DUMP_EXIT" != "0" ]; then
    echo "pg_dump: error: connection to postgresql://u:hunter2@h/db failed" >&2
fi
exit "$FAKE_PG_DUMP_EXIT"
"""


def _context(name: str = "003_add_users") -> HookContext[ExecutionContext]:
    return HookContext(
        phase=HookPhase.BEFORE_EXECUTE,
        data=ExecutionContext(metadata={"migration_name": name}),
    )


def _config(tmp_path: Path, **kwargs: object) -> BackupConfig:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return BackupConfig(backup_dir=tmp_path / "backups", database_url=URL, **kwargs)


@pytest.fixture
def fake_pg_dump(tmp_path, monkeypatch):
    """A ``pg_dump`` on PATH; returns the file its argv is logged to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "pg_dump"
    script.write_text(FAKE_PG_DUMP)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "pg_dump.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_PG_DUMP_LOG", str(log))
    monkeypatch.setenv("FAKE_PG_DUMP_VERSION", "18.4")
    monkeypatch.setenv("FAKE_PG_DUMP_EXIT", "0")
    return log


def _dump_argv(log: Path) -> list[str]:
    lines = [line for line in log.read_text().splitlines() if line != "--version"]
    assert len(lines) == 1, lines
    return lines[0].split()


class TestTheSetting:
    def test_identity(self, tmp_path):
        hook = BackupHook(_config(tmp_path))
        assert (hook.id, hook.name, hook.priority) == ("builtin.backup", "Database Backup", 1)

    def test_zstd_is_the_default(self, tmp_path):
        assert _config(tmp_path).method() == Compression("zstd")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("zstd", Compression("zstd")),
            ("zstd:9", Compression("zstd", 9)),
            ("gzip", Compression("gzip")),
            ("gzip:9", Compression("gzip", 9)),
            ("lz4", Compression("lz4")),
            ("none", Compression("none")),
        ],
    )
    def test_compression_values(self, tmp_path, value, expected):
        assert _config(tmp_path, compression=value).method() == expected

    @pytest.mark.parametrize(("compress", "method"), [(True, "gzip"), (False, "none")])
    def test_compress_maps_to_a_method_with_a_deprecation_warning(self, tmp_path, compress, method):
        with pytest.warns(DeprecationWarning, match="compression"):
            config = BackupConfig(backup_dir=tmp_path, database_url=URL, compress=compress)
        assert config.method() == Compression(method)

    def test_the_keys_fraisier_passes_construct(self, tmp_path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config = BackupConfig(backup_dir=str(tmp_path), database_url=URL, compress=True)
        assert config.method() == Compression("gzip")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"compress": True, "compression": "zstd"},
            {"compression": "brotli"},
            {"compression": "zstd:fast"},
            {"compression": "gzip:12"},
            {"compression": "none:3"},
        ],
        ids=[
            "both-given",
            "unknown-method",
            "level-not-a-number",
            "level-out-of-range",
            "none-with-level",
        ],
    )
    @pytest.mark.asyncio
    async def test_a_bad_setting_constructs_and_is_refused_when_run(self, tmp_path, kwargs):
        config = _config(tmp_path, **kwargs)  # never raises
        assert isinstance(config.method(), str)

        with patch("asyncio.create_subprocess_exec") as spawn:
            result = await BackupHook(config).execute(_context())

        spawn.assert_not_called()
        assert result.success is False
        assert "zstd" in result.error
        assert not (tmp_path / "backups").exists()


class TestTheArgv:
    @pytest.mark.parametrize(
        ("compression", "compress", "suffix"),
        [
            (Compression("zstd"), ["--compress=zstd"], ".sql.zst"),
            (Compression("zstd", 9), ["--compress=zstd:9"], ".sql.zst"),
            (Compression("gzip"), ["--compress=gzip"], ".sql.gz"),
            (Compression("lz4"), ["--compress=lz4"], ".sql.lz4"),
            (Compression("none"), [], ".sql"),
        ],
    )
    def test_pg_dump_compresses_and_writes_the_file(self, tmp_path, compression, compress, suffix):
        target = tmp_path / f"m{compression.suffix}.partial"
        assert compression.suffix == suffix
        assert pg_dump_argv(compression, target, SAFE_URL, 18) == [
            "pg_dump",
            "--no-owner",
            "--no-acl",
            *compress,
            "-f",
            str(target),
            SAFE_URL,
        ]

    def test_gzip_on_a_client_older_than_16_is_the_integer_form(self, tmp_path):
        argv = pg_dump_argv(Compression("gzip"), tmp_path / "m", SAFE_URL, 15)
        assert "--compress=6" in argv

    @pytest.mark.asyncio
    async def test_the_dump_never_goes_through_a_pipe(self, tmp_path):
        version = AsyncMock(returncode=0)
        version.communicate.return_value = (b"pg_dump (PostgreSQL) 18.4\n", b"")
        dump = AsyncMock(returncode=1)
        dump.communicate.return_value = (None, b"pg_dump: error: no server")

        with patch("asyncio.create_subprocess_exec", side_effect=[version, dump]) as spawn:
            result = await BackupHook(_config(tmp_path)).execute(_context())

        assert result.success is False
        args, kwargs = spawn.call_args
        assert kwargs["stdout"] is not asyncio.subprocess.PIPE
        assert kwargs["stderr"] is asyncio.subprocess.PIPE
        assert "--compress=zstd" in args
        assert args[-1] == SAFE_URL
        assert kwargs["env"]["PGPASSWORD"] == "secret"


class TestAFailedDumpLeavesNothing:
    @pytest.mark.asyncio
    async def test_a_failed_dump_leaves_no_file_and_prunes_nothing(
        self, tmp_path, fake_pg_dump, monkeypatch
    ):
        monkeypatch.setenv("FAKE_PG_DUMP_EXIT", "1")
        config = _config(tmp_path, max_backups=1)
        backups = tmp_path / "backups"
        backups.mkdir()
        previous = [backups / "001_a.sql.zst", backups / "002_b.sql.zst"]
        for path in previous:
            path.write_text("an earlier backup")

        result = await BackupHook(config).execute(_context())

        assert result.success is False
        assert sorted(backups.iterdir()) == previous

    @pytest.mark.asyncio
    async def test_a_cancelled_dump_leaves_no_file(self, tmp_path, fake_pg_dump, monkeypatch):
        monkeypatch.setenv("FAKE_PG_DUMP_HANG", "1")
        partial = tmp_path / "backups" / "003_add_users.sql.zst.partial"
        task = asyncio.create_task(BackupHook(_config(tmp_path)).execute(_context()))
        for _ in range(500):
            if partial.exists():
                break
            await asyncio.sleep(0.01)
        assert partial.exists()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert list((tmp_path / "backups").iterdir()) == []

    @pytest.mark.asyncio
    async def test_the_error_carries_no_password(self, tmp_path, fake_pg_dump, monkeypatch):
        monkeypatch.setenv("FAKE_PG_DUMP_EXIT", "1")
        result = await BackupHook(_config(tmp_path)).execute(_context())
        assert result.error is not None
        assert "pg_dump failed" in result.error
        assert "hunter2" not in result.error

    @pytest.mark.asyncio
    async def test_a_dump_that_succeeds_is_the_final_name_and_no_partial(
        self, tmp_path, fake_pg_dump
    ):
        result = await BackupHook(_config(tmp_path)).execute(_context())

        assert result.success is True, result.error
        backups = tmp_path / "backups"
        assert [p.name for p in backups.iterdir()] == ["003_add_users.sql.zst"]
        assert result.stats is not None
        assert result.stats["backup_path"] == str(backups / "003_add_users.sql.zst")
        argv = _dump_argv(fake_pg_dump)
        assert argv[argv.index("-f") + 1] == str(backups / "003_add_users.sql.zst.partial")

    @pytest.mark.asyncio
    async def test_pg_dump_not_found(self, tmp_path):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await BackupHook(_config(tmp_path)).execute(_context())
        assert result.success is False
        assert "pg_dump not found" in result.error


class TestRetentionAcrossSuffixes:
    def test_the_newest_backups_stay_whatever_wrote_them(self, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        names = ["1.sql.gz", "2.sql.gz", "3.sql.gz", "4.sql.zst", "5.sql.zst"]
        now = time.time()
        for age, name in enumerate(reversed(names)):
            path = backups / name
            path.write_text("dump")
            os.utime(path, (now - age * 60, now - age * 60))
        (backups / "6.sql.zst.partial").write_text("in flight")
        (backups / "notes.txt").write_text("keep me")

        BackupHook(_config(tmp_path, max_backups=3))._enforce_retention(backups)

        assert sorted(p.name for p in backups.iterdir()) == [
            "3.sql.gz",
            "4.sql.zst",
            "5.sql.zst",
            "6.sql.zst.partial",
            "notes.txt",
        ]


class TestTheClientVersion:
    @pytest.mark.parametrize(
        ("line", "major"),
        [
            ("pg_dump (PostgreSQL) 18.4", 18),
            ("pg_dump (PostgreSQL) 16.4 (Debian 16.4-1.pgdg120+2)", 16),
            ("pg_dump (PostgreSQL) 15.8", 15),
            ("something else", None),
        ],
    )
    def test_the_version_read(self, line, major):
        assert client_major(line) == major

    @pytest.mark.asyncio
    async def test_zstd_on_a_15_client_is_refused(self, tmp_path, fake_pg_dump, monkeypatch):
        monkeypatch.setenv("FAKE_PG_DUMP_VERSION", "15.8")
        result = await BackupHook(_config(tmp_path)).execute(_context())

        assert result.success is False
        assert "15.8" in result.error
        assert "16" in result.error
        assert fake_pg_dump.read_text().splitlines() == ["--version"]

    @pytest.mark.asyncio
    async def test_gzip_on_a_15_client_runs(self, tmp_path, fake_pg_dump, monkeypatch):
        monkeypatch.setenv("FAKE_PG_DUMP_VERSION", "15.8")
        result = await BackupHook(_config(tmp_path, compression="gzip")).execute(_context())

        assert result.success is True, result.error
        assert (tmp_path / "backups" / "003_add_users.sql.gz").exists()
        assert "--compress=6" in _dump_argv(fake_pg_dump)
