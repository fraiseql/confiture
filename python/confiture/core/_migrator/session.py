"""MigratorSession — context manager for managed migration sessions."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

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


from confiture.core._migrator import apply_loop as _apply_loop
from confiture.core._migrator import replay as _replay
from confiture.core._migrator import reporting as _reporting
from confiture.core._migrator import rollback_loop as _rollback_loop
from confiture.core._migrator.events import UpObserver
from confiture.core.locking import LockConfig, MigrationLock


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

    def __init__(
        self,
        config: Environment | None,
        migrations_dir: Path,
        *,
        database_url_override: str | None = None,
        migration_table_override: str | None = None,
        command: str | None = None,
    ) -> None:
        self._config = config
        self._migrations_dir = migrations_dir
        self._conn: Connection | None = None
        self._migrator: Migrator | None = None
        self._database_url_override = database_url_override
        self._migration_table_override = migration_table_override
        self._command = command  # recorded in the lock-holder metadata (#147)
        self._owns_connection = True

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
            from confiture.exceptions import ConfigurationError

            raise ConfigurationError(
                "MigratorSession requires either a config or database_url_override",
                resolution_hint=(
                    "Use Migrator.from_config(...) or pass database_url_override= "
                    "to MigratorSession directly."
                ),
            )

        self._conn = _m.create_connection(url)
        try:
            self._migrator = _m.Migrator(
                connection=self._conn,
                migration_table=migration_table,
            )
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
        from confiture.exceptions import ConfigurationError

        if self._conn is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )
        lock = MigrationLock(self._conn, LockConfig())
        return lock.is_locked()

    def get_lock_holder(self) -> dict[str, Any] | None:
        """Get diagnostic info about the process holding the migration lock.

        Returns:
            Dict with keys: pid, user, application, client_addr, started_at.
            None if no lock is held.

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
        """
        from confiture.exceptions import ConfigurationError

        if self._conn is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )
        lock = MigrationLock(self._conn, LockConfig())
        return lock.get_lock_holder()

    # ------------------------------------------------------------------ #
    # High-level library methods                                         #
    # ------------------------------------------------------------------ #

    def status(self) -> StatusResult:
        """Get migration status: which migrations are applied, pending, or unknown.

        Queries the tracking table to determine applied vs pending migrations.
        If the tracking table doesn't exist, all migrations show as pending.

        Returns:
            StatusResult with:
            - migrations: List of MigrationInfo (version, name, status, applied_at)
            - applied/pending: Shortcut properties for version lists
            - has_pending: True if any migrations need applying
            - summary: {"applied": N, "pending": N, "total": N}
            - tracking_table_exists: Whether tracking table is present

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
        lock_timeout: int = 30000,
        no_lock: bool = False,
        require_reversible: bool = False,
        strict_mode: bool | None = None,
        auto_baseline: Path | None = None,
        install_view_helpers: bool | None = None,
        on_event: UpObserver | None = None,
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
            lock_timeout: Lock timeout in milliseconds (default: 30000).
            no_lock: If True, skip distributed locking.
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

        Returns:
            MigrateUpResult with:
            - success: True if all migrations applied successfully
            - migrations_applied: List of MigrationApplied (serialized as "applied")
            - skipped: List of already-applied migration versions
            - total_execution_time_ms: Total time (serialized as "total_duration_ms")
            - errors: List of error messages if success=False
            - has_errors: Property — True if success=False and errors non-empty
            - error_summary: Property — first error message or None

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
            strict_mode=strict_mode,
            auto_baseline=auto_baseline,
            install_view_helpers=install_view_helpers,
            on_event=on_event,
        )

    def _plan_under_lock(self, *, force: bool) -> tuple[list[Path], list[str]]:
        """Initialize the ledger and discover what to apply — the caller holds the lock.

        Returns:
            ``(pending_files, skipped_versions)``: the files to apply (every file
            when *force*), and the versions the ledger already records.
        """
        return _apply_loop._plan_under_lock(self, force=force)

    def _verify_checksums(self, *, enabled: bool, on_mismatch: str) -> tuple[bool, list[str]]:
        """Check every applied migration file against the ledger — the caller holds the lock.

        Returns:
            ``(verified, warnings)``: *verified* is True only when the verifier
            ran and found no mismatch; *warnings* carries the mismatches under
            ``"warn"``. Under ``"fail"`` a mismatch raises
            :class:`~confiture.core.checksum.ChecksumVerificationError`.
        """
        return _apply_loop._verify_checksums(self, enabled=enabled, on_mismatch=on_mismatch)

    def _up_under_lock(
        self,
        *,
        target: str | None,
        dry_run: bool,
        dry_run_execute: bool,
        verify_checksums: bool,
        on_checksum_mismatch: str,
        force: bool,
        require_reversible: bool,
        strict_mode: bool | None = None,
        auto_baseline: Path | None = None,
        install_view_helpers: bool | None = None,
        on_event: UpObserver | None = None,
    ) -> MigrateUpResult:
        """The body of :meth:`up`, run while the migration lock is held."""
        return _apply_loop._up_under_lock(
            self,
            target=target,
            dry_run=dry_run,
            dry_run_execute=dry_run_execute,
            verify_checksums=verify_checksums,
            on_checksum_mismatch=on_checksum_mismatch,
            force=force,
            require_reversible=require_reversible,
            strict_mode=strict_mode,
            auto_baseline=auto_baseline,
            install_view_helpers=install_view_helpers,
            on_event=on_event,
        )

    def _up_dry_run_execute(
        self,
        *,
        pending_files: list[Path],
        target: str | None,
        force: bool,
        checksums_verified: bool,
        skipped_versions: list[str],
        checksum_warnings: list[str],
        strict_mode: bool = False,
        on_event: UpObserver | None = None,
    ) -> MigrateUpResult:
        """Execute pending migrations inside a SAVEPOINT, then roll back.

        This catches real SQL errors (syntax, constraints, type mismatches)
        without persisting any changes.

        Note:
            Non-transactional DDL (e.g. ``CREATE INDEX CONCURRENTLY``) cannot
            run inside a SAVEPOINT and will cause an error.
        """
        return _apply_loop._up_dry_run_execute(
            self,
            pending_files=pending_files,
            target=target,
            force=force,
            checksums_verified=checksums_verified,
            skipped_versions=skipped_versions,
            checksum_warnings=checksum_warnings,
            strict_mode=strict_mode,
            on_event=on_event,
        )

    def _rollback_sequence(self, versions: list[str], *, dry_run: bool = False) -> tuple[list, int]:
        """Roll back an ordered (newest → oldest) list of versions.

        The shared rollback loop behind both ``down(steps=N)`` and
        ``down_to(target)`` — keeps the two paths from diverging. Reuses the
        engine's ``rollback()`` (transactional vs. non-transactional handling
        lives there). Does NOT acquire the lock itself; callers wrap it.

        Returns:
            (rolled_back, total_execution_time_ms) where rolled_back is a list
            of MigrationApplied in the order rolled back.
        """
        return _rollback_loop._rollback_sequence(self, versions, dry_run=dry_run)

    def _reversible_versions(self) -> set[str]:
        """Set of discoverable versions that have a usable rollback.

        A ``.up.sql`` migration is reversible iff its sibling ``.down.sql``
        exists on disk; Python migrations are treated as reversible (they define
        ``down()``). This feeds the planner's ``down_available`` so an
        irreversible target is refused *before* any execution.
        """
        return _rollback_loop._reversible_versions(self)

    def apply_one(
        self,
        version: str,
        *,
        applied_by: str | None = None,
        lock_timeout: int = 30000,
        no_lock: bool = False,
    ) -> MigrationApplied:
        """Apply exactly one migration by version, under the migration lock.

        The engine behind ``confiture migrate apply-as``: the operator applies
        the migration :meth:`up` halted on (``requires_superuser=True``) through
        a session opened on the privileged role's URL, then re-runs ``up()``.

        Args:
            version: The migration version to apply.
            applied_by: Recorded in the ledger's ``applied_by`` column.
            lock_timeout: Lock acquisition timeout in milliseconds.
            no_lock: If True, skip distributed locking.

        Raises:
            MigrationError: ``MIGR_001`` if the version is already applied,
                ``MIGR_100`` if no file carries it; whatever the migration raises.
            LockAcquisitionError: The migration lock could not be taken.
        """
        return _apply_loop.apply_one(
            self, version, applied_by=applied_by, lock_timeout=lock_timeout, no_lock=no_lock
        )

    def down(
        self,
        *,
        steps: int = 1,
        dry_run: bool = False,
        lock_timeout: int = 30000,
        no_lock: bool = False,
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
            MigrateDownResult with:
            - success: True if all rollbacks succeeded
            - migrations_rolled_back: List of MigrationApplied (serialized as "rolled_back")
            - total_execution_time_ms: Total time (serialized as "total_duration_ms")
            - error: Error message if success=False

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
        lock_timeout: int = 30000,
        no_lock: bool = False,
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
            lock_timeout: Lock acquisition timeout in milliseconds.
            no_lock: If True, skip distributed locking.

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
            MigrateReinitResult with:
            - success: True if reinit succeeded
            - deleted_count: Number of tracking entries removed
            - migrations_marked: List of MigrationApplied (serialized as "marked")
            - total_execution_time_ms: Total time (serialized as "total_duration_ms")

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            MigrationError: If tracking table operations fail.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.reinit(through="20260228180602")
            ...     print(f"Marked {len(result.migrations_marked)} migrations")
        """
        from confiture.exceptions import ConfigurationError

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )
        self._migrator.initialize()
        return self._migrator.reinit(
            through=through, dry_run=dry_run, migrations_dir=self._migrations_dir
        )

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
            MigrateRebuildResult with:
            - success: True if rebuild completed
            - schemas_dropped: List of dropped schema names
            - ddl_statements_executed: Number of DDL statements applied
            - migrations_marked: Migrations marked as applied
            - verified: True/False/None — post-rebuild verification result
            - seeds_applied: Number of seed files applied (None if not requested)

        Raises:
            ConfigurationError: If used outside ``with`` context manager.
            RebuildError: If schema build or DDL application fails.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.rebuild(drop_schemas=True, apply_seeds=True)
            ...     if result.success:
            ...         print(f"Rebuilt with {result.ddl_statements_executed} DDL statements")
        """
        from confiture.exceptions import ConfigurationError

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )
        return self._migrator.rebuild(
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
