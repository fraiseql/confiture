"""MigratorSession — context manager for managed migration sessions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from psycopg import Connection

    from confiture.config.environment import Environment
    from confiture.models.results import (
        CurrentRevision,
        DownToResult,
        MigrateDownResult,
        MigrateRebuildResult,
        MigrateReinitResult,
        MigrateUpResult,
        MigrationApplied,
        PreflightAgainstResult,
        PreflightResult,
        StatusResult,
    )


from confiture.core import connection
from confiture.core._migrator import apply_loop as _apply_loop
from confiture.core._migrator import replay as _replay
from confiture.core._migrator import reporting as _reporting
from confiture.core._migrator import rollback_loop as _rollback_loop
from confiture.core._migrator.events import UpObserver
from confiture.core.locking import LockConfig, MigrationLock, resolve_lock_settings
from confiture.exceptions import ConfigurationError


def _not_entered() -> ConfigurationError:
    """The error every session method raises outside its ``with`` block."""
    return ConfigurationError(
        "MigratorSession must be used as a context manager",
        resolution_hint="Use: with Migrator.from_config(...) as m: ...",
    )


def _core_connection():
    """``confiture.core.connection``, imported when first needed (it imports psycopg)."""

    return connection


class MigratorSession:
    """Context manager that wraps Migrator with connection lifecycle management.

    Created via ``Migrator.from_config()``. Ensures the database connection is
    always closed, even when an exception is raised inside the ``with`` block.

    Example::

        with Migrator.from_config("db/environments/prod.yaml") as m:
            result = m.status()
            if result.has_pending:
                m.up()
    """

    #: What opens the connection when no ``connection_factory`` is given: core's
    #: own factory, looked up when the session enters (never at import). Class
    #: attributes so an embedder or a test can set them once for every session.
    default_connection_factory: ClassVar[Callable[[Any], Connection]] = staticmethod(
        lambda url: _core_connection().create_connection(url)
    )
    default_migration_loader: ClassVar[Callable[[Path], type]] = staticmethod(
        lambda path: _core_connection().load_migration_class(path)
    )

    def __init__(
        self,
        config: Environment | None,
        migrations_dir: Path,
        *,
        database_url_override: str | None = None,
        migration_table_override: str | None = None,
        command: str | None = None,
        connection_factory: Callable[[Any], Connection] | None = None,
        migration_loader: Callable[[Path], type] | None = None,
    ) -> None:
        self._config = config
        self._connection_factory = connection_factory
        self._migration_loader = migration_loader
        self._migrations_dir = migrations_dir
        self._conn: Connection | None = None
        self._migrator: Migrator | None = None
        self._database_url_override = database_url_override
        self._migration_table_override = migration_table_override
        self._command = command  # recorded in the lock-holder metadata (#147)
        self._owns_connection = True

    @property
    def connection_factory(self) -> Callable[[Any], Connection]:
        """What opens the connection: the injected factory, else the class default (read when used)."""
        return self._connection_factory or type(self).default_connection_factory

    @connection_factory.setter
    def connection_factory(self, factory: Callable[[Any], Connection] | None) -> None:
        self._connection_factory = factory

    @property
    def migration_loader(self) -> Callable[[Path], type]:
        """What turns a migration file into a class: injected, else the class default."""
        return self._migration_loader or type(self).default_migration_loader

    @migration_loader.setter
    def migration_loader(self, loader: Callable[[Path], type] | None) -> None:
        self._migration_loader = loader

    @classmethod
    def attached(
        cls,
        migrator: Migrator,
        migrations_dir: Path,
        *,
        config: Environment | None = None,
        command: str | None = None,
    ) -> MigratorSession:
        """A session over an engine that already owns its connection.

        The caller keeps ownership: leaving the ``with`` block does not close
        the connection. This is how :meth:`Migrator.migrate_up` runs the one
        apply loop without opening a second connection.
        """
        session = cls(config, migrations_dir, command=command)
        session._conn = migrator.connection
        session._migrator = migrator
        session._owns_connection = False
        return session

    def __enter__(self) -> MigratorSession:
        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.create_connection and have it intercepted here.
        # Reason: import cycle (the module is partially initialised when this import runs at module level)
        import confiture.core.migrator as _m

        if self._migrator is not None:  # attached to a live engine
            return self

        if self._database_url_override is not None:
            url: str = self._database_url_override
            migration_table: str = self._migration_table_override or "tb_confiture"
        elif self._config is not None:
            url = self._config.database_url
            migration_table = self._config.migration.tracking_table
        else:
            raise ConfigurationError(
                "MigratorSession requires either a config or database_url_override",
                resolution_hint=(
                    "Use Migrator.from_config(...) or pass database_url_override= "
                    "to MigratorSession directly."
                ),
            )

        self._conn = self.connection_factory(url)
        try:
            self._migrator = _m.Migrator(
                connection=self._conn,
                migration_table=migration_table,
            )
        # Reason: resource guard: the connection must not leak on any exit, KeyboardInterrupt included
        except BaseException:
            # A rejected tracking-table name must not leak the connection.
            self._conn.close()
            self._conn = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._conn is not None and self._owns_connection:
            self._conn.close()
            self._conn = None

    @property
    def connection(self) -> Connection:
        """The session's live connection (inside ``with``)."""
        if self._conn is None:
            raise _not_entered()
        return self._conn

    @property
    def migrator(self) -> Migrator:
        """The session's engine (inside ``with``, or when attached)."""
        if self._migrator is None:
            raise _not_entered()
        return self._migrator

    def _lock_settings(self, lock_timeout: int | None, no_lock: bool | None) -> tuple[int, bool]:
        """Explicit arguments win; otherwise the environment's ``migration.locking`` block."""
        migration = getattr(self._config, "migration", None)
        return resolve_lock_settings(getattr(migration, "locking", None), lock_timeout, no_lock)

    # ------------------------------------------------------------------ #
    # Lock inspection                                                    #
    # ------------------------------------------------------------------ #

    def is_locked(self) -> bool:
        """Check if the migration lock is currently held by any process.

        Returns:
            True if another process holds the migration lock.

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
        """
        lock = MigrationLock(self.connection, LockConfig())
        return lock.is_locked()

    def get_lock_holder(self) -> dict[str, Any] | None:
        """Get diagnostic info about the process holding the migration lock.

        Returns:
            Dict with keys: pid, user, application, client_addr, started_at.
            None if no lock is held.

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
        """
        lock = MigrationLock(self.connection, LockConfig())
        return lock.get_lock_holder()

    # ------------------------------------------------------------------ #
    # High-level library methods                                         #
    # ------------------------------------------------------------------ #

    def status(self) -> StatusResult:
        """Get migration status: which migrations are applied, pending, or unknown.

        Queries the tracking table to determine applied vs pending migrations.
        If the tracking table doesn't exist, all migrations show as pending.

        Returns:
            :class:`~confiture.models.results.StatusResult` (its fields are documented there).


        Raises:
            ConfigurationError: If called outside ``with`` context manager.
                               Fix: ``with Migrator.from_config(...) as m: m.status()``
            SchemaError: If migration files cannot be parsed (invalid filename format).
            SQLError: If querying the tracking table fails (permission denied, etc.).

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     status = m.status()
            ...     print(f"Applied: {status.summary['applied']}")
            ...     print(f"Pending: {status.summary['pending']}")
        """
        return _reporting.status(self)

    def current_revision(self) -> CurrentRevision | None:
        """Return the latest applied migration revision (issue #141).

        Returns:
            A ``CurrentRevision`` for the most-recently-applied migration, or
            ``None`` when the tracking table exists but is empty (no migrations
            applied yet — a freshly-initialized database).

        Raises:
            ConfigurationError: If called outside the ``with`` context manager.
            PreconditionError: ``PRECON_1001`` when the tracking table is absent
                (confiture not initialized on this database) — exits 2 per #146.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     cur = m.current_revision()
            ...     print(cur.version if cur else "(none applied)")
        """
        return _reporting.current_revision(self)

    def up(
        self,
        *,
        target: str | None = None,
        dry_run: bool = False,
        dry_run_execute: bool = False,
        verify_checksums: bool = True,
        on_checksum_mismatch: str = "fail",
        force: bool = False,
        lock_timeout: int | None = None,
        no_lock: bool | None = None,
        require_reversible: bool = False,
        allow_destructive: bool = False,
        strict_mode: bool | None = None,
        auto_baseline: Path | None = None,
        install_view_helpers: bool | None = None,
        on_event: UpObserver | None = None,
        batch: Any | None = None,
    ) -> MigrateUpResult:
        """Apply pending migrations up to target version.

        Applies pending migrations in sequence. All migrations are executed
        within a single transaction (atomic operation).

        Args:
            target: Target migration version to apply up to (YYYYMMDDHHMMSS format).
                    If None, applies all pending migrations.
                    Example: "20260228180602"
            dry_run: If True, analyze migrations without executing SQL.
                     Shows which migrations would be applied.
            dry_run_execute: If True, execute all SQL inside a SAVEPOINT then
                     roll back. Catches real SQL errors without persisting changes.
                     Mutually exclusive with ``dry_run``.
            verify_checksums: If True, verify the checksums of every applied
                     migration file against the ledger before applying anything
                     (skipped under ``force``). A mismatch raises
                     :class:`~confiture.core.checksum.ChecksumVerificationError`
                     under the default ``on_checksum_mismatch="fail"``.
            on_checksum_mismatch: ``"fail"`` (raise), ``"warn"`` (continue, report
                     the mismatches in ``warnings``) or ``"ignore"``.
            force: If True, re-apply all migrations including already-applied ones.
            lock_timeout: Lock timeout in milliseconds; ``None`` reads
                ``migration.locking.timeout_ms`` from the environment (else 30000).
            no_lock: Skip distributed locking; ``None`` reads
                ``migration.locking.enabled`` from the environment (else lock).
            require_reversible: If True, abort before applying any migration
                     if any pending migration lacks a ``.down.sql`` file.
            strict_mode: Fail on warnings/notices. None (default) takes the
                     environment's ``migration.strict_mode``.
            auto_baseline: Snapshots directory for self-baselining a database
                     whose ledger is missing (the CLI's ``--auto-detect-baseline``).
                     None (default) never baselines.
            install_view_helpers: Install the view helper functions before
                     applying. None (default) follows ``migration.view_helpers: auto``.
            on_event: Observer for live progress
                     (:class:`~confiture.core.migrator.UpEvent`): lock acquired,
                     each pending file, applying/applied/failed, the superuser halt.
            batch: A :class:`~confiture.core.large_tables.BatchConfig` set on every
                     migration as ``batch_config`` before it runs (the CLI's
                     ``--batched``). None leaves the class defaults.

        Returns:
            :class:`~confiture.models.results.MigrateUpResult` (its fields are documented there).


        Raises:
            ConfigurationError: If used outside ``with`` context manager, or
                ``auto_baseline`` refuses (ledger elsewhere, snapshots missing).
            MigrationError: If the migrations directory does not exist.
            ChecksumVerificationError: A tampered applied file under
                ``on_checksum_mismatch="fail"``.
            LockAcquisitionError: The migration lock could not be taken.

        A failing migration is not an exception: the result has ``success=False``,
        its message in ``errors`` and the exception itself in ``failure``.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.up()
            ...     if result.success:
            ...         print(f"Applied {len(result.migrations_applied)} migrations")
            ...     else:
            ...         for error in result.errors:
            ...             print(f"ERROR: {error}")
        """
        lock_timeout, no_lock = self._lock_settings(lock_timeout, no_lock)
        return _apply_loop.up(
            self,
            target=target,
            dry_run=dry_run,
            dry_run_execute=dry_run_execute,
            verify_checksums=verify_checksums,
            on_checksum_mismatch=on_checksum_mismatch,
            force=force,
            lock_timeout=lock_timeout,
            no_lock=no_lock,
            require_reversible=require_reversible,
            allow_destructive=allow_destructive,
            strict_mode=strict_mode,
            auto_baseline=auto_baseline,
            install_view_helpers=install_view_helpers,
            on_event=on_event,
            batch=batch,
        )

    def apply_one(
        self,
        version: str,
        *,
        applied_by: str | None = None,
        lock_timeout: int | None = None,
        no_lock: bool | None = None,
    ) -> MigrationApplied:
        """Apply exactly one migration by version, under the migration lock.

        The engine behind ``confiture migrate apply-as``: the operator applies
        the migration :meth:`up` halted on (``requires_superuser=True``) through
        a session opened on the privileged role's URL, then re-runs ``up()``.

        Args:
            version: The migration version to apply.
            applied_by: Recorded in the ledger's ``applied_by`` column.
            lock_timeout: Lock acquisition timeout in milliseconds; ``None`` reads
                ``migration.locking`` from the environment.
            no_lock: Skip distributed locking; ``None`` reads ``migration.locking``.

        Raises:
            MigrationError: ``MIGR_001`` if the version is already applied,
                ``MIGR_100`` if no file carries it; whatever the migration raises.
            LockAcquisitionError: The migration lock could not be taken.
        """
        lock_timeout, no_lock = self._lock_settings(lock_timeout, no_lock)
        return _apply_loop.apply_one(
            self, version, applied_by=applied_by, lock_timeout=lock_timeout, no_lock=no_lock
        )

    def down(
        self,
        *,
        steps: int = 1,
        dry_run: bool = False,
        lock_timeout: int | None = None,
        no_lock: bool | None = None,
        command: str | None = None,
    ) -> MigrateDownResult:
        """Roll back applied migrations in reverse order.

        Rolls back the most recently applied migrations. Each migration's
        ``down()`` method or ``.down.sql`` file is executed.

        Acquires the migration advisory lock for the duration of the rollback
        (issue #142) so it is atomic w.r.t. a concurrent ``up()``/``down()`` —
        previously ``down()`` ran unlocked, a latent race. Pass ``no_lock=True``
        to skip (dangerous in multi-pod environments).

        Args:
            steps: Number of migrations to roll back (default: 1).
                   Migrations are rolled back in reverse chronological order.
            dry_run: If True, analyze without executing SQL (no lock taken).
            lock_timeout: Lock acquisition timeout in milliseconds (default: 30000).
            no_lock: If True, skip distributed locking.

        Returns:
            :class:`~confiture.models.results.MigrateDownResult` (its fields are documented there).


        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            MigrationError: If a migration file cannot be loaded.
            RollbackError: If rollback SQL execution fails.
            LockAcquisitionError: If the migration lock cannot be acquired.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.down(steps=2)
            ...     if result.success:
            ...         print(f"Rolled back {len(result.migrations_rolled_back)} migrations")
        """
        lock_timeout, no_lock = self._lock_settings(lock_timeout, no_lock)
        return _rollback_loop.down(
            self,
            steps=steps,
            dry_run=dry_run,
            lock_timeout=lock_timeout,
            no_lock=no_lock,
            command=command,
        )

    def down_to(
        self,
        target: str,
        *,
        dry_run: bool = False,
        lock_timeout: int | None = None,
        no_lock: bool | None = None,
        command: str | None = None,
    ) -> DownToResult:
        """Roll back every migration newer than ``target`` (issue #142).

        Computes the rollback set via the pure planner, validates that *all*
        required ``.down.sql`` files exist up front (refusing atomically if any
        is missing — no partial application), then rolls back newest → oldest
        under the migration lock so the read-and-rollback is atomic w.r.t. other
        writers.

        Args:
            target: The revision to roll back to (kept applied).
            dry_run: If True, compute + validate the plan but execute nothing.
            lock_timeout: Lock acquisition timeout in milliseconds; ``None`` reads
                ``migration.locking`` from the environment.
            no_lock: Skip distributed locking; ``None`` reads ``migration.locking``.

        Returns:
            DownToResult with from/to/rolled_back/skipped/errors.

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            RollbackError: ``ROLLBACK_600`` if a required ``.down.sql`` is missing.
            MigrationError: ``MIGR_100`` for an unknown target, or a
                forward-move ("use migrate up --target") for a target newer than
                current.
            LockAcquisitionError: If the migration lock cannot be acquired.
        """
        lock_timeout, no_lock = self._lock_settings(lock_timeout, no_lock)
        return _rollback_loop.down_to(
            self,
            target,
            dry_run=dry_run,
            lock_timeout=lock_timeout,
            no_lock=no_lock,
            command=command,
        )

    def reinit(
        self,
        *,
        through: str | None = None,
        dry_run: bool = False,
    ) -> MigrateReinitResult:
        """Reset tracking table and re-baseline from migration files on disk.

        Deletes all entries from the tracking table, then marks migrations
        as applied (without executing SQL). Useful after schema consolidation.

        Args:
            through: Mark migrations as applied through this version.
                     If None, marks all migration files on disk as applied.
            dry_run: If True, show what would happen without making changes.

        Returns:
            :class:`~confiture.models.results.MigrateReinitResult` (its fields are documented there).


        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            MigrationError: If tracking table operations fail.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.reinit(through="20260228180602")
            ...     print(f"Marked {len(result.migrations_marked)} migrations")
        """
        engine = self.migrator
        engine.initialize()
        return engine.reinit(through=through, dry_run=dry_run, migrations_dir=self._migrations_dir)

    def rebuild(
        self,
        *,
        drop_schemas: bool = False,
        dry_run: bool = False,
        apply_seeds: bool = False,
        backup_tracking: bool = False,
    ) -> MigrateRebuildResult:
        """Rebuild database from DDL and bootstrap tracking table.

        Orchestrates a full rebuild: drops schemas (optional), applies DDL,
        bootstraps tracking, and optionally applies seeds.

        Args:
            drop_schemas: Drop all user schemas before rebuild.
            dry_run: Report what would happen without executing.
            apply_seeds: Apply seed files after DDL.
            backup_tracking: Dump tracking table before clearing.

        Returns:
            :class:`~confiture.models.results.MigrateRebuildResult` (its fields are documented there).


        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            RebuildError: If schema build or DDL application fails.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.rebuild(drop_schemas=True, apply_seeds=True)
            ...     if result.success:
            ...         print(f"Rebuilt with {result.ddl_statements_executed} DDL statements")
        """
        return self.migrator.rebuild(
            drop_schemas=drop_schemas,
            dry_run=dry_run,
            apply_seeds=apply_seeds,
            backup_tracking=backup_tracking,
            migrations_dir=self._migrations_dir,
            env_config=self._config,
        )

    def preflight(
        self,
        *,
        versions: list[str] | None = None,
    ) -> PreflightResult:
        """Pre-flight check for pending migrations.

        Verifies:
        - All pending .up.sql files have matching .down.sql (reversibility)
        - No pending migrations contain non-transactional statements
        - No duplicate migration versions on disk
        - Applied migration files haven't been tampered with (checksum, DB required)

        No database connection required for reversibility, non-transactional, and
        duplicate checks. Checksum verification is only performed when the session
        is entered (DB connected).

        Args:
            versions: Specific versions to check. If None and session is
                      entered (DB connected), checks pending migrations.
                      If None and session is NOT entered, checks ALL
                      migration files on disk.

        Returns:
            PreflightResult with per-migration analysis.
        """
        return _reporting.preflight(self, versions=versions)

    def run_against(
        self,
        pending_files: list[Path],
        against_url: str,
        *,
        allow_non_transactional: bool = False,
    ) -> PreflightAgainstResult:
        """Execute pending migrations via SAVEPOINTs, then roll back all DDL.

        Calls ``migration.up()`` directly — bypasses ``apply()``'s
        commit/tracking/hooks.  An outer SAVEPOINT envelopes the entire loop;
        the ``finally`` block rolls back to it, leaving the database in its
        original state (when ``allow_non_transactional=False``).

        Non-transactional migrations (``getattr(migration, 'transactional', True)
        is False``) contain statements that PostgreSQL rejects inside any
        transaction block (e.g. ``CREATE INDEX CONCURRENTLY``,
        ``ALTER TYPE … ADD VALUE``).

        - ``allow_non_transactional=False`` (default): such migrations are skipped
          and recorded as ``skipped=True``.  The DB is always left unchanged.
        - ``allow_non_transactional=True``: the current transaction is committed
          (releasing the outer SAVEPOINT), then the migration runs in autocommit
          mode.  When a non-transactional migration is encountered, the outer
          SAVEPOINT is released via commit().  Any transactional DDL that executed
          before that point is also permanently committed — not just the
          non-transactional migration.  The preflight DB must be reprovisioned
          before the next run (``db_consumed=True``).

        Args:
            pending_files: Migration files to test, in version order.
            against_url: URL of the preflight database (used in result only;
                connection is already open on ``self._conn``).
            allow_non_transactional: When ``True``, non-transactional migrations
                run outside the SAVEPOINT at the cost of consuming the preflight DB.

        Returns:
            PreflightAgainstResult with one entry per migration.

        Raises:
            ConfigurationError: If called outside a ``with`` block (``self._conn``
                is ``None``).
        """
        return _replay.run_against(
            self, pending_files, against_url, allow_non_transactional=allow_non_transactional
        )


# Avoid circular import: Migrator is defined in engine.py but MigratorSession
# references it. We import it here so the type annotation and runtime value work.
from confiture.core._migrator.engine import Migrator  # noqa: E402
