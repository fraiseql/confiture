"""MigratorSession — context manager for managed migration sessions."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import Connection

    from confiture.config.environment import Environment
    from confiture.models.results import (
        MigrateDownResult,
        MigrateRebuildResult,
        MigrateReinitResult,
        MigrateUpResult,
        PreflightResult,
        StatusResult,
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

    def __init__(self, config: Environment, migrations_dir: Path) -> None:
        self._config = config
        self._migrations_dir = migrations_dir
        self._conn: Connection | None = None
        self._migrator: Migrator | None = None

    def __enter__(self) -> MigratorSession:
        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.create_connection and have it intercepted here.
        import confiture.core.migrator as _m

        self._conn = _m.create_connection(self._config.database_url)
        self._migrator = Migrator(
            connection=self._conn,
            migration_table=self._config.migration.tracking_table,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
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

    def up(
        self,
        *,
        target: str | None = None,
        dry_run: bool = False,
        dry_run_execute: bool = False,
        verify_checksums: bool = True,
        force: bool = False,
        lock_timeout: int = 30000,
        no_lock: bool = False,
        require_reversible: bool = False,
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
            verify_checksums: If True, verify migration file checksums.
            force: If True, re-apply all migrations including already-applied ones.
            lock_timeout: Lock timeout in milliseconds (default: 30000).
            no_lock: If True, skip distributed locking.
            require_reversible: If True, abort before applying any migration
                     if any pending migration lacks a ``.down.sql`` file.

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
            ConfigurationError: If used outside ``with`` context manager.
            MigrationError: If a migration file cannot be loaded or executed.
            MigrationError: If the migrations directory does not exist.

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.up()
            ...     if result.success:
            ...         print(f"Applied {len(result.migrations_applied)} migrations")
            ...     else:
            ...         for error in result.errors:
            ...             print(f"ERROR: {error}")
        """
        import time as _time

        import confiture.core.migrator as _m

        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.load_migration_class and confiture.core.migrator.MigrationLock.
        from confiture.exceptions import ConfigurationError
        from confiture.models.results import MigrateUpResult, MigrationApplied

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

        # Dry-run: return without applying
        if dry_run:
            return MigrateUpResult(
                success=True,
                migrations_applied=[],
                total_execution_time_ms=0,
                checksums_verified=verify_checksums,
                dry_run=True,
                skipped=skipped_versions,
            )

        if not pending_files:
            return MigrateUpResult(
                success=True,
                migrations_applied=[],
                total_execution_time_ms=0,
                checksums_verified=verify_checksums,
                dry_run=False,
                skipped=skipped_versions,
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
                    checksums_verified=verify_checksums,
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
                verify_checksums=verify_checksums,
                lock_timeout=lock_timeout,
                no_lock=no_lock,
                skipped_versions=skipped_versions,
            )

        # Apply with distributed lock
        lock_config = _m.LockConfig(enabled=not no_lock, timeout_ms=lock_timeout)
        lock = _m.MigrationLock(self._conn, lock_config)

        migrations_applied: list[MigrationApplied] = []
        total_execution_time_ms = 0
        failed_exception: Exception | None = None

        try:
            with lock.acquire():
                for migration_file in pending_files:
                    migration_class = _m.load_migration_class(migration_file)
                    migration = migration_class(connection=self._conn)

                    # Stop at target version
                    if target and migration.version > target:
                        break

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
                    except Exception as exc:
                        failed_exception = exc
                        break
        except Exception as exc:
            if failed_exception is None:
                failed_exception = exc

        if failed_exception is not None:
            return MigrateUpResult(
                success=False,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=verify_checksums,
                dry_run=False,
                errors=[str(failed_exception)],
                skipped=skipped_versions,
            )

        return MigrateUpResult(
            success=True,
            migrations_applied=migrations_applied,
            total_execution_time_ms=total_execution_time_ms,
            checksums_verified=verify_checksums,
            dry_run=False,
            warnings=["Force mode enabled"] if force else [],
            skipped=skipped_versions,
        )

    def _up_dry_run_execute(
        self,
        *,
        pending_files: list[Path],
        target: str | None,
        force: bool,
        verify_checksums: bool,
        lock_timeout: int,
        no_lock: bool,
        skipped_versions: list[str],
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

        lock_config = _m.LockConfig(enabled=not no_lock, timeout_ms=lock_timeout)
        lock = _m.MigrationLock(self._conn, lock_config)

        migrations_tested: list[MigrationApplied] = []
        total_time = 0
        failed_exception: Exception | None = None

        try:
            with lock.acquire():
                self._conn.execute("SAVEPOINT dry_run_execute")
                try:
                    for migration_file in pending_files:
                        migration_class = _m.load_migration_class(migration_file)
                        migration = migration_class(connection=self._conn)

                        if target and migration.version > target:
                            break

                        try:
                            start = _time.time()
                            self._migrator.apply(
                                migration, force=force, migration_file=migration_file
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
                        except Exception as exc:
                            failed_exception = exc
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
                checksums_verified=verify_checksums,
                dry_run=True,
                dry_run_execute=True,
                errors=[str(failed_exception)],
                skipped=skipped_versions,
            )

        return MigrateUpResult(
            success=True,
            migrations_applied=migrations_tested,
            total_execution_time_ms=total_time,
            checksums_verified=verify_checksums,
            dry_run=True,
            dry_run_execute=True,
            skipped=skipped_versions,
            warnings=["dry_run_execute: all SQL executed successfully, changes rolled back"],
        )

    def down(
        self,
        *,
        steps: int = 1,
        dry_run: bool = False,
    ) -> MigrateDownResult:
        """Roll back applied migrations in reverse order.

        Rolls back the most recently applied migrations. Each migration's
        ``down()`` method or ``.down.sql`` file is executed.

        Args:
            steps: Number of migrations to roll back (default: 1).
                   Migrations are rolled back in reverse chronological order.
            dry_run: If True, analyze without executing SQL.

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

        Example:
            >>> with Migrator.from_config("db/environments/prod.yaml") as m:
            ...     result = m.down(steps=2)
            ...     if result.success:
            ...         print(f"Rolled back {len(result.migrations_rolled_back)} migrations")
        """
        import time as _time

        import confiture.core.migrator as _m

        # Import through confiture.core.migrator so tests can patch
        # confiture.core.migrator.load_migration_class.
        from confiture.exceptions import ConfigurationError
        from confiture.models.results import MigrateDownResult, MigrationApplied

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

        versions_to_rollback = applied_versions[-steps:]
        migration_files = self._migrator.find_migration_files(migrations_dir=self._migrations_dir)

        rolled_back: list[MigrationApplied] = []
        total_execution_time_ms = 0

        for version in reversed(versions_to_rollback):
            migration_file = next(
                (
                    f
                    for f in migration_files
                    if self._migrator._version_from_filename(f.name) == version
                ),
                None,
            )
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

        return MigrateDownResult(
            success=True,
            migrations_rolled_back=rolled_back,
            total_execution_time_ms=total_execution_time_ms,
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
            from confiture.core.checksum import (
                ChecksumConfig,
                ChecksumMismatchBehavior,
                MigrationChecksumVerifier,
            )

            config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
            verifier = MigrationChecksumVerifier(self._conn, config)
            mismatches = verifier.verify_all(self._migrations_dir)
            result.checksum_mismatches = [
                f"{m.version}_{m.name}: expected {m.expected[:12]}..., got {m.actual[:12]}..."
                for m in mismatches
            ]
            result.checksum_verified = True

        return result


# Avoid circular import: Migrator is defined in engine.py but MigratorSession
# references it. We import it here so the type annotation and runtime value work.
from confiture.core._migrator.engine import Migrator  # noqa: E402
