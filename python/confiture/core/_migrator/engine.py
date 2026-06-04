"""Migration executor — Migrator class."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confiture.config.environment import Environment
    from confiture.core._migrator.session import MigratorSession
    from confiture.models.results import (
        MigrateRebuildResult,
        MigrateReinitResult,
    )

import psycopg
import psycopg.pq
from psycopg import sql as pgsql

from confiture.core._migrator import apply as apply_impl
from confiture.core._migrator import baseline as baseline_impl
from confiture.core._migrator import discovery as discovery_impl
from confiture.core._migrator import factory
from confiture.core._migrator import rollback as rollback_impl
from confiture.core._migrator import state as state_impl
from confiture.core._migrator._constants import (
    _POSTGRES_RESERVED_WORDS,
    _VALID_TABLE_RE,
)
from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)
from confiture.core.checksum import (
    ChecksumConfig,
)
from confiture.core.dry_run import DryRunResult
from confiture.core.hooks import HookRegistry
from confiture.core.hooks.context import ExecutionContext
from confiture.core.locking import LockConfig
from confiture.core.progress import ProgressManager
from confiture.exceptions import SQLError
from confiture.models.migration import Migration

logger = logging.getLogger(__name__)


class Migrator:
    """Executes database migrations and tracks their state.

    The Migrator class is responsible for:
    - Creating and managing the tb_confiture tracking table
    - Applying migrations (running up() methods)
    - Rolling back migrations (running down() methods)
    - Recording execution time and checksums
    - Ensuring transaction safety

    Example:
        >>> conn = psycopg.connect("postgresql://localhost/mydb")
        >>> migrator = Migrator(connection=conn)
        >>> migrator.initialize()
        >>> migrator.apply(my_migration)
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        migration_table: str = "tb_confiture",
    ):
        """Initialize migrator with database connection.

        Args:
            connection: psycopg3 database connection
            migration_table: Name of the tracking table. May be schema-qualified
                (e.g. ``public.tb_confiture``). Defaults to ``tb_confiture``.

        Raises:
            ValueError: If migration_table contains characters that are not
                safe for use as an unquoted SQL identifier.
        """
        if not _VALID_TABLE_RE.match(migration_table):
            raise ValueError(
                f"Invalid migration_table name: {migration_table!r}. "
                "Use letters, digits, and underscores only, optionally "
                "schema-qualified (e.g. 'public.tb_confiture')."
            )
        table_base = migration_table.split(".")[-1].lower()
        if table_base in _POSTGRES_RESERVED_WORDS:
            raise ValueError(
                f"Migration table name {migration_table!r} is a PostgreSQL reserved word. "
                "Choose a descriptive name like 'tb_confiture' or 'schema_migrations'."
            )
        self.connection = connection
        self.migration_table = migration_table
        # Unqualified table name — used for index names and information_schema lookups
        self._table_base = migration_table.split(".")[-1]
        # Schema part (None when not schema-qualified)
        parts = migration_table.split(".", 1)
        self._table_schema: str | None = parts[0] if len(parts) == 2 else None

        # Hook registry for lifecycle events
        self.hook_registry = HookRegistry[ExecutionContext]()

    def register_hook(self, phase: Any, hook: Any) -> None:
        """Register a hook for a migration lifecycle phase.

        Args:
            phase: Hook phase (e.g., HookPhase.BEFORE_EXECUTE)
            hook: Hook instance to register
        """
        self.hook_registry.register(phase, hook)

    @property
    def _table_ident(self) -> pgsql.Identifier:
        """Return a properly quoted SQL identifier for the tracking table."""
        if self._table_schema is not None:
            return pgsql.Identifier(self._table_schema, self._table_base)
        return pgsql.Identifier(self._table_base)

    def _execute_sql(
        self,
        query: str | pgsql.Composable,
        params: tuple[str, ...] | None = None,
    ) -> None:
        """Execute SQL with detailed error reporting.

        Args:
            sql: SQL statement to execute
            params: Optional query parameters

        Raises:
            SQLError: If SQL execution fails with detailed context
        """
        try:
            with self.connection.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
        except Exception as e:
            if isinstance(query, pgsql.Composable):
                try:
                    sql_text = query.as_string(self.connection)
                except Exception:  # noqa: BLE001 — fall through to context-free render
                    sql_text = query.as_string(None)
            else:
                sql_text = str(query)
            raise SQLError(
                sql_text,
                params,
                e,
                resolution_hint="Check the SQL syntax and ensure the target database objects exist",
            ) from e

    def initialize(self) -> None:
        """Create tb_confiture tracking table with Trinity pattern.

        Identity pattern (Trinity):
        - id: UUID (external, stable identifier)
        - pk_confiture: BIGINT (internal, sequential)
        - slug: TEXT (human-readable reference)

        This method is idempotent - safe to call multiple times.

        Raises:
            MigrationError: If table creation fails
        """
        state_impl.initialize(self)

    def apply(
        self,
        migration: Migration,
        force: bool = False,
        migration_file: Path | None = None,
        skip_preconditions: bool = False,
        *,
        commit: bool = True,
        applied_by: str | None = None,
    ) -> None:
        """Apply a migration and record it in the tracking table.

        For transactional migrations (default):
        - Uses savepoints for clean rollback on failure
        - Executes hooks before and after DDL execution

        For non-transactional migrations (transactional=False):
        - Runs in autocommit mode
        - No automatic rollback on failure
        - Required for CREATE INDEX CONCURRENTLY, etc.

        Precondition Validation:
        - If migration defines up_preconditions, they are validated first
        - If any precondition fails, the migration is aborted
        - Use skip_preconditions=True to bypass validation (not recommended)

        Args:
            migration: Migration instance to apply
            force: If True, skip the "already applied" check
            migration_file: Path to migration file for checksum computation
            skip_preconditions: If True, skip precondition validation (not recommended)
            commit: If False, the final ``connection.commit()`` after a
                successful transactional apply is suppressed. Used by
                ``--dry-run-execute`` where the caller owns an outer
                SAVEPOINT that must outlive the per-migration apply. Has
                no effect on non-transactional migrations.
            applied_by: PostgreSQL role to record in ``tb_confiture.applied_by``
                (issue #137). When None, defaults to the connection's
                ``current_user``. ``migrate apply-as`` sets this explicitly
                to the role argument.

        Raises:
            MigrationError: If migration fails or hooks fail
            PreconditionValidationError: If precondition validation fails
        """
        apply_impl.apply(
            self,
            migration,
            force=force,
            migration_file=migration_file,
            skip_preconditions=skip_preconditions,
            commit=commit,
            applied_by=applied_by,
        )

    def _validate_preconditions(
        self,
        migration: Migration,
        direction: str,
        preconditions: list,
    ) -> None:
        """Validate migration preconditions before execution.

        Raises:
            PreconditionValidationError: If any precondition fails.
        """
        apply_impl.validate_preconditions(self, migration, direction, preconditions)

    def _apply_transactional(
        self,
        migration: Migration,
        already_applied: bool,
        migration_file: Path | None = None,
        *,
        commit: bool = True,
        applied_by: str | None = None,
    ) -> None:
        """Apply migration within a transaction using savepoints.

        Args:
            migration: Migration instance to apply
            already_applied: Whether migration was already applied (force mode)
            migration_file: Path to migration file for checksum computation
            commit: If False, suppress the final ``connection.commit()``. The
                migration DDL and tracking-table row stay inside the caller's
                outer transaction; the caller is responsible for either
                committing or rolling back. Used by ``--dry-run-execute``,
                whose outer SAVEPOINT would otherwise be discarded by COMMIT.
            applied_by: PostgreSQL role to record in ``tb_confiture.applied_by``
                (issue #137). When None, defaults to the connection's
                ``current_user``.
        """
        apply_impl.apply_transactional(
            self,
            migration,
            already_applied,
            migration_file,
            commit=commit,
            applied_by=applied_by,
        )

    def _apply_non_transactional(
        self,
        migration: Migration,
        already_applied: bool,
        migration_file: Path | None = None,
        *,
        applied_by: str | None = None,
    ) -> None:
        """Apply migration in autocommit mode (no transaction).

        WARNING: If this fails, manual cleanup may be required.

        Args:
            migration: Migration instance to apply
            already_applied: Whether migration was already applied (force mode)
            migration_file: Path to migration file for checksum computation
        """
        apply_impl.apply_non_transactional(
            self,
            migration,
            already_applied,
            migration_file,
            applied_by=applied_by,
        )

    def _create_savepoint(self, name: str) -> None:
        """Create a savepoint for transaction rollback."""
        apply_impl.create_savepoint(self, name)

    def _release_savepoint(self, name: str) -> None:
        """Release a savepoint (commit nested transaction)."""
        apply_impl.release_savepoint(self, name)

    def _rollback_to_savepoint(self, name: str, *, commit: bool = True) -> None:
        """Rollback to a savepoint (undo nested transaction).

        When ``commit`` is False the post-rollback commit/full-rollback are
        suppressed so the rollback stays nested in the caller's transaction.
        """
        apply_impl.rollback_to_savepoint(self, name, commit=commit)

    def _record_migration(
        self,
        migration: Migration,
        execution_time_ms: int,
        migration_file: Path | None = None,
        *,
        applied_by: str | None = None,
    ) -> None:
        """Record migration in tracking table with checksum.

        ``applied_by`` defaults to the connection's ``current_user`` when None;
        pre-0.17.0 rows keep ``applied_by IS NULL`` as a documented invariant.
        """
        apply_impl.record_migration(
            self, migration, execution_time_ms, migration_file, applied_by=applied_by
        )

    def mark_applied(
        self,
        migration_file: Path,
        reason: str = "baseline",
    ) -> str:
        """Mark a migration as applied without executing it.

        Records the migration in the tracking table without running the up() method.
        Useful for:
        - Establishing a baseline when adopting confiture on an existing database
        - Setting up a new environment from a backup
        - Recovering from a failed migration state

        Args:
            migration_file: Path to migration file (.py or .up.sql)
            reason: Reason for marking as applied (stored in notes)

        Returns:
            Version of the migration that was marked as applied

        Raises:
            MigrationError: If migration is already applied or cannot be loaded

        Example:
            >>> migrator.mark_applied(Path("db/migrations/001_create_users.py"))
            "001"
        """
        return apply_impl.mark_applied(self, migration_file, reason)

    def baseline_from_db(
        self,
        source_dsn: str,
        migrations_dir: Path,
        *,
        through: str | None = None,
        dry_run: bool = False,
        source_table: str | None = None,
    ) -> dict[str, Any]:
        """Copy tracking-table rows from another database.

        Connects to *source_dsn*, reads ``tb_confiture`` (or
        *source_table* when given), filters to the intersection of
        source-applied versions and locally present migration files,
        and inserts the surviving rows into the target's tracking table.
        Rows already present on the target are skipped.

        Args:
            source_dsn: PostgreSQL connection string for the source DB.
            migrations_dir: Local migrations directory; used to compute
                the version intersection.
            through: Optional version cap.  Source rows with versions
                strictly above this are excluded and surfaced as a
                warning to make the operator aware of the skipped state.
            dry_run: When ``True``, no INSERTs are executed; the returned
                dict still describes what *would* have been copied.
            source_table: Override the source tracking-table name when
                it differs from the target.  Defaults to the target
                table name.

        Returns:
            A dict with keys ``copied`` (list of row dicts inserted),
            ``skipped`` (list of versions already on the target),
            ``source_only`` (list of versions in source but not local),
            ``warnings`` (list of human-readable diagnostics), and
            ``dry_run`` (bool).

        Raises:
            ConfigurationError: If *through* names a version that is not
                in source or local migration files.
            MigrationError: If the source connection fails or its table
                cannot be read.
        """
        return baseline_impl.baseline_from_db(
            self,
            source_dsn,
            migrations_dir,
            through=through,
            dry_run=dry_run,
            source_table=source_table,
        )

    def _clear_tracking_table(self) -> int:
        """Delete all entries from the tracking table.

        Used internally by reinit() to reset migration state before
        re-baselining. Uses DELETE (not TRUNCATE) for transaction safety.

        Returns:
            Number of rows deleted.
        """
        return baseline_impl.clear_tracking_table(self)

    def reinit(
        self,
        through: str | None = None,
        dry_run: bool = False,
        migrations_dir: Path | None = None,
    ) -> MigrateReinitResult:
        """Reset tracking table and re-mark migrations as applied.

        Clears all entries from tb_confiture, then re-marks migration files
        on disk as applied. Used after consolidating migration files to
        re-establish a clean tracking state.

        Args:
            through: Mark migrations up to and including this version.
                If None, marks all migration files on disk.
            dry_run: If True, perform the operation inside a transaction
                that is rolled back, returning what would have happened.
            migrations_dir: Directory containing migration files.
                Defaults to the migrator's configured directory.

        Returns:
            MigrateReinitResult with details of the operation.

        Raises:
            MigrationError: If the through version is not found on disk.

        Example:
            >>> migrator.reinit(through="005")
            MigrateReinitResult(success=True, deleted_count=5, ...)

            >>> migrator.reinit()  # marks all files
            MigrateReinitResult(success=True, deleted_count=3, ...)
        """
        return baseline_impl.reinit(self, through, dry_run, migrations_dir)

    def rollback(
        self,
        migration: Migration,
        skip_preconditions: bool = False,
    ) -> None:
        """Rollback a migration and remove it from tracking table.

        For transactional migrations (default):
        - Executes within a transaction with automatic rollback on failure
        - Safe and consistent

        For non-transactional migrations (transactional=False):
        - Runs in autocommit mode
        - No automatic rollback on failure
        - Manual cleanup may be required

        Precondition Validation:
        - If migration defines down_preconditions, they are validated first
        - If any precondition fails, the rollback is aborted
        - Use skip_preconditions=True to bypass validation (not recommended)

        Args:
            migration: Migration instance to rollback
            skip_preconditions: If True, skip precondition validation (not recommended)

        Raises:
            MigrationError: If migration fails or was not applied
            PreconditionValidationError: If precondition validation fails
        """
        rollback_impl.rollback(self, migration, skip_preconditions)

    def _is_applied(self, version: str) -> bool:
        """Check if migration *version* has been applied."""
        return state_impl.is_applied(self, version)

    def get_applied_versions(self) -> list[str]:
        """Get all applied migration versions, ordered by applied_at ascending."""
        return state_impl.get_applied_versions(self)

    def get_applied_migrations_with_timestamps(self) -> list[dict[str, Any]]:
        """Return applied migrations with version, name, and applied_at timestamp."""
        return state_impl.get_applied_migrations_with_timestamps(self)

    def get_current_revision_row(self) -> dict[str, Any] | None:
        """Return the most-recently-applied migration row, or None if empty.

        Raises psycopg's UndefinedTable when the tracking table is absent;
        callers must probe ``tracking_table_exists()`` first to distinguish an
        absent table (not initialized) from an empty one (no migrations).
        """
        return state_impl.get_current_revision_row(self)

    def find_migration_files(self, migrations_dir: Path | None = None) -> list[Path]:
        """Find all migration files in the migrations directory.

        Discovers both Python migrations (.py) and SQL file migrations (.up.sql).
        For SQL migrations, returns the .up.sql file path (the .down.sql is
        inferred when loading).

        Args:
            migrations_dir: Optional custom migrations directory.
                           If None, uses db/migrations/ (default)

        Returns:
            List of migration file paths, sorted by version number.
            Includes both .py files and .up.sql files.

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> files = migrator.find_migration_files()
            >>> # [Path("db/migrations/001_create_users.py"),
            >>> #  Path("db/migrations/002_add_posts.up.sql"), ...]
        """
        return discovery_impl.find_migration_files(self, migrations_dir)

    # ------------------------------------------------------------------
    # Rebuild helpers
    # ------------------------------------------------------------------

    _SYSTEM_SCHEMAS = frozenset(
        {
            "pg_catalog",
            "information_schema",
            "pg_toast",
        }
    )

    def _discover_user_schemas(self) -> list[str]:
        """Query all user-created schemas, excluding system schemas."""
        return baseline_impl.discover_user_schemas(self)

    def _drop_user_schemas(self, schemas: list[str]) -> list[str]:
        """Drop user schemas with CASCADE and recreate ``public`` (autocommit)."""
        return baseline_impl.drop_user_schemas(self, schemas)

    def _apply_ddl_string(self, ddl: str) -> tuple[int, list[str]]:
        """Execute DDL statements in autocommit mode.

        Returns a tuple of (statements_executed, warnings).
        """
        return baseline_impl.apply_ddl_string(self, ddl)

    def _backup_tracking_table(self) -> list[dict[str, Any]]:
        """Dump current tracking table contents as list of dicts (empty if absent)."""
        return baseline_impl.backup_tracking_table(self)

    def rebuild(
        self,
        *,
        drop_schemas: bool = False,
        dry_run: bool = False,
        apply_seeds: bool = False,
        backup_tracking: bool = False,
        schema_dir: Path | None = None,
        migrations_dir: Path | None = None,
        seeds_dir: Path | None = None,
        env_config: Environment | None = None,
    ) -> MigrateRebuildResult:
        """Rebuild database from DDL and bootstrap tracking table.

        Orchestrates: (1) optional tracking backup, (2) optional schema
        cleanup, (3) DDL build + apply, (4) tracking table init +
        re-baseline, (5) optional seed application.

        Args:
            drop_schemas: Drop all user schemas before rebuild.
            dry_run: Build DDL and report what would happen without executing.
            apply_seeds: Apply seed files after DDL.
            backup_tracking: Dump tracking table before clearing.
            schema_dir: Path to schema directory (default: db/schema).
            migrations_dir: Path to migrations directory (default: db/migrations).
            seeds_dir: Path to seeds directory (default: db/seeds).
            env_config: Optional Environment config for SchemaBuilder.

        Returns:
            MigrateRebuildResult with operation details.

        Raises:
            RebuildError: If schema build or DDL application fails.
        """
        return baseline_impl.rebuild(
            self,
            drop_schemas=drop_schemas,
            dry_run=dry_run,
            apply_seeds=apply_seeds,
            backup_tracking=backup_tracking,
            schema_dir=schema_dir,
            migrations_dir=migrations_dir,
            seeds_dir=seeds_dir,
            env_config=env_config,
        )

    def tracking_table_exists(self) -> bool:
        """Return True if the tb_confiture tracking table exists in the database.

        Useful for detecting whether a database has been initialised with
        confiture (e.g. after a staging restore that wiped the tracking table).

        Returns:
            True if ``tb_confiture`` exists, False otherwise.

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> if not migrator.tracking_table_exists():
            ...     migrator.initialize()
        """
        return state_impl.tracking_table_exists(self)

    def baseline_through(
        self,
        through: str,
        migrations_dir: Path,
    ) -> list[str]:
        """Mark migrations as applied through a version without clearing the table.

        Unlike :meth:`reinit`, this method does **not** delete existing
        tracking entries.  It only inserts new rows for migrations that are
        not yet recorded.  Intended for use by auto-detect baseline after a
        restore wipes the tracking table.

        Args:
            through: Target version string (e.g. ``"007"``).  All migration
                files from the first through this version are marked applied.
            migrations_dir: Directory containing migration files.

        Returns:
            List of version strings that were newly marked as applied.

        Raises:
            MigrationError: If ``through`` version is not found on disk.

        Example:
            >>> migrator.baseline_through("007", Path("db/migrations"))
            ["001", "002", "003", "004", "005", "006", "007"]
        """
        return baseline_impl.baseline_through(self, through, migrations_dir)

    def find_duplicate_versions(self, migrations_dir: Path | None = None) -> dict[str, list[Path]]:
        """Find migration files that share the same version prefix.

        Groups migration files by version prefix and returns only versions
        with more than one file. This detects conflicts that would cause
        a UNIQUE constraint violation on tb_confiture.version at apply time.

        Args:
            migrations_dir: Optional custom migrations directory.
                           If None, uses db/migrations/ (default)

        Returns:
            Dict mapping version strings to lists of conflicting file paths.
            Empty dict if no duplicates exist.

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> dupes = migrator.find_duplicate_versions()
            >>> # {"001": [Path("001_a.py"), Path("001_b.up.sql")]}
        """
        if migrations_dir is None:
            migrations_dir = Path("db") / "migrations"
        return find_duplicate_migration_versions(migrations_dir)

    def find_orphaned_sql_files(self, migrations_dir: Path | None = None) -> list[Path]:
        """Find .sql files that don't match the expected naming pattern.

        Confiture only recognizes:
        - {NNN}_{name}.up.sql (forward migrations)
        - {NNN}_{name}.down.sql (rollback migrations)

        Files like {NNN}_{name}.sql (without .up/.down) are silently ignored
        by the migration discovery and should be renamed.

        Args:
            migrations_dir: Optional custom migrations directory.
                           If None, uses db/migrations/ (default)

        Returns:
            List of orphaned .sql file paths, sorted by name.

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> orphaned = migrator.find_orphaned_sql_files()
            >>> # [Path("db/migrations/001_create_users.sql"),
            >>> #  Path("db/migrations/002_add_columns.sql")]
        """
        return discovery_impl.find_orphaned_sql_files(migrations_dir)

    def fix_orphaned_sql_files(
        self, migrations_dir: Path | None = None, dry_run: bool = False
    ) -> dict[str, list[tuple[str, str]]]:
        """Rename orphaned SQL files to match the expected naming pattern.

        For each orphaned file {NNN}_{name}.sql, renames it to {NNN}_{name}.up.sql
        (assuming it's a forward migration).

        Args:
            migrations_dir: Optional custom migrations directory.
                           If None, uses db/migrations/ (default)
            dry_run: If True, return what would be renamed without making changes

        Returns:
            Dictionary with:
            - 'renamed': List of tuples (old_name, new_name) for successfully renamed files
            - 'errors': List of tuples (filename, error_message) for failures

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> result = migrator.fix_orphaned_sql_files(dry_run=False)
            >>> print(f"Renamed: {result['renamed']}")
            Renamed: [('001_create_users.sql', '001_create_users.up.sql')]
        """
        return discovery_impl.fix_orphaned_sql_files(self, migrations_dir, dry_run)

    def find_pending(self, migrations_dir: Path | None = None) -> list[Path]:
        """Find migrations that have not been applied yet.

        Args:
            migrations_dir: Optional custom migrations directory

        Returns:
            List of pending migration file paths

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> pending = migrator.find_pending()
            >>> print(f"Found {len(pending)} pending migrations")
        """
        return discovery_impl.find_pending(self, migrations_dir)

    def _version_from_filename(self, filename: str) -> str:
        """Extract the version prefix from a migration filename.

        Supports ``{version}_{name}.py`` and ``{version}_{name}.up.sql`` (and
        ``.down.sql``) → ``"001"``.
        """
        return _version_from_migration_filename(filename)

    def migrate_up(
        self,
        force: bool = False,
        migrations_dir: Path | None = None,
        target: str | None = None,
        lock_config: LockConfig | None = None,
        checksum_config: ChecksumConfig | None = None,
        progress: ProgressManager | None = None,
    ) -> list[str]:
        """Apply pending migrations up to target version.

        Uses distributed locking to ensure only one migration process runs
        at a time. This is critical for multi-pod Kubernetes deployments.

        Optionally verifies checksums before running migrations to detect
        unauthorized modifications to migration files.

        Args:
            force: If True, skip migration state checks and apply all migrations
            migrations_dir: Custom migrations directory (default: db/migrations)
            target: Target migration version (applies all if None)
            lock_config: Locking configuration. If None, uses default (enabled,
                30s timeout, blocking mode). Pass LockConfig(enabled=False)
                to disable locking.
            checksum_config: Checksum verification configuration. If None, uses
                default (enabled, fail on mismatch). Pass
                ChecksumConfig(enabled=False) to disable verification.
            progress: Optional ProgressManager for displaying migration progress

        Returns:
            List of applied migration versions

        Raises:
            MigrationError: If migration application fails
            LockAcquisitionError: If lock cannot be acquired within timeout
            ChecksumVerificationError: If checksum mismatch and behavior is FAIL

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> migrator.initialize()
            >>> # Default: verify checksums, fail on mismatch
            >>> applied = migrator.migrate_up()
            >>>
            >>> # With progress tracking
            >>> with ProgressManager() as pm:
            ...     applied = migrator.migrate_up(progress=pm)
        """
        return apply_impl.migrate_up(
            self,
            force=force,
            migrations_dir=migrations_dir,
            target=target,
            lock_config=lock_config,
            checksum_config=checksum_config,
            progress=progress,
        )

    def _migrate_up_internal(
        self,
        force: bool = False,
        migrations_dir: Path | None = None,
        target: str | None = None,
        progress: ProgressManager | None = None,
    ) -> list[str]:
        """Internal implementation of migrate_up (called within lock)."""
        return apply_impl.migrate_up_internal(
            self, force, migrations_dir, target, progress=progress
        )

    def _warn_mixed_transactional_modes(self, migration_files: list[Path]) -> None:
        """Warn if batch contains both transactional and non-transactional migrations."""
        apply_impl.warn_mixed_transactional_modes(migration_files)

    def _trigger_hook(
        self,
        phase: Any,
        migration: Migration,
        execution_time_ms: int = 0,
        success: bool = False,
        error: str | None = None,
    ) -> None:
        """Trigger hooks for a migration lifecycle event."""
        state_impl.trigger_hook(self, phase, migration, execution_time_ms, success, error)

    def dry_run(self, migration: Migration) -> DryRunResult:
        """Test a migration without making permanent changes.

        Executes the migration SQL statements inside a SAVEPOINT that gets
        rolled back, providing accurate timing and constraint validation.

        Args:
            migration: Migration instance to test

        Returns:
            DryRunResult with execution metrics and real DB feedback

        Raises:
            DryRunError: If migration execution fails during dry-run

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> migration = MyMigration(connection=conn)
            >>> result = migrator.dry_run(migration)
            >>> print(f"Execution time: {result.total_time_ms}ms")
            >>> print(f"Confidence: {result.confidence_pct}%")
        """
        return apply_impl.dry_run(self, migration)

    def check_preconditions(
        self,
        migration: Migration,
        direction: str = "up",
    ) -> tuple[bool, list[tuple[Any, str]]]:
        """Check migration preconditions without running the migration.

        Returns ``(all_passed, failures)`` where *failures* is a list of
        ``(precondition, error_message)`` tuples.
        """
        return apply_impl.check_preconditions(self, migration, direction)

    @classmethod
    def from_config(
        cls,
        config: Environment | Path | str,
        *,
        migrations_dir: Path | str = Path("db/migrations"),
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
        return factory.from_config(config, migrations_dir=migrations_dir)
