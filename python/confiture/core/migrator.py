"""Migration executor for applying and rolling back database migrations."""

import logging
import time
from pathlib import Path
from typing import Any

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
from confiture.core.preconditions import PreconditionValidationError, PreconditionValidator
from confiture.exceptions import MigrationError, SQLError
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
        """Create tb_confiture tracking table with Trinity pattern.

        Identity pattern (Trinity):
        - id: UUID (external, stable identifier)
        - pk_confiture: BIGINT (internal, sequential)
        - slug: TEXT (human-readable reference)

        This method is idempotent - safe to call multiple times.

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
                        WHERE table_name = 'tb_confiture'
                    )
                """)
                result = cursor.fetchone()
                table_exists = result[0] if result else False

            if not table_exists:
                # Create new table with Trinity pattern
                self._execute_sql("""
                    CREATE TABLE tb_confiture (
                        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                        pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
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
                    CREATE INDEX idx_tb_confiture_pk_confiture
                        ON tb_confiture(pk_confiture)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_tb_confiture_slug
                        ON tb_confiture(slug)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_tb_confiture_version
                        ON tb_confiture(version)
                """)
                self._execute_sql("""
                    CREATE INDEX idx_tb_confiture_applied_at
                        ON tb_confiture(applied_at DESC)
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
        skip_preconditions: bool = False,
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

        Raises:
            MigrationError: If migration fails or hooks fail
            PreconditionValidationError: If precondition validation fails
        """
        already_applied = self._is_applied(migration.version)

        if not force and already_applied:
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) has already been applied"
            )

        # Validate preconditions before applying
        if not skip_preconditions:
            self._validate_preconditions(
                migration, direction="up", preconditions=migration.up_preconditions
            )

        if migration.transactional:
            self._apply_transactional(migration, already_applied, migration_file)
        else:
            self._apply_non_transactional(migration, already_applied, migration_file)

    def _validate_preconditions(
        self,
        migration: Migration,
        direction: str,
        preconditions: list,
    ) -> None:
        """Validate migration preconditions before execution.

        Args:
            migration: Migration being validated
            direction: "up" or "down" for error messages
            preconditions: List of preconditions to check

        Raises:
            PreconditionValidationError: If any precondition fails
        """
        if not preconditions:
            return

        logger.debug(
            f"Validating {len(preconditions)} preconditions for migration "
            f"{migration.version} ({direction})"
        )

        validator = PreconditionValidator(self.connection)
        try:
            validator.validate(
                preconditions,
                migration_version=migration.version,
                migration_name=migration.name,
            )
            logger.debug(f"All preconditions passed for migration {migration.version}")
        except PreconditionValidationError as e:
            logger.error(f"Precondition validation failed for migration {migration.version}: {e}")
            raise

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
                INSERT INTO tb_confiture
                    (slug, version, name, execution_time_ms, checksum)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (slug, migration.version, migration.name, execution_time_ms, checksum),
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
        from datetime import datetime

        from confiture.core.connection import load_migration_class

        # Load the migration class to get version and name
        migration_class = load_migration_class(migration_file)

        # Create a minimal instance just to read attributes
        # We need to pass a connection but won't use it
        migration = migration_class(connection=self.connection)

        # Check if already applied
        applied_versions = set(self.get_applied_versions())
        if migration.version in applied_versions:
            logger.info(f"Migration {migration.version} already applied, skipping")
            return migration.version

        # Generate slug with baseline marker
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{migration.name}_{timestamp}_baseline"

        # Compute checksum
        checksum = compute_checksum(migration_file)

        # Record in tracking table with execution_time_ms = 0 (not executed)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tb_confiture
                    (slug, version, name, execution_time_ms, checksum)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (slug, migration.version, migration.name, 0, checksum),
            )

        self.connection.commit()
        logger.info(
            f"Marked migration {migration.version} ({migration.name}) as applied ({reason})"
        )

        return migration.version

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
        # Check if applied
        if not self._is_applied(migration.version):
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) "
                "has not been applied, cannot rollback"
            )

        # Validate preconditions before rolling back
        if not skip_preconditions:
            self._validate_preconditions(
                migration, direction="down", preconditions=migration.down_preconditions
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
                DELETE FROM tb_confiture
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
                DELETE FROM tb_confiture
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
                FROM tb_confiture
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
                FROM tb_confiture
                ORDER BY applied_at ASC
            """)
            return [row[0] for row in cursor.fetchall()]

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
        if migrations_dir is None:
            migrations_dir = Path("db") / "migrations"

        if not migrations_dir.exists():
            return []

        # Find all .py files (excluding __pycache__, __init__.py)
        py_files = [
            f
            for f in migrations_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ]

        # Find all .up.sql files (SQL migrations)
        sql_files = list(migrations_dir.glob("*.up.sql"))

        # Combine and sort by version
        all_files = py_files + sql_files
        migration_files = sorted(all_files, key=lambda f: self._version_from_filename(f.name))

        return migration_files

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
        if migrations_dir is None:
            migrations_dir = Path("db") / "migrations"

        if not migrations_dir.exists():
            return []

        # Find all .sql files
        all_sql_files = set(migrations_dir.glob("*.sql"))

        # Find all properly named migration files
        expected_files = set(migrations_dir.glob("*.up.sql")) | set(
            migrations_dir.glob("*.down.sql")
        )

        # Orphaned files are SQL files that don't match the expected pattern
        orphaned = all_sql_files - expected_files
        return sorted(orphaned, key=lambda f: f.name)

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
        if migrations_dir is None:
            migrations_dir = Path("db") / "migrations"

        if not migrations_dir.exists():
            return {"renamed": [], "errors": []}

        orphaned_files = self.find_orphaned_sql_files(migrations_dir)
        renamed: list[tuple[str, str]] = []
        errors: list[tuple[str, str]] = []

        for orphaned_file in orphaned_files:
            # Suggest renaming by adding .up suffix before .sql
            # Example: 001_create_users.sql -> 001_create_users.up.sql
            old_name = orphaned_file.name
            new_name = f"{orphaned_file.stem}.up.sql"
            new_path = orphaned_file.parent / new_name

            try:
                if not dry_run:
                    # Check if target already exists
                    if new_path.exists():
                        errors.append((old_name, f"Target file already exists: {new_name}"))
                        continue

                    # Rename the file
                    orphaned_file.rename(new_path)
                    logger.info(f"Renamed migration file: {old_name} -> {new_name}")

                renamed.append((old_name, new_name))
            except Exception as e:
                errors.append((old_name, str(e)))
                logger.error(f"Failed to rename {old_name}: {e}")

        return {"renamed": renamed, "errors": errors}

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

        Supports both Python and SQL migrations:
        - Python: {version}_{name}.py -> "001_create_users.py" -> "001"
        - SQL: {version}_{name}.up.sql -> "001_create_users.up.sql" -> "001"

        Args:
            filename: Migration filename

        Returns:
            Version string

        Example:
            >>> migrator._version_from_filename("042_add_column.py")
            "042"
            >>> migrator._version_from_filename("042_add_column.up.sql")
            "042"
        """
        # Remove SQL file extensions if present
        if filename.endswith(".up.sql"):
            filename = filename[:-7]  # Remove ".up.sql"
        elif filename.endswith(".down.sql"):
            filename = filename[:-9]  # Remove ".down.sql"

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

    def check_preconditions(
        self,
        migration: Migration,
        direction: str = "up",
    ) -> tuple[bool, list[tuple[Any, str]]]:
        """Check migration preconditions without running the migration.

        Useful for:
        - CI/CD pipelines to verify preconditions before deployment
        - Pre-flight validation in production
        - Debugging precondition issues

        Args:
            migration: Migration instance to check
            direction: "up" or "down" to specify which preconditions to check

        Returns:
            Tuple of (all_passed, failures):
                - all_passed: True if all preconditions passed
                - failures: List of (precondition, error_message) for failures

        Example:
            >>> migrator = Migrator(connection=conn)
            >>> migration = MyMigration(connection=conn)
            >>> passed, failures = migrator.check_preconditions(migration)
            >>> if not passed:
            ...     for precondition, error in failures:
            ...         print(f"FAILED: {precondition}: {error}")
        """
        preconditions = (
            migration.up_preconditions if direction == "up" else migration.down_preconditions
        )

        if not preconditions:
            return (True, [])

        validator = PreconditionValidator(self.connection)
        return validator.check(preconditions)
