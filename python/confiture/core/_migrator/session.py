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

from confiture.core._migrator import policy as _policy
from confiture.core._migrator.events import UpObserver, emit
from confiture.core.checksum import (
    ChecksumConfig,
    ChecksumMismatchBehavior,
    MigrationChecksumVerifier,
)
from confiture.core.locking import LockConfig, MigrationLock
from confiture.exceptions import MigrationError


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
        self._migrator = _m.Migrator(
            connection=self._conn,
            migration_table=migration_table,
        )
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
        from datetime import datetime

        from confiture.exceptions import ConfigurationError
        from confiture.models.results import MigrationInfo, StatusResult

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )

        assert self._config is not None
        tracking_table = self._config.migration.tracking_table

        # Discover migration files (Python and SQL)
        if not self._migrations_dir.exists():
            return StatusResult(
                migrations=[],
                tracking_table_exists=False,
                tracking_table=tracking_table,
                summary={"applied": 0, "pending": 0, "total": 0},
            )

        py_files = list(self._migrations_dir.glob("*.py"))
        sql_files = list(self._migrations_dir.glob("*.up.sql"))
        migration_files = sorted(py_files + sql_files, key=lambda f: f.name.split("_")[0])

        if not migration_files:
            table_exists = self._migrator.tracking_table_exists()
            return StatusResult(
                migrations=[],
                tracking_table_exists=table_exists,
                tracking_table=tracking_table,
                summary={"applied": 0, "pending": 0, "total": 0},
            )

        # Query tracking table
        table_exists = self._migrator.tracking_table_exists()
        applied_versions: set[str] = set()
        applied_at_by_version: dict[str, datetime | None] = {}

        if table_exists:
            applied_versions = set(self._migrator.get_applied_versions())
            for row in self._migrator.get_applied_migrations_with_timestamps():
                raw_ts = row.get("applied_at")
                if raw_ts is not None and isinstance(raw_ts, str):
                    try:
                        applied_at_by_version[row["version"]] = datetime.fromisoformat(raw_ts)
                    except ValueError:
                        applied_at_by_version[row["version"]] = None
                elif isinstance(raw_ts, datetime):
                    applied_at_by_version[row["version"]] = raw_ts
                else:
                    applied_at_by_version[row["version"]] = None

        # Build MigrationInfo list
        infos: list[MigrationInfo] = []
        for mf in migration_files:
            base_name = mf.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]
            parts = base_name.split("_", 1)
            version = parts[0] if parts else "???"
            name = parts[1] if len(parts) > 1 else base_name

            migration_status = (
                "applied" if (table_exists and version in applied_versions) else "pending"
            )

            at = applied_at_by_version.get(version) if migration_status == "applied" else None
            infos.append(
                MigrationInfo(version=version, name=name, status=migration_status, applied_at=at)
            )

        applied_count = sum(1 for m in infos if m.status == "applied")
        pending_count = sum(1 for m in infos if m.status == "pending")

        return StatusResult(
            migrations=infos,
            tracking_table_exists=table_exists,
            tracking_table=tracking_table,
            summary={"applied": applied_count, "pending": pending_count, "total": len(infos)},
        )

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
        from confiture.exceptions import ConfigurationError, DatabaseNotInitializedError
        from confiture.models.results import CurrentRevision

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )

        # MANDATORY probe: get_current_revision_row() raises psycopg's
        # UndefinedTable on an absent table — it does NOT return None. Translate
        # "absent" → PRECON_1001 (exit 2); reserve None for "exists but empty".
        if not self._migrator.tracking_table_exists():
            raise DatabaseNotInitializedError("Database not initialized (tracking table absent)")

        row = self._migrator.get_current_revision_row()
        if row is None:
            return None
        return CurrentRevision(
            version=row["version"],
            name=row["name"],
            applied_at=row["applied_at"],
            checksum=row.get("checksum"),
        )

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

        import confiture.core.migrator as _m

        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.load_migration_class and confiture.core.migrator.MigrationLock.
        from confiture.exceptions import ConfigurationError

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )

        if dry_run and dry_run_execute:
            raise ConfigurationError(
                "Cannot use both dry_run and dry_run_execute",
                resolution_hint="Use dry_run for analysis-only, or dry_run_execute for SAVEPOINT-based verification.",
            )

        if not self._migrations_dir.exists():
            raise MigrationError(
                f"Migrations directory not found: {self._migrations_dir.absolute()}",
                resolution_hint=f"Create the migrations directory at {self._migrations_dir} or run 'confiture migrate generate' to scaffold it",
            )

        # Everything from here runs under the migration lock (ENG-03): the plan
        # is made against the ledger as the lock holder sees it, so a second
        # deployer that waited for the lock finds nothing left to apply instead
        # of failing on what the first one just recorded — and two first-run
        # deployers cannot race the ledger CREATE.
        lock_config = _m.LockConfig(
            enabled=not no_lock, timeout_ms=lock_timeout, command=self._command
        )
        lock = _m.MigrationLock(self._conn, lock_config)
        with lock.acquire():
            if not no_lock:
                emit(on_event, "lock_acquired")
            return self._up_under_lock(
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

    def _plan_under_lock(self, *, force: bool) -> tuple[list[Path], list[str]]:
        """Initialize the ledger and discover what to apply — the caller holds the lock.

        Returns:
            ``(pending_files, skipped_versions)``: the files to apply (every file
            when *force*), and the versions the ledger already records.
        """
        assert self._migrator is not None
        self._migrator.initialize()

        # Resolve migrations to apply
        all_files = self._migrator.find_migration_files(migrations_dir=self._migrations_dir)
        if force:
            pending_files = all_files
        else:
            pending_files = self._migrator.find_pending(migrations_dir=self._migrations_dir)

        apply_versions = {self._migrator._version_from_filename(f.name) for f in pending_files}
        skipped_versions = [
            self._migrator._version_from_filename(f.name)
            for f in all_files
            if self._migrator._version_from_filename(f.name) not in apply_versions
        ]

        return pending_files, skipped_versions

    def _verify_checksums(self, *, enabled: bool, on_mismatch: str) -> tuple[bool, list[str]]:
        """Check every applied migration file against the ledger — the caller holds the lock.

        Returns:
            ``(verified, warnings)``: *verified* is True only when the verifier
            ran and found no mismatch; *warnings* carries the mismatches under
            ``"warn"``. Under ``"fail"`` a mismatch raises
            :class:`~confiture.core.checksum.ChecksumVerificationError`.
        """
        assert self._migrator is not None
        if not enabled:
            return False, []
        behaviour = ChecksumMismatchBehavior(on_mismatch)
        verifier = MigrationChecksumVerifier(
            self._conn,
            ChecksumConfig(enabled=True, on_mismatch=behaviour),
            migration_table=self._migrator.migration_table,
        )
        mismatches = verifier.verify_all(self._migrations_dir)
        if not mismatches:
            return True, []
        return False, [
            f"Checksum mismatch: {m.version}_{m.name} was modified after it was applied"
            for m in mismatches
        ]

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
        import time as _time

        import confiture.core.migrator as _m
        from confiture.models.results import (
            MigrateUpResult,
            MigrationApplied,
            SkippedMigration,
        )

        assert self._migrator is not None
        if auto_baseline is not None:
            _policy.auto_baseline(
                conn=self._conn,
                migrator=self._migrator,
                migrations_dir=self._migrations_dir,
                snapshots_dir=auto_baseline,
                on_event=on_event,
            )
        pending_files, skipped_versions = self._plan_under_lock(force=force)
        if _policy.wants_view_helpers(install_view_helpers, self._config):
            _policy.install_view_helpers(self._conn, on_event)
        checksums_verified, checksum_warnings = self._verify_checksums(
            enabled=verify_checksums and not force, on_mismatch=on_checksum_mismatch
        )
        if checksums_verified:
            emit(on_event, "checksums_verified")
        effective_strict = _policy.resolve_strict_mode(strict_mode, self._config)
        pending_versions: list[str] = []
        for migration_file in pending_files:
            version, name = _label(migration_file)
            pending_versions.append(version)
            emit(on_event, "pending", version=version, name=name)

        # Dry-run: return without applying
        if dry_run:
            return MigrateUpResult(
                success=True,
                migrations_applied=[],
                total_execution_time_ms=0,
                checksums_verified=checksums_verified,
                dry_run=True,
                skipped=skipped_versions,
                warnings=checksum_warnings,
                pending=pending_versions,
            )

        if not pending_files:
            return MigrateUpResult(
                success=True,
                migrations_applied=[],
                total_execution_time_ms=0,
                checksums_verified=checksums_verified,
                dry_run=False,
                skipped=skipped_versions,
                warnings=checksum_warnings,
            )

        # Reversibility gate — check before any SQL execution
        if require_reversible:
            preflight_result = self.preflight()
            if not preflight_result.all_reversible:
                names = ", ".join(m.version for m in preflight_result.irreversible)
                return MigrateUpResult(
                    success=False,
                    migrations_applied=[],
                    total_execution_time_ms=0,
                    checksums_verified=checksums_verified,
                    dry_run=False,
                    errors=[
                        f"Irreversible migrations detected (missing .down.sql): {names}. "
                        f"Use require_reversible=False or add .down.sql files."
                    ],
                    skipped=skipped_versions,
                )

        # SAVEPOINT-based dry-run execution
        if dry_run_execute:
            return self._up_dry_run_execute(
                pending_files=pending_files,
                target=target,
                force=force,
                checksums_verified=checksums_verified,
                skipped_versions=skipped_versions,
                checksum_warnings=checksum_warnings,
                strict_mode=effective_strict,
                on_event=on_event,
            )

        migrations_applied: list[MigrationApplied] = []
        skipped_superuser: list[SkippedMigration] = []
        pending_after_halt: list[str] = []
        total_execution_time_ms = 0
        failed_exception: Exception | None = None
        halted = False

        try:
            for idx, migration_file in enumerate(pending_files):
                migration_class = _m.load_migration_class(migration_file)
                migration = migration_class(connection=self._conn)
                _apply_strict_mode(migration, effective_strict)

                # Stop at target version
                if target and migration.version > target:
                    emit(on_event, "target_reached", version=migration.version, name=migration.name)
                    break

                # Issue #137 — halt-at-first-skip for requires_superuser.
                # No dependency cascade exists in the model, so the safe
                # behavior is to stop the chain and surface a recovery
                # hint via the formatter.  Later migrations are reported
                # as pending rather than silently applied.
                # ``is True`` rather than truthiness so MagicMock-based
                # test doubles don't accidentally trip the halt path.
                if getattr(migration, "requires_superuser", False) is True:
                    emit(on_event, "superuser_halt", version=migration.version, name=migration.name)
                    skipped_superuser.append(
                        SkippedMigration(
                            version=migration.version,
                            name=migration.name,
                            reason=(
                                "requires_superuser=True; resolve with "
                                f"`confiture migrate apply-as <role> {migration.version}`"
                            ),
                        )
                    )
                    pending_after_halt = [
                        self._migrator._version_from_filename(f.name)
                        for f in pending_files[idx + 1 :]
                    ]
                    halted = True
                    break

                emit(on_event, "applying", version=migration.version, name=migration.name)
                try:
                    start = _time.time()
                    self._migrator.apply(migration, force=force, migration_file=migration_file)
                    elapsed = int((_time.time() - start) * 1000)
                    total_execution_time_ms += elapsed
                    migrations_applied.append(
                        MigrationApplied(
                            version=migration.version,
                            name=migration.name,
                            execution_time_ms=elapsed,
                        )
                    )
                    emit(
                        on_event,
                        "applied",
                        version=migration.version,
                        name=migration.name,
                        elapsed_ms=elapsed,
                    )
                except Exception as exc:
                    failed_exception = exc
                    emit(
                        on_event,
                        "failed",
                        version=migration.version,
                        name=migration.name,
                        message=str(exc),
                    )
                    break
        except Exception as exc:
            if failed_exception is None:
                failed_exception = exc
                emit(on_event, "failed", message=str(exc))

        if failed_exception is not None:
            return MigrateUpResult(
                success=False,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=checksums_verified,
                dry_run=False,
                errors=[str(failed_exception)],
                failure=failed_exception,
                skipped=skipped_versions,
                skipped_superuser=skipped_superuser,
                pending=pending_after_halt,
            )

        return MigrateUpResult(
            success=not halted,
            migrations_applied=migrations_applied,
            total_execution_time_ms=total_execution_time_ms,
            checksums_verified=checksums_verified,
            dry_run=False,
            warnings=(["Force mode enabled"] if force else []) + checksum_warnings,
            skipped=skipped_versions,
            skipped_superuser=skipped_superuser,
            pending=pending_after_halt,
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
        import time as _time

        import confiture.core.migrator as _m
        from confiture.models.results import MigrateUpResult, MigrationApplied

        # Invariant: this helper only runs inside an active session (callers guard).
        assert self._conn is not None
        assert self._migrator is not None

        migrations_tested: list[MigrationApplied] = []
        total_time = 0
        failed_exception: Exception | None = None

        try:
            self._conn.execute("SAVEPOINT dry_run_execute")
            try:
                for migration_file in pending_files:
                    migration_class = _m.load_migration_class(migration_file)
                    migration = migration_class(connection=self._conn)
                    _apply_strict_mode(migration, strict_mode)

                    if target and migration.version > target:
                        emit(
                            on_event,
                            "target_reached",
                            version=migration.version,
                            name=migration.name,
                        )
                        break

                    if not getattr(migration, "transactional", True):
                        # Cannot run inside the SAVEPOINT: the autocommit path
                        # would commit everything tested so far.
                        skipped_versions.append(migration.version)
                        checksum_warnings = checksum_warnings + [
                            f"dry_run_execute: skipped {migration.version}_{migration.name} — "
                            "non-transactional migrations cannot run inside a SAVEPOINT"
                        ]
                        emit(
                            on_event,
                            "skipped_non_transactional",
                            version=migration.version,
                            name=migration.name,
                        )
                        continue

                    emit(on_event, "applying", version=migration.version, name=migration.name)
                    try:
                        start = _time.time()
                        self._migrator.apply(
                            migration,
                            force=force,
                            migration_file=migration_file,
                            commit=False,
                        )
                        elapsed = int((_time.time() - start) * 1000)
                        total_time += elapsed
                        migrations_tested.append(
                            MigrationApplied(
                                version=migration.version,
                                name=migration.name,
                                execution_time_ms=elapsed,
                            )
                        )
                        emit(
                            on_event,
                            "applied",
                            version=migration.version,
                            name=migration.name,
                            elapsed_ms=elapsed,
                        )
                    except Exception as exc:
                        failed_exception = exc
                        emit(
                            on_event,
                            "failed",
                            version=migration.version,
                            name=migration.name,
                            message=str(exc),
                        )
                        break
            finally:
                self._conn.execute("ROLLBACK TO SAVEPOINT dry_run_execute")
                self._conn.execute("RELEASE SAVEPOINT dry_run_execute")
        except Exception as exc:
            if failed_exception is None:
                failed_exception = exc

        if failed_exception is not None:
            return MigrateUpResult(
                success=False,
                migrations_applied=migrations_tested,
                total_execution_time_ms=total_time,
                checksums_verified=checksums_verified,
                dry_run=True,
                dry_run_execute=True,
                errors=[str(failed_exception)],
                failure=failed_exception,
                skipped=skipped_versions,
            )

        return MigrateUpResult(
            success=True,
            migrations_applied=migrations_tested,
            total_execution_time_ms=total_time,
            checksums_verified=checksums_verified,
            dry_run=True,
            dry_run_execute=True,
            skipped=skipped_versions,
            warnings=["dry_run_execute: all SQL executed successfully, changes rolled back"]
            + checksum_warnings,
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
        import time as _time

        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.load_migration_class.
        import confiture.core.migrator as _m
        from confiture.models.results import MigrationApplied

        assert self._migrator is not None

        migration_files = self._migrator.find_migration_files(migrations_dir=self._migrations_dir)
        by_version = {self._migrator._version_from_filename(f.name): f for f in migration_files}

        rolled_back: list[MigrationApplied] = []
        total_execution_time_ms = 0

        for version in versions:
            migration_file = by_version.get(version)
            if migration_file is None:
                continue

            migration_class = _m.load_migration_class(migration_file)
            migration = migration_class(connection=self._conn)

            if not dry_run:
                start = _time.time()
                self._migrator.rollback(migration)
                elapsed = int((_time.time() - start) * 1000)
                total_execution_time_ms += elapsed
            else:
                elapsed = 0

            rolled_back.append(
                MigrationApplied(
                    version=migration.version,
                    name=migration.name,
                    execution_time_ms=elapsed,
                )
            )

        return rolled_back, total_execution_time_ms

    def _reversible_versions(self) -> set[str]:
        """Set of discoverable versions that have a usable rollback.

        A ``.up.sql`` migration is reversible iff its sibling ``.down.sql``
        exists on disk; Python migrations are treated as reversible (they define
        ``down()``). This feeds the planner's ``down_available`` so an
        irreversible target is refused *before* any execution.
        """
        assert self._migrator is not None

        reversible: set[str] = set()
        for f in self._migrator.find_migration_files(migrations_dir=self._migrations_dir):
            version = self._migrator._version_from_filename(f.name)
            if f.name.endswith(".up.sql"):
                down_file = f.parent / f.name.replace(".up.sql", ".down.sql")
                if down_file.exists():
                    reversible.add(version)
            else:
                reversible.add(version)
        return reversible

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
        import time as _time

        import confiture.core.migrator as _m
        from confiture.exceptions import ConfigurationError, MigrationError
        from confiture.models.results import MigrationApplied

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )
        lock = _m.MigrationLock(
            self._conn,
            _m.LockConfig(enabled=not no_lock, timeout_ms=lock_timeout, command=self._command),
        )
        with lock.acquire():
            self._migrator.initialize()
            if version in set(self._migrator.get_applied_versions()):
                raise MigrationError(
                    f"Migration {version} is already applied.",
                    version=version,
                    error_code="MIGR_001",
                    context={"reason": "already_applied"},
                    resolution_hint="Nothing to do — the version is already in the tracking table.",
                )
            files = self._migrator.find_migration_files(migrations_dir=self._migrations_dir)
            matches = [f for f in files if self._migrator._version_from_filename(f.name) == version]
            if not matches:
                raise MigrationError(
                    f"No migration with version {version} in {self._migrations_dir}",
                    version=version,
                    error_code="MIGR_100",
                    resolution_hint="Check the version and --migrations-dir.",
                )
            migration_file = sorted(matches)[0]
            migration = _m.load_migration_class(migration_file)(connection=self._conn)
            start = _time.time()
            self._migrator.apply(migration, migration_file=migration_file, applied_by=applied_by)
            return MigrationApplied(
                version=migration.version,
                name=migration.name,
                execution_time_ms=int((_time.time() - start) * 1000),
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
        import confiture.core.migrator as _m
        from confiture.exceptions import ConfigurationError
        from confiture.models.results import MigrateDownResult

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )

        self._migrator.initialize()
        applied_versions = self._migrator.get_applied_versions()

        if not applied_versions:
            return MigrateDownResult(
                success=True,
                migrations_rolled_back=[],
                total_execution_time_ms=0,
            )

        versions_to_rollback = list(reversed(applied_versions[-steps:]))  # newest → oldest

        if dry_run:
            rolled_back, total_ms = self._rollback_sequence(versions_to_rollback, dry_run=True)
        else:
            lock_config = _m.LockConfig(
                enabled=not no_lock, timeout_ms=lock_timeout, command=command or self._command
            )
            lock = _m.MigrationLock(self._conn, lock_config)
            with lock.acquire():
                rolled_back, total_ms = self._rollback_sequence(versions_to_rollback, dry_run=False)

        return MigrateDownResult(
            success=True,
            migrations_rolled_back=rolled_back,
            total_execution_time_ms=total_ms,
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
        import confiture.core.migrator as _m
        from confiture.core._migrator.rollback_planner import (
            REASON_IRREVERSIBLE,
            REASON_TARGET_NEWER,
            plan_down_to,
        )
        from confiture.exceptions import ConfigurationError, MigrationError, RollbackError
        from confiture.models.results import DownToResult

        if self._migrator is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with Migrator.from_config(...) as m: ...",
            )

        self._migrator.initialize()
        applied = self._migrator.get_applied_versions()  # ASC
        known = {
            self._migrator._version_from_filename(f.name)
            for f in self._migrator.find_migration_files(migrations_dir=self._migrations_dir)
        }
        down_available = self._reversible_versions()

        plan = plan_down_to(applied, known, target, down_available)

        if not plan.valid:
            if plan.reason == REASON_IRREVERSIBLE:
                missing = ", ".join(plan.missing_down)
                raise RollbackError(
                    f"Cannot roll back to {target}: missing .down.sql for {missing}. "
                    f"Aborting without applying anything.",
                    error_code="ROLLBACK_600",
                    resolution_hint=(
                        f"Add the missing .down.sql file(s) for {missing}, or choose a "
                        f"target that does not require rolling back past them."
                    ),
                )
            if plan.reason == REASON_TARGET_NEWER:
                raise MigrationError(
                    f"Revision {target} is newer than the current revision — "
                    f"down-to only moves backward.",
                    error_code="MIGR_100",
                    resolution_hint="Use 'confiture migrate up --target' for forward moves.",
                )
            # unknown_revision
            raise MigrationError(
                f"Unknown revision: {target}.",
                error_code="MIGR_100",
                resolution_hint="Run 'confiture migrate status' or 'migrate current' "
                "to see known revisions.",
            )

        from_ = applied[-1] if applied else None

        if plan.noop:
            return DownToResult(from_=from_, to=target, rolled_back=[], noop=True)

        # Defensive: any computed version not actually applied (consistent
        # tracking table → empty).
        applied_set = set(applied)
        skipped = [v for v in plan.to_rollback if v not in applied_set]
        to_execute = [v for v in plan.to_rollback if v in applied_set]

        if dry_run:
            return DownToResult(from_=from_, to=target, rolled_back=to_execute, skipped=skipped)

        lock_config = _m.LockConfig(
            enabled=not no_lock, timeout_ms=lock_timeout, command=command or self._command
        )
        lock = _m.MigrationLock(self._conn, lock_config)
        with lock.acquire():
            self._rollback_sequence(to_execute, dry_run=False)

        return DownToResult(from_=from_, to=target, rolled_back=to_execute, skipped=skipped)

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
        from confiture.core.preflight import run_preflight

        # Determine which versions to check
        check_versions = versions
        if check_versions is None and self._migrator is not None:
            # Inside context: check pending migrations only
            status = self.status()
            check_versions = status.pending if status.pending else None

        result = run_preflight(self._migrations_dir, versions=check_versions)

        # Checksum verification (only when DB is connected)
        if self._conn is not None:
            # #182: verify_all() raises psycopg's UndefinedTable on an absent
            # ledger. preflight is an advisory aggregator, not a gate, so it
            # skips and reports rather than raising — consistent with the
            # probes in status() and current_revision().
            if self._migrator is not None and not self._migrator.tracking_table_exists():
                result.checksum_verified = False
                result.checksum_skipped_reason = (
                    "no migration ledger in this database — nothing recorded to "
                    "verify checksums against"
                )
                return result

            from confiture.core.checksum import (
                ChecksumConfig,
                ChecksumMismatchBehavior,
                MigrationChecksumVerifier,
            )

            config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
            verifier = MigrationChecksumVerifier(
                self._conn,
                config,
                migration_table=(
                    self._migrator.migration_table if self._migrator is not None else "tb_confiture"
                ),
            )
            mismatches = verifier.verify_all(self._migrations_dir)
            result.checksum_mismatches = [
                f"{m.version}_{m.name}: expected {(m.expected or '')[:12]}..., got {m.actual[:12]}..."
                for m in mismatches
            ]
            result.checksum_verified = True

        return result

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
        import time as _time

        import confiture.core.migrator as _m
        from confiture.exceptions import ConfigurationError
        from confiture.models.results import PreflightAgainstMigration, PreflightAgainstResult

        if self._conn is None:
            raise ConfigurationError(
                "MigratorSession must be used as a context manager",
                resolution_hint="Use: with MigratorSession(...) as s: s.run_against(...)",
            )

        results: list[PreflightAgainstMigration] = []
        db_consumed = False
        outer_sp = "preflight_run"
        outer_sp_active = True

        # Outer SAVEPOINT: ROLLBACK TO here at the end undoes all migration DDL.
        # No initialize() call — tracking table never needed (we skip apply()).
        self._conn.execute(f"SAVEPOINT {outer_sp}")
        try:
            for migration_file in pending_files:
                migration_class = _m.load_migration_class(migration_file)
                migration = migration_class(connection=self._conn)

                # Non-transactional migration: cannot run inside a SAVEPOINT.
                # Use getattr with default True so migrations without the attribute
                # are treated as transactional (safe — they run inside SAVEPOINT).
                if not getattr(migration, "transactional", True):
                    if not allow_non_transactional:
                        results.append(
                            PreflightAgainstMigration(
                                version=migration.version,
                                name=migration.name,
                                success=False,
                                skipped=True,
                                skipped_reason=("non-transactional: cannot run inside SAVEPOINT"),
                            )
                        )
                        continue

                    # allow_non_transactional=True: commit() ends the outer SAVEPOINT
                    # and permanently applies ALL DDL executed so far — including any
                    # transactional migrations that ran before this one.
                    # The preflight DB is now consumed regardless of what follows.
                    if outer_sp_active:
                        self._conn.commit()
                        outer_sp_active = False
                    db_consumed = True

                    self._conn.autocommit = True
                    try:
                        start = _time.time()
                        migration.up()
                        elapsed = int((_time.time() - start) * 1000)
                        results.append(
                            PreflightAgainstMigration(
                                version=migration.version,
                                name=migration.name,
                                success=True,
                                execution_time_ms=elapsed,
                            )
                        )
                    except Exception as exc:
                        results.append(
                            PreflightAgainstMigration(
                                version=migration.version,
                                name=migration.name,
                                success=False,
                                error=str(exc),
                            )
                        )
                    finally:
                        self._conn.autocommit = False
                    continue

                # Transactional migration: per-migration SAVEPOINT.
                per_sp = f"sp_{migration.version}"
                self._conn.execute(f"SAVEPOINT {per_sp}")
                try:
                    start = _time.time()
                    migration.up()  # Direct call — no commit, no tracking
                    elapsed = int((_time.time() - start) * 1000)
                    self._conn.execute(f"RELEASE SAVEPOINT {per_sp}")
                    results.append(
                        PreflightAgainstMigration(
                            version=migration.version,
                            name=migration.name,
                            success=True,
                            execution_time_ms=elapsed,
                        )
                    )
                except Exception as exc:
                    # ROLLBACK TO resets to before per_sp without destroying outer_sp.
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {per_sp}")
                    self._conn.execute(f"RELEASE SAVEPOINT {per_sp}")
                    results.append(
                        PreflightAgainstMigration(
                            version=migration.version,
                            name=migration.name,
                            success=False,
                            error=str(exc),
                        )
                    )
        finally:
            # Roll back all migration DDL — only meaningful when outer_sp is still
            # active (i.e. no non-transactional migration triggered a commit).
            if outer_sp_active:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {outer_sp}")
                self._conn.execute(f"RELEASE SAVEPOINT {outer_sp}")

        return PreflightAgainstResult(
            migrations=results,
            against_url=against_url,
            db_consumed=db_consumed,
        )


# Avoid circular import: Migrator is defined in engine.py but MigratorSession
# references it. We import it here so the type annotation and runtime value work.
from confiture.core._migrator.engine import Migrator  # noqa: E402


def _label(migration_file: Path) -> tuple[str, str]:
    """``(version, name)`` from a migration filename — ``.py`` or ``.up.sql``."""
    stem = migration_file.name
    for suffix in (".up.sql", ".py"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    version, _, name = stem.partition("_")
    return version, name


def _apply_strict_mode(migration: Any, strict: bool) -> None:
    """Strict mode from the session/config, unless the class already pins it."""
    if strict and not getattr(type(migration), "strict_mode", False):
        migration.strict_mode = True
