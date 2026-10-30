"""Pre-migration database backup via pg_dump.

``pg_dump`` compresses the dump and writes the file itself: the dump never passes
through confiture's memory. It writes to ``<name><suffix>.partial`` and the file is
renamed onto its final name only once ``pg_dump`` has exited 0, so a failed dump
never counts as a backup.
"""

import asyncio
import contextlib
import logging
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.url_redaction import libpq_env, redact_credentials_in, split_password

logger = logging.getLogger(__name__)

#: The suffix each method writes. Retention prunes every one of them, so a history
#: written under one setting is pruned once the hook writes another.
SUFFIXES: dict[str, str] = {
    "zstd": ".sql.zst",
    "gzip": ".sql.gz",
    "lz4": ".sql.lz4",
    "none": ".sql",
}

#: The levels ``pg_dump`` accepts per method (``none`` takes none).
_LEVELS: dict[str, range] = {
    "zstd": range(-131072, 23),
    "gzip": range(1, 10),
    "lz4": range(1, 13),
}

#: The first ``pg_dump`` that knows ``--compress=<method>``, zstd and lz4.
_METHOD_SYNTAX_MAJOR = 16

#: A ``pg_dump --version`` line: ``pg_dump (PostgreSQL) 18.4``, or a distro build
#: such as ``pg_dump (PostgreSQL) 16.4 (Debian 16.4-1.pgdg120+2)``.
_VERSION = re.compile(r"\(PostgreSQL\)\s+(\d+)(?:\.(\d+))?")

_ACCEPTED = "zstd, gzip, lz4 or none, optionally with a level (zstd:9)"


@dataclass(frozen=True)
class Compression:
    """How ``pg_dump`` compresses a backup: a method and an optional level."""

    method: str
    level: int | None = None

    @property
    def suffix(self) -> str:
        """The backup file's suffix."""
        return SUFFIXES[self.method]

    def spec(self, client_major: int | None) -> str | None:
        """The ``--compress`` value, or ``None`` for an uncompressed dump.

        A client older than 16 knows only the integer form, which means gzip.
        """
        if self.method == "none":
            return None
        if (
            self.method == "gzip"
            and client_major is not None
            and (client_major < _METHOD_SYNTAX_MAJOR)
        ):
            return str(self.level or 6)
        return self.method if self.level is None else f"{self.method}:{self.level}"


def parse_compression(value: str) -> Compression | str:
    """*value* (``zstd``, ``zstd:9``, …) read, or the reason it is refused."""
    method, _, level_text = value.strip().lower().partition(":")
    if method not in SUFFIXES:
        return f"unknown backup compression {value!r}: expected {_ACCEPTED}"
    if not level_text:
        return Compression(method)
    levels = _LEVELS.get(method)
    try:
        level = int(level_text)
    except ValueError:
        level = None
    if levels is None or level is None or level not in levels:
        accepted = "no level" if levels is None else f"a level from {levels[0]} to {levels[-1]}"
        return (
            f"invalid backup compression {value!r}: {method} takes {accepted}; expected {_ACCEPTED}"
        )
    return Compression(method, level)


@dataclass(frozen=True)
class BackupConfig:
    """Configuration for database backup hook.

    ``compression`` is ``zstd`` (the default), ``gzip``, ``lz4`` or ``none``,
    optionally with a level (``zstd:9``). ``compress`` is the older switch:
    ``True`` means ``gzip``, ``False`` means ``none``.

    ``database_url`` is a URI or a libpq keyword conninfo; either way its
    password reaches ``pg_dump`` in ``PGPASSWORD``, never on argv.

    ``env``, when given, is the whole environment of ``pg_dump`` and of
    ``pg_dump --version``: nothing of the process environment reaches them, so
    an ambient ``PGHOSTADDR``, ``PGOPTIONS`` or ``PGSERVICE`` cannot change
    which server is dumped or what. It must carry a ``PATH`` that finds
    ``pg_dump`` (without one, the system default path is searched). ``None``
    (the default) inherits the process environment.

    The constructor never refuses a value: a caller that registers hooks
    best-effort would drop the backup silently. A value it cannot use is refused
    when the hook runs, as a failed :class:`HookResult` (see :meth:`method`).
    """

    backup_dir: Path
    database_url: str
    compress: bool | None = None
    max_backups: int = 10  # retention: keep N most recent
    compression: str | None = None
    env: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.compress is not None:
            warnings.warn(
                "BackupConfig(compress=...) is deprecated; use compression= "
                "('zstd', 'gzip', 'lz4' or 'none')",
                DeprecationWarning,
                stacklevel=3,
            )

    def method(self) -> Compression | str:
        """The compression this config asks for, or the reason it is refused."""
        if self.compress is not None and self.compression is not None:
            return (
                "backup compression is set twice: give compression= "
                f"({_ACCEPTED}), not compress= as well"
            )
        if self.compress is not None:
            return Compression("gzip" if self.compress else "none")
        return parse_compression(self.compression or "zstd")


