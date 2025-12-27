"""Migration executor for applying and rolling back database migrations."""

import logging
import time
from pathlib import Path

import psycopg

from confiture.core.connection import get_migration_class, load_migration_module
from confiture.core.dry_run import DryRunExecutor
from confiture.core.hooks import HookContext, HookError, HookExecutor, HookPhase
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

    def apply(self, migration: Migration, force: bool = False) -> None:
        """Apply a migration and record it in the tracking table.

        Uses savepoints for clean rollback on failure.
        Executes hooks before and after DDL execution:
        - BEFORE_VALIDATION: Pre-flight checks
        - BEFORE_DDL: Data preparation
        - AFTER_DDL: Data backfill (e.g., read model updates)
        - AFTER_VALIDATION: Consistency verification
        - CLEANUP: Final cleanup
        - ON_ERROR: Error handlers (if migration fails)

        Args:
            migration: Migration instance to apply
            force: If True, skip the "already applied" check

        Raises:
            MigrationError: If migration fails or hooks fail
        """
        already_applied = self._is_applied(migration.version)

        if not force and already_applied:
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) has already been applied"
            )

        savepoint_name = f"migration_{migration.version}"
        executor = HookExecutor()
        context = HookContext(
            migration_name=migration.name,
            migration_version=migration.version,
            direction="forward"
        )

        try:
            self._create_savepoint(savepoint_name)

            # BEFORE_VALIDATION phase
            logger.debug(f"Executing BEFORE_VALIDATION hooks for migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.BEFORE_VALIDATION,
                migration.before_validation_hooks or [],
                context
            )

            # BEFORE_DDL phase
            logger.debug(f"Executing BEFORE_DDL hooks for migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.BEFORE_DDL,
                migration.before_ddl_hooks or [],
                context
            )

            # Execute migration DDL
            logger.debug(f"Executing DDL for migration {migration.version}")
            start_time = time.perf_counter()
            migration.up()
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            # AFTER_DDL phase
            logger.debug(f"Executing AFTER_DDL hooks for migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.AFTER_DDL,
                migration.after_ddl_hooks or [],
                context
            )

            # AFTER_VALIDATION phase
            logger.debug(f"Executing AFTER_VALIDATION hooks for migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.AFTER_VALIDATION,
                migration.after_validation_hooks or [],
                context
            )

            # CLEANUP phase
            logger.debug(f"Executing CLEANUP hooks for migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.CLEANUP,
                migration.cleanup_hooks or [],
                context
            )

            # Only record the migration if it's not already applied
            # In force mode, we re-apply but don't re-record
            if not already_applied:
                self._record_migration(migration, execution_time_ms)
            self._release_savepoint(savepoint_name)

            self.connection.commit()
            logger.info(f"Successfully applied migration {migration.version} ({migration.name})")

        except Exception as e:
            self._rollback_to_savepoint(savepoint_name)

            # ON_ERROR phase: execute error handlers if migration fails
            logger.debug(f"Migration {migration.version} failed, executing ON_ERROR hooks")
            try:
                executor.execute_phase(
                    self.connection,
                    HookPhase.ON_ERROR,
                    migration.error_hooks or [],
                    context
                )
            except Exception as hook_error:
                # Log hook error but don't mask the original migration error
                logger.error(
                    f"ON_ERROR hook failed for migration {migration.version}: {hook_error}",
                    exc_info=True
                )

            if isinstance(e, (MigrationError, HookError)):
                raise
            else:
                raise MigrationError(
                    f"Failed to apply migration {migration.version} ({migration.name}): {e}"
                ) from e

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

    def _record_migration(self, migration: Migration, execution_time_ms: int) -> None:
        """Record migration in tracking table."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{migration.name}_{timestamp}"

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_migrations
                    (slug, version, name, execution_time_ms)
                VALUES (%s, %s, %s, %s)
                """,
                (slug, migration.version, migration.name, execution_time_ms),
            )

    def rollback(self, migration: Migration) -> None:
        """Rollback a migration and remove it from tracking table.

        This method:
        1. Checks if migration was applied
        2. Executes BEFORE_DDL hooks (for rollback cleanup prep)
        3. Executes migration.down() within a transaction
        4. Executes CLEANUP hooks (for rollback cleanup)
        5. Removes migration record from tracking table
        6. Commits transaction
        7. Executes ON_ERROR hooks if rollback fails

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

        executor = HookExecutor()
        context = HookContext(
            migration_name=migration.name,
            migration_version=migration.version,
            direction="backward"
        )

        try:
            # BEFORE_DDL phase (for rollback cleanup prep)
            logger.debug(f"Executing BEFORE_DDL hooks for rollback of migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.BEFORE_DDL,
                migration.before_ddl_hooks or [],
                context
            )

            # Execute down() method
            logger.debug(f"Executing rollback (down) for migration {migration.version}")
            migration.down()

            # CLEANUP phase (for rollback cleanup)
            logger.debug(f"Executing CLEANUP hooks for rollback of migration {migration.version}")
            executor.execute_phase(
                self.connection,
                HookPhase.CLEANUP,
                migration.cleanup_hooks or [],
                context
            )

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
            logger.info(f"Successfully rolled back migration {migration.version} ({migration.name})")

        except Exception as e:
            self.connection.rollback()

            # ON_ERROR phase: execute error handlers if rollback fails
            logger.debug(f"Rollback of migration {migration.version} failed, executing ON_ERROR hooks")
            try:
                executor.execute_phase(
                    self.connection,
                    HookPhase.ON_ERROR,
                    migration.error_hooks or [],
                    context
                )
            except Exception as hook_error:
                # Log hook error but don't mask the original rollback error
                logger.error(
                    f"ON_ERROR hook failed during rollback of migration {migration.version}: {hook_error}",
                    exc_info=True
                )

            raise MigrationError(
                f"Failed to rollback migration {migration.version} ({migration.name}): {e}"
            ) from e

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
        self, force: bool = False, migrations_dir: Path | None = None, target: str | None = None
    ) -> list[str]:
        """Apply pending migrations up to target version.

        Args:
            force: If True, skip migration state checks and apply all migrations
            migrations_dir: Custom migrations directory (default: db/migrations)
            target: Target migration version (applies all if None)

        Returns:
            List of applied migration versions

        Raises:
            MigrationError: If migration application fails
        """
        # Find migrations to apply
        if force:
            # In force mode, apply all migrations regardless of state
            migrations_to_apply = self.find_migration_files(migrations_dir)
        else:
            # Normal mode: only apply pending migrations
            migrations_to_apply = self.find_pending(migrations_dir)

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

            # Apply migration
            self.apply(migration, force=force)
            applied_versions.append(migration.version)

        return applied_versions

    def dry_run(self, migration: Migration) -> "DryRunResult":  # noqa: F821
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
