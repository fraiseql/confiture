"""The migrator's public face: :class:`Migrator`, :class:`MigratorSession`, and what they read.

The implementation lives in ``confiture.core._migrator``: the engine that operates on
one connection's migrations and ledger, the session that drives it with a lock and a
connection lifecycle. :class:`Migrator` is the engine plus the two conveniences that
open or attach a session, which is why it is defined here, above both, rather than
in the engine: the engine never needs to know a session exists.

This module holds no patch seams. Tests and embedders inject through
``MigratorSession(connection_factory=..., migration_loader=...)`` or the class-level
``MigratorSession.default_*`` attributes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.core._migrator import factory as _factory
from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    discover_migration_files,
    find_duplicate_migration_versions,
    parse_migration_filename,
)
from confiture.core._migrator.engine import MigrationEngine
from confiture.core._migrator.events import UpEvent, UpObserver
from confiture.core._migrator.session import MigratorSession

# Names the session resolves through this module at call time. Tests patch
# either ``confiture.core.migrator.<name>`` (this namespace) or the defining
# module's attribute; the two function wrappers below honour both.
from confiture.core.checksum import ChecksumConfig
from confiture.core.locking import LockConfig, MigrationLock
from confiture.core.progress import ProgressManager
from confiture.exceptions import MigrationError, SchemaError

if TYPE_CHECKING:
    from confiture.config.environment import Environment

__all__ = [
    "LockConfig",
    "MigrationLock",
    "Migrator",
    "MigratorSession",
    "UpEvent",
    "UpObserver",
    "_version_from_migration_filename",
    "discover_migration_files",
    "find_duplicate_migration_versions",
    "parse_migration_filename",
    "replay_migrations",
]


class Migrator(MigrationEngine):
    """Executes database migrations and tracks their state.

    The engine (:class:`~confiture.core._migrator.engine.MigrationEngine`) with the
    two ways into a session: :meth:`from_config`, which opens one, and
    :meth:`migrate_up`, which attaches one to this engine's connection.

    Example:
        >>> with Migrator.from_config("db/environments/prod.yaml") as m:
        ...     m.up()
    """

    @classmethod
    def from_config(
        cls,
        config: Environment | Path | str,
        *,
        migrations_dir: Path | str = Path("db/migrations"),
        connection_factory: Callable[[Any], Any] | None = None,
        migration_loader: Callable[[Path], type] | None = None,
    ) -> MigratorSession:
        """Create a managed MigratorSession from an Environment config.

        Accepts an ``Environment`` object, a ``Path`` to a YAML config file,
        or a string path. The returned ``MigratorSession`` must be used as a
        context manager (``with`` statement) to ensure the database connection
        is properly closed.

        Args:
            config: One of:
                    - ``Environment`` instance (pre-loaded config)
                    - ``Path`` or ``str`` path to YAML config file
                    Example: ``"db/environments/prod.yaml"``
            migrations_dir: Directory containing migration files.
                           Defaults to ``db/migrations``.

        Returns:
            MigratorSession context manager.

        Raises:
            MigrationError: If the config file cannot be found.
            ConfigurationError: If the YAML config is invalid.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     status = m.status()
            ...     if status.has_pending:
            ...         result = m.up()
        """
        return _factory.from_config(
            config,
            migrations_dir=migrations_dir,
            connection_factory=connection_factory,
            migration_loader=migration_loader,
        )

    def migrate_up(
        self,
        force: bool = False,
        migrations_dir: Path | None = None,
        target: str | None = None,
        lock_config: LockConfig | None = None,
        checksum_config: ChecksumConfig | None = None,
        progress: ProgressManager | None = None,
    ) -> list[str]:
        """Apply pending migrations through the one apply loop.

        A thin call into :meth:`MigratorSession.up` attached to this engine's
        connection: the lock is taken first, discovery and the ledger init run
        under it, checksums are verified before anything is applied.

        Args:
            force: If True, skip migration state checks and apply all migrations
            migrations_dir: Custom migrations directory (default: db/migrations)
            target: Target migration version (applies all if None)
            lock_config: ``enabled`` and ``timeout_ms`` are honoured (default:
                enabled, 30s). Pass ``LockConfig(enabled=False)`` to disable locking.
            checksum_config: ``enabled`` and ``on_mismatch`` are honoured (default:
                enabled, fail on mismatch).
            progress: Optional ProgressManager advanced once per applied migration

        Returns:
            Versions applied, in order.

        Raises:
            ChecksumVerificationError: A tampered applied file (``on_mismatch=FAIL``).
            LockAcquisitionError: The migration lock could not be taken.
            MigrationError: A migration failed (the original exception is re-raised),
                or the chain halted on ``requires_superuser=True``.

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> applied = migrator.migrate_up()
        """
        lock_config = lock_config or LockConfig()
        checksum_config = checksum_config or ChecksumConfig()
        session = MigratorSession.attached(self, migrations_dir or Path("db/migrations"))
        result = session.up(
            target=target,
            force=force,
            verify_checksums=checksum_config.enabled,
            on_checksum_mismatch=checksum_config.on_mismatch.value,
            lock_timeout=lock_config.timeout_ms,
            no_lock=not lock_config.enabled,
            on_event=_progress_observer(progress) if progress is not None else None,
        )
        if result.failure is not None:
            raise result.failure
        if not result.success:
            raise MigrationError(result.error_summary or "Migration chain halted before completion")
        return [m.version for m in result.migrations_applied]


def _progress_observer(progress: ProgressManager) -> Any:
    """Advance a ``ProgressManager`` task once per applied migration."""
    state: dict[str, Any] = {"task": None}

    def observe(event: Any) -> None:
        if event.kind == "applying" and state["task"] is None:
            state["task"] = progress.add_task("Applying migrations...", total=None)
        elif event.kind == "applied" and state["task"] is not None:
            progress.update(state["task"], advance=1)

    return observe


def replay_migrations(
    database_url: str, migrations_dir: Path, migration_table: str | None = None
) -> None:
    """``migrate up`` every migration in *migrations_dir* against *database_url*.

    What ``ExpectedSchemaDB.from_base_plus_migrations`` is handed to build the
    schema a repository's migrations produce.

    Raises:
        SchemaError: A migration failed to apply.
    """
    session = MigratorSession(
        config=None,
        migrations_dir=migrations_dir,
        database_url_override=database_url,
        migration_table_override=migration_table,
    )
    with session:
        result = session.up()
    if not result.success:
        raise SchemaError(
            f"Migration replay into the scratch database failed: {result.errors}",
            resolution_hint="Fix the failing migration, then retry the drift check.",
        )
