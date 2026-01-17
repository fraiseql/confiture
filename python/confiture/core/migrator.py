"""Migration executor for applying and rolling back database migrations."""

import logging
import time
from pathlib import Path

import psycopg

from confiture.core.checksum import (
    ChecksumConfig,
    MigrationChecksumVerifier,
    compute_checksum,
)
from confiture.core.connection import get_migration_class, load_migration_module
from confiture.core.dry_run import DryRunExecutor, DryRunResult
from confiture.core.hooks import HookError
from confiture.core.locking import LockConfig, MigrationLock
from confiture.exceptions import MigrationError, SQLError
from confiture.models.migration import Migration

logger = logging.getLogger(__name__)


class Migrator:
    """Executes database migrations and tracks their state.

    The Migrator class is responsible for:
    - Creating and managing the confiture_migrations tracking table
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

    def __init__(self, connection: psycopg.Connection):
        """Initialize migrator with database connection.

        Args:
            connection: psycopg3 database connection
        """
        self.connection = connection

    def _execute_sql(self, sql: str, params: tuple[str, ...] | None = None) -> None:
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
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
        except Exception as e:
            raise SQLError(sql, params, e) from e

    def initialize(self) -> None:
        """Create confiture_migrations tracking table with modern identity trinity.

        Identity pattern:
        - id: Auto-incrementing BIGINT (internal, sequential)
        - pk_migration: UUID (stable identifier, external APIs)
        - slug: Human-readable (migration_name + timestamp)

        This method is idempotent - safe to call multiple times.
        Handles migration from old table structure.

        Raises:
            MigrationError: If table creation fails
        """
        try:
            # Enable UUID extension
            self._execute_sql('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

            # Check if table exists
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'confiture_migrations'
                    )
                """)
                result = cursor.fetchone()
                table_exists = result[0] if result else False

            if table_exists:
                # Check if we need to migrate old table structure
                with self.connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns
                            WHERE table_name = 'confiture_migrations'
                            AND column_name = 'pk_migration'
                        )
                    """)
                    result = cursor.fetchone()
                    has_new_structure = result[0] if result else False

                if not has_new_structure:
                    # Migrate old table structure to new trinity pattern
                    self._execute_sql("""
                        ALTER TABLE confiture_migrations
                        ADD COLUMN pk_migration UUID DEFAULT uuid_generate_v4() UNIQUE,
                        ADD COLUMN slug TEXT,
                        ALTER COLUMN id SET DATA TYPE BIGINT,
                        ALTER COLUMN applied_at SET DATA TYPE TIMESTAMPTZ
                    """)

                    # Generate slugs for existing migrations
                    self._execute_sql("""
                        UPDATE confiture_migrations
                        SET slug = name || '_' || to_char(applied_at, 'YYYYMMDD_HH24MISS')
                        WHERE slug IS NULL
                    """)

                    # Make slug NOT NULL and UNIQUE
                    self._execute_sql("""
                        ALTER TABLE confiture_migrations
                        ALTER COLUMN slug SET NOT NULL,
                        ADD CONSTRAINT confiture_migrations_slug_unique UNIQUE (slug)
                    """)

                    # Create new indexes
                    self._execute_sql("""
                        CREATE INDEX IF NOT EXISTS idx_confiture_migrations_pk_migration
                            ON confiture_migrations(pk_migration)
                    """)
                    self._execute_sql("""
                        CREATE INDEX IF NOT EXISTS idx_confiture_migrations_slug
                            ON confiture_migrations(slug)
                    """)

            else:
                # Create new table with trinity pattern
                self._execute_sql("""
                    CREATE TABLE confiture_migrations (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        pk_migration UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
                        slug TEXT NOT NULL UNIQUE,
                        version VARCHAR(255) NOT NULL UNIQUE,
                        name VARCHAR(255) NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        execution_time_ms INTEGER,
                        checksum VARCHAR(64)
                    )
                """)

                # Create indexes
                self._execute_sql("""
                    CREATE INDEX idx_confiture_migrations_pk_migration
                        ON confiture_migrations(pk_migration)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_confiture_migrations_slug
                        ON confiture_migrations(slug)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_confiture_migrations_version
                        ON confiture_migrations(version)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_confiture_migrations_applied_at
                        ON confiture_migrations(applied_at DESC)
                """)

            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, SQLError):
                raise MigrationError(f"Failed to initialize migrations table: {e}") from e
            else:
                raise MigrationError(f"Failed to initialize migrations table: {e}") from e

    def apply(
        self,
        migration: Migration,
        force: bool = False,
        migration_file: Path | None = None,
    ) -> None:
        """Apply a migration and record it in the tracking table.

        For transactional migrations (default):
        - Uses savepoints for clean rollback on failure
        - Executes hooks before and after DDL execution

        For non-transactional migrations (transactional=False):
        - Runs in autocommit mode
        - No automatic rollback on failure
        - Required for CREATE INDEX CONCURRENTLY, etc.

        Args:
            migration: Migration instance to apply
            force: If True, skip the "already applied" check
            migration_file: Path to migration file for checksum computation

        Raises:
            MigrationError: If migration fails or hooks fail
        """
        already_applied = self._is_applied(migration.version)

        if not force and already_applied:
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) has already been applied"
            )

        if migration.transactional:
            self._apply_transactional(migration, already_applied, migration_file)
        else:
            self._apply_non_transactional(migration, already_applied, migration_file)

    def _apply_transactional(
        self,
        migration: Migration,
        already_applied: bool,
        migration_file: Path | None = None,
    ) -> None:
        """Apply migration within a transaction using savepoints.

        Args:
            migration: Migration instance to apply
            already_applied: Whether migration was already applied (force mode)
            migration_file: Path to migration file for checksum computation
        """
        savepoint_name = f"migration_{migration.version}"
        try:
            self._create_savepoint(savepoint_name)

            # Execute migration DDL
            logger.debug(f"Executing DDL for migration {migration.version}")
            start_time = time.perf_counter()
            migration.up()
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            # Only record the migration if it's not already applied
            # In force mode, we re-apply but don't re-record
            if not already_applied:
                self._record_migration(migration, execution_time_ms, migration_file)
            self._release_savepoint(savepoint_name)

            self.connection.commit()
            logger.info(f"Successfully applied migration {migration.version} ({migration.name})")

        except Exception as e:
            self._rollback_to_savepoint(savepoint_name)
            if isinstance(e, (MigrationError, HookError)):
                raise
            else:
                raise MigrationError(
                    f"Failed to apply migration {migration.version} ({migration.name}): {e}"
                ) from e

    def _apply_non_transactional(
        self,
        migration: Migration,
        already_applied: bool,
        migration_file: Path | None = None,
    ) -> None:
        """Apply migration in autocommit mode (no transaction).

        WARNING: If this fails, manual cleanup may be required.

        Args:
            migration: Migration instance to apply
            already_applied: Whether migration was already applied (force mode)
            migration_file: Path to migration file for checksum computation
        """
        logger.warning(
            f"Running migration {migration.version} in non-transactional mode. "
            "Manual cleanup may be required on failure."
        )

        # Ensure any pending transaction is committed
        self.connection.commit()

        # Set autocommit mode
        original_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            logger.debug(f"Executing DDL for migration {migration.version} (autocommit)")
            start_time = time.perf_counter()
            migration.up()
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            # Record migration (in autocommit, this commits immediately)
            if not already_applied:
                self._record_migration(migration, execution_time_ms, migration_file)

            logger.info(
                f"Successfully applied non-transactional migration "
                f"{migration.version} ({migration.name})"
            )

        except Exception as e:
            logger.error(
                f"Non-transactional migration {migration.version} failed. "
                "Manual cleanup may be required."
            )
            raise MigrationError(
                f"Failed to apply non-transactional migration "
                f"{migration.version} ({migration.name}): {e}. "
                "Manual cleanup may be required."
            ) from e

        finally:
            # Restore original autocommit setting
            self.connection.autocommit = original_autocommit

    def _create_savepoint(self, name: str) -> None:
        """Create a savepoint for transaction rollback."""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {name}")

    def _release_savepoint(self, name: str) -> None:
        """Release a savepoint (commit nested transaction)."""
        with self.connection.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {name}")

    def _rollback_to_savepoint(self, name: str) -> None:
        """Rollback to a savepoint (undo nested transaction)."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.connection.commit()
        except Exception:
            # Savepoint rollback failed, do full rollback
            self.connection.rollback()

    def _record_migration(
        self,
        migration: Migration,
        execution_time_ms: int,
        migration_file: Path | None = None,
    ) -> None:
        """Record migration in tracking table with checksum.

        Args:
            migration: Migration that was applied
            execution_time_ms: Time taken to apply migration
            migration_file: Path to migration file for checksum computation
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{migration.name}_{timestamp}"

        # Compute checksum if file path provided
        checksum = None
        if migration_file is not None and migration_file.exists():
            checksum = compute_checksum(migration_file)
            logger.debug(f"Computed checksum for {migration.version}: {checksum[:16]}...")

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_migrations
                    (slug, version, name, execution_time_ms, checksum)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (slug, migration.version, migration.name, execution_time_ms, checksum),
            )

    def rollback(self, migration: Migration) -> None:
        """Rollback a migration and remove it from tracking table.

        For transactional migrations (default):
        - Executes within a transaction with automatic rollback on failure
        - Safe and consistent

        For non-transactional migrations (transactional=False):
        - Runs in autocommit mode
        - No automatic rollback on failure
        - Manual cleanup may be required

        Args:
            migration: Migration instance to rollback

        Raises:
            MigrationError: If migration fails or was not applied
        """
        # Check if applied
        if not self._is_applied(migration.version):
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) "
                "has not been applied, cannot rollback"
            )

        if migration.transactional:
            self._rollback_transactional(migration)
        else:
            self._rollback_non_transactional(migration)

    def _rollback_transactional(self, migration: Migration) -> None:
        """Rollback a migration within a transaction.

        Args:
            migration: Migration instance to rollback
        """
        try:
            # Execute down() method
            logger.debug(f"Executing rollback (down) for migration {migration.version}")
            migration.down()

            # Remove from tracking table
            self._execute_sql(
                """
                DELETE FROM confiture_migrations
                WHERE version = %s
                """,
                (migration.version,),
            )

            # Commit transaction
            self.connection.commit()
            logger.info(
                f"Successfully rolled back migration {migration.version} ({migration.name})"
            )

        except Exception as e:
            self.connection.rollback()
            raise MigrationError(
                f"Failed to rollback migration {migration.version} ({migration.name}): {e}"
            ) from e

    def _rollback_non_transactional(self, migration: Migration) -> None:
        """Rollback a migration in autocommit mode (no transaction).

        WARNING: If this fails, manual cleanup may be required.

        Args:
            migration: Migration instance to rollback
        """
        logger.warning(
            f"Rolling back migration {migration.version} in non-transactional mode. "
            "Manual cleanup may be required on failure."
        )

        # Ensure any pending transaction is committed
        self.connection.commit()

        # Set autocommit mode
        original_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            # Execute down() method
            logger.debug(
                f"Executing rollback (down) for migration {migration.version} (autocommit)"
            )
            migration.down()

            # Remove from tracking table
            self._execute_sql(
                """
                DELETE FROM confiture_migrations
                WHERE version = %s
                """,
                (migration.version,),
            )

            logger.info(
                f"Successfully rolled back non-transactional migration "
                f"{migration.version} ({migration.name})"
            )

        except Exception as e:
            logger.error(
                f"Non-transactional rollback of migration {migration.version} failed. "
                "Manual cleanup may be required."
            )
            raise MigrationError(
                f"Failed to rollback non-transactional migration "
                f"{migration.version} ({migration.name}): {e}. "
                "Manual cleanup may be required."
            ) from e

        finally:
            # Restore original autocommit setting
            self.connection.autocommit = original_autocommit

    def _is_applied(self, version: str) -> bool:
        """Check if migration version has been applied.

        Args:
            version: Migration version to check

        Returns:
            True if migration has been applied, False otherwise
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM confiture_migrations
                WHERE version = %s
                """,
                (version,),
            )
            result = cursor.fetchone()
            if result is None:
                return False
            count: int = result[0]
            return count > 0

    def get_applied_versions(self) -> list[str]:
        """Get list of all applied migration versions.

        Returns:
            List of migration versions, sorted by applied_at timestamp
        """
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT version
                FROM confiture_migrations
                ORDER BY applied_at ASC
            """)
            return [row[0] for row in cursor.fetchall()]

    def find_migration_files(self, migrations_dir: Path | None = None) -> list[Path]:
        """Find all migration files in the migrations directory.

        Args:
            migrations_dir: Optional custom migrations directory.
                           If None, uses db/migrations/ (default)

        Returns:
            List of migration file paths, sorted by version number

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> files = migrator.find_migration_files()
            >>> # [Path("db/migrations/001_create_users.py"), ...]
        """
        if migrations_dir is None:
            migrations_dir = Path("db") / "migrations"

        if not migrations_dir.exists():
            return []

        # Find all .py files (excluding __pycache__, __init__.py)
        migration_files = sorted(
            [
                f
                for f in migrations_dir.glob("*.py")
                if f.name != "__init__.py" and not f.name.startswith("_")
            ]
        )

        return migration_files

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
        # Get all migration files
        all_migrations = self.find_migration_files(migrations_dir)

        # Get applied versions
        applied_versions = set(self.get_applied_versions())

        # Filter to pending only
        pending_migrations = [
            migration_file
            for migration_file in all_migrations
            if self._version_from_filename(migration_file.name) not in applied_versions
        ]

        return pending_migrations

    def _version_from_filename(self, filename: str) -> str:
        """Extract version from migration filename.

        Migration files follow the format: {version}_{name}.py
        Example: "001_create_users.py" -> "001"

        Args:
            filename: Migration filename

        Returns:
            Version string

        Example:
            >>> migrator._version_from_filename("042_add_column.py")
            "042"
        """
        # Split on first underscore
        version = filename.split("_")[0]
        return version

    def migrate_up(
        self,
        force: bool = False,
        migrations_dir: Path | None = None,
        target: str | None = None,
        lock_config: LockConfig | None = None,
        checksum_config: ChecksumConfig | None = None,
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
            >>> # Custom checksum behavior
            >>> from confiture.core.checksum import ChecksumConfig, ChecksumMismatchBehavior
            >>> applied = migrator.migrate_up(
            ...     checksum_config=ChecksumConfig(
            ...         on_mismatch=ChecksumMismatchBehavior.WARN
            ...     )
            ... )
            >>>
            >>> # Disable checksum verification
            >>> applied = migrator.migrate_up(
            ...     checksum_config=ChecksumConfig(enabled=False)
            ... )
        """
        effective_migrations_dir = migrations_dir or Path("db/migrations")

        # Verify checksums before running migrations (unless force mode)
        if checksum_config is None:
            checksum_config = ChecksumConfig()

        if checksum_config.enabled and not force:
            verifier = MigrationChecksumVerifier(self.connection, checksum_config)
            verifier.verify_all(effective_migrations_dir)

        # Create lock manager
        lock = MigrationLock(self.connection, lock_config)

        # Acquire lock and run migrations
        with lock.acquire():
            return self._migrate_up_internal(force, migrations_dir, target)

    def _migrate_up_internal(
        self,
        force: bool = False,
        migrations_dir: Path | None = None,
        target: str | None = None,
    ) -> list[str]:
        """Internal implementation of migrate_up (called within lock).

        Args:
            force: If True, skip migration state checks
            migrations_dir: Custom migrations directory
            target: Target migration version

        Returns:
            List of applied migration versions
        """
        # Find migrations to apply
        if force:
            # In force mode, apply all migrations regardless of state
            migrations_to_apply = self.find_migration_files(migrations_dir)
        else:
            # Normal mode: only apply pending migrations
            migrations_to_apply = self.find_pending(migrations_dir)

        # Check for mixed transactional modes and warn
        self._warn_mixed_transactional_modes(migrations_to_apply)

        applied_versions = []

        for migration_file in migrations_to_apply:
            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=self.connection)

            # Check target
            if target and migration.version > target:
                break

            # Apply migration with file path for checksum computation
            self.apply(migration, force=force, migration_file=migration_file)
            applied_versions.append(migration.version)

        return applied_versions

    def _warn_mixed_transactional_modes(self, migration_files: list[Path]) -> None:
        """Warn if batch contains both transactional and non-transactional migrations.

        Mixed batches can be problematic because non-transactional migrations
        cannot be automatically rolled back if a later transactional migration fails.

        Args:
            migration_files: List of migration files to check
        """
        if len(migration_files) <= 1:
            return

        transactional_migrations: list[str] = []
        non_transactional_migrations: list[str] = []

        for migration_file in migration_files:
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Check transactional attribute (default is True)
            is_transactional = getattr(migration_class, "transactional", True)

            if is_transactional:
                transactional_migrations.append(migration_file.name)
            else:
                non_transactional_migrations.append(migration_file.name)

        if transactional_migrations and non_transactional_migrations:
            logger.warning(
                "Batch contains both transactional and non-transactional migrations. "
                "If a transactional migration fails after a non-transactional one succeeds, "
                "manual cleanup of the non-transactional changes may be required.\n"
                f"  Non-transactional: {', '.join(non_transactional_migrations)}\n"
                f"  Transactional: {', '.join(transactional_migrations[:3])}"
                f"{'...' if len(transactional_migrations) > 3 else ''}"
            )

    def dry_run(self, migration: Migration) -> DryRunResult:
        """Test a migration without making permanent changes.

        Executes the migration in dry-run mode using DryRunExecutor,
        which automatically rolls back all changes. Useful for:
        - Verifying migrations work before production deployment
        - Estimating execution time
        - Detecting constraint violations
        - Identifying table locking issues

        Args:
            migration: Migration instance to test

        Returns:
            DryRunResult with execution metrics and estimates

        Raises:
            DryRunError: If migration execution fails during dry-run

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> migration = MyMigration(connection=conn)
            >>> result = migrator.dry_run(migration)
            >>> print(f"Estimated time: {result.estimated_production_time_ms}ms")
            >>> print(f"Confidence: {result.confidence_percent}%")
        """
        executor = DryRunExecutor()
        return executor.run(self.connection, migration)