def client_major(version_output: str) -> int | None:
    """The major version a ``pg_dump --version`` line names, or ``None``."""
    match = _VERSION.search(version_output)
    return int(match.group(1)) if match else None


def client_version(version_output: str) -> str | None:
    """The version (``15.8``) a ``pg_dump --version`` line names, or ``None``."""
    match = _VERSION.search(version_output)
    if match is None:
        return None
    return match.group(1) if match.group(2) is None else f"{match.group(1)}.{match.group(2)}"


def pg_dump_argv(
    compression: Compression, target: Path, url: str, client_major: int | None
) -> list[str]:
    """The ``pg_dump`` command writing *url*'s dump to *target*, compressed."""
    spec = compression.spec(client_major)
    compress = [] if spec is None else [f"--compress={spec}"]
    return ["pg_dump", "--no-owner", "--no-acl", *compress, "-f", str(target), url]


def _refused(reason: str) -> HookResult:
    return HookResult(success=False, error=f"backup refused: {reason}")


class BackupHook(Hook[ExecutionContext]):
    """Create a pg_dump backup before each migration.

    Registers on HookPhase.before_execute. ``pg_dump`` compresses the dump
    (zstd by default) and writes the file itself.
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
        compression = self._config.method()
        if isinstance(compression, str):
            return _refused(compression)

        try:
            target, password = split_password(self._config.database_url)
        except ValueError as exc:
            return _refused(str(exc))

        ctx = context.get_data()
        migration_name = ctx.metadata.get("migration_name", "unknown_migration")
        backup_dir = Path(self._config.backup_dir)

        try:
            version = await _pg_dump_version(self._config.env)
            major = client_major(version)
            if compression.method in {"zstd", "lz4"} and (
                major is not None and major < _METHOD_SYNTAX_MAJOR
            ):
                return _refused(
                    f"{compression.method} needs pg_dump 16 or newer; the pg_dump "
                    f"client here is {client_version(version)}"
                )
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{migration_name}{compression.suffix}"
            failure = await self._dump(compression, backup_path, major, target, password)
        except FileNotFoundError:
            return HookResult(success=False, error=self._not_found())
        if failure is not None:
            return HookResult(success=False, error=failure)

        self._enforce_retention(backup_dir)
        size_kb = backup_path.stat().st_size / 1024
        logger.info("Backup created: %s (%.1f KB)", backup_path, size_kb)
        return HookResult(
            success=True,
            stats={"backup_path": str(backup_path), "size_kb": size_kb},
        )

    async def _dump(
        self,
        compression: Compression,
        backup_path: Path,
        major: int | None,
        target: str,
        password: str | None,
    ) -> str | None:
        """Run ``pg_dump`` on *target* into a partial file; ``None`` once it is the backup.

        *password* rides in PGPASSWORD, never on argv, where ``ps aux`` would
        show it to every user on the host. Whatever happens, no partial file
        is left behind.
        """
        partial = backup_path.with_name(f"{backup_path.name}.partial")
        try:
            proc = await asyncio.create_subprocess_exec(
                *pg_dump_argv(compression, partial, target, major),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=libpq_env(password, base=self._config.env),
            )
            try:
                _, stderr = await proc.communicate()
            except asyncio.CancelledError:
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()
                raise
            if proc.returncode != 0:
                message = redact_credentials_in((stderr or b"").decode(errors="replace"))
                return f"pg_dump failed: {message.strip()}"
            if not partial.exists():
                return "pg_dump exited 0 but wrote no file"
            partial.replace(backup_path)
            return None
        finally:
            partial.unlink(missing_ok=True)

    def _not_found(self) -> str:
        """The error for a ``pg_dump`` the child's ``PATH`` does not hold."""
        if self._config.env is None:
            return "pg_dump not found. Install PostgreSQL client tools."
        return (
            "pg_dump not found on the PATH of BackupConfig.env. "
            "Install PostgreSQL client tools there."
        )

    def _enforce_retention(self, backup_dir: Path) -> None:
        """Keep only the N most recent backups, whatever method wrote them."""
        backups = {path for suffix in SUFFIXES.values() for path in backup_dir.glob(f"*{suffix}")}
        newest_first = sorted(backups, key=lambda p: p.stat().st_mtime, reverse=True)
        for old in newest_first[self._config.max_backups :]:
            old.unlink()
            logger.debug("Removed old backup: %s", old)


async def _pg_dump_version(env: Mapping[str, str] | None) -> str:
    """What ``pg_dump --version`` prints (empty when it prints nothing usable).

    It runs in *env*, or inherits the process environment when there is none.
    """
    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=None if env is None else dict(env),
    )
    stdout, _ = await proc.communicate()
    return stdout.decode(errors="replace") if stdout else ""
