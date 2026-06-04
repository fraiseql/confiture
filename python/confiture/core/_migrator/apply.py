"""Apply / migrate-up / dry-run concern for ``Migrator``.

Peeled out of ``engine.py``. Free functions taking the
``Migrator`` instance as their first argument; the class keeps thin delegating
methods, so its public surface and patch targets are unchanged. Cross-method
calls go through ``migrator.<method>()`` (the delegators) so existing test
seams that mock those methods on the instance keep working. Pure refactor.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.pq
from psycopg import sql as pgsql

from confiture.core._migrator._constants import _VIEW_COLUMN_RENAME_RE
from confiture.core.checksum import (
    ChecksumConfig,
    MigrationChecksumVerifier,
    compute_checksum,
)
from confiture.core.connection import get_migration_class, load_migration_module
from confiture.core.dry_run import DryRunExecutor, DryRunResult
from confiture.core.hooks import HookError
from confiture.core.hooks.phases import HookPhase
from confiture.core.locking import LockConfig, MigrationLock
from confiture.core.preconditions import PreconditionValidationError, PreconditionValidator
from confiture.core.progress import ProgressManager
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration

if TYPE_CHECKING:
    from confiture.core._migrator.engine import Migrator

logger = logging.getLogger(__name__)


def apply(
    migrator: Migrator,
    migration: Migration,
    force: bool = False,
    migration_file: Path | None = None,
    skip_preconditions: bool = False,
    *,
    commit: bool = True,
    applied_by: str | None = None,
) -> None:
    """Apply a migration and record it in the tracking table.

    See :meth:`Migrator.apply` for the full contract.
    """
    already_applied = migrator._is_applied(migration.version)

    if not force and already_applied:
        raise MigrationError(
            f"Migration {migration.version} ({migration.name}) has already been applied",
            migration.version,
            migration.name,
            error_code="MIGR_101",
            resolution_hint="Use --force to re-apply this migration, or run 'confiture migrate status' to review applied migrations",
        )

    # Validate preconditions before applying
    if not skip_preconditions:
        migrator._validate_preconditions(
            migration, direction="up", preconditions=migration.up_preconditions
        )

    if migration.transactional:
        migrator._apply_transactional(
            migration,
            already_applied,
            migration_file,
            commit=commit,
            applied_by=applied_by,
        )
    else:
        migrator._apply_non_transactional(
            migration, already_applied, migration_file, applied_by=applied_by
        )


def validate_preconditions(
    migrator: Migrator,
    migration: Migration,
    direction: str,
    preconditions: list,
) -> None:
    """Validate migration preconditions before execution.

    Raises:
        PreconditionValidationError: If any precondition fails.
    """
    if not preconditions:
        return

    logger.debug(
        f"Validating {len(preconditions)} preconditions for migration "
        f"{migration.version} ({direction})"
    )

    validator = PreconditionValidator(migrator.connection)
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


def apply_transactional(
    migrator: Migrator,
    migration: Migration,
    already_applied: bool,
    migration_file: Path | None = None,
    *,
    commit: bool = True,
    applied_by: str | None = None,
) -> None:
    """Apply migration within a transaction using savepoints.

    See :meth:`Migrator._apply_transactional` for the full contract.
    """
    savepoint_name = f"migration_{migration.version}"
    execution_time_ms = 0
    success = False

    try:
        migrator._create_savepoint(savepoint_name)

        # Trigger BEFORE_EXECUTE hook
        migrator._trigger_hook(
            HookPhase.BEFORE_EXECUTE,
            migration,
            execution_time_ms=0,
            success=False,
        )

        # Execute migration DDL
        logger.debug(f"Executing DDL for migration {migration.version}")
        start_time = time.perf_counter()
        migration.up()
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        # #133: a migration body that issues COMMIT/ROLLBACK silently
        # breaks confiture's outer transaction envelope. After a clean
        # up() we expect the connection to be INTRANS; INERROR is handled
        # by the surrounding exception path. Any other status means the
        # body committed/rolled back and we cannot safely record the
        # migration.
        #
        # Guard against test doubles: if a unit test passes a mock
        # connection whose ``info.transaction_status`` isn't an actual
        # ``TransactionStatus`` value, skip the check rather than
        # false-positive on the mock.
        tx_status = migrator.connection.info.transaction_status
        if isinstance(tx_status, psycopg.pq.TransactionStatus) and tx_status not in (
            psycopg.pq.TransactionStatus.INTRANS,
            psycopg.pq.TransactionStatus.INERROR,
        ):
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) issued "
                f"an explicit COMMIT or ROLLBACK in its body, breaking "
                f"confiture's transaction envelope "
                f"(connection status: {tx_status.name}).",
                migration.version,
                migration.name,
                error_code="MIGR_107",
                resolution_hint=(
                    "Remove any explicit COMMIT or ROLLBACK from the migration body. "
                    "Confiture manages the outer transaction; embedded transaction "
                    "control leaves the database in an unrecoverable state if a "
                    "subsequent statement fails. If you need autocommit semantics, "
                    "set transactional = False on the migration."
                ),
            )
        success = True

        # Trigger AFTER_EXECUTE hook
        migrator._trigger_hook(
            HookPhase.AFTER_EXECUTE,
            migration,
            execution_time_ms=execution_time_ms,
            success=True,
        )

        # Only record the migration if it's not already applied
        # In force mode, we re-apply but don't re-record
        if not already_applied:
            migrator._record_migration(
                migration, execution_time_ms, migration_file, applied_by=applied_by
            )
        migrator._release_savepoint(savepoint_name)

        if commit:
            migrator.connection.commit()
        logger.info(f"Successfully applied migration {migration.version} ({migration.name})")

    except Exception as e:
        # Trigger AFTER_EXECUTE hook for failure case
        if "start_time" in locals():
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        migrator._trigger_hook(
            HookPhase.AFTER_EXECUTE,
            migration,
            execution_time_ms=execution_time_ms,
            success=False,
            error=str(e),
        )

        migrator._rollback_to_savepoint(savepoint_name, commit=commit)
        if isinstance(e, (MigrationError, HookError)):
            raise
        hint = "Check the migration SQL for errors and ensure the database is in the expected state"
        if isinstance(e, psycopg.Error) and _VIEW_COLUMN_RENAME_RE.search(str(e)):
            hint = (
                "Dependent views block this column change. "
                "Call confiture.save_and_drop_dependent_views() before the ALTER "
                "and confiture.recreate_saved_views() after it. "
                "If you renamed a column, views referencing the old name cannot be "
                "auto-recreated — check SELECT schema_name, view_name, error_message, "
                "definition FROM confiture.saved_views for preserved definitions"
            )
        raise MigrationError(
            f"Failed to apply migration {migration.version} ({migration.name}): {e}",
            migration.version,
            migration.name,
            resolution_hint=hint,
        ) from e


def apply_non_transactional(
    migrator: Migrator,
    migration: Migration,
    already_applied: bool,
    migration_file: Path | None = None,
    *,
    applied_by: str | None = None,
) -> None:
    """Apply migration in autocommit mode (no transaction).

    WARNING: If this fails, manual cleanup may be required.
    """
    logger.warning(
        f"Running migration {migration.version} in non-transactional mode. "
        "Manual cleanup may be required on failure."
    )

    # Ensure any pending transaction is committed
    migrator.connection.commit()

    # Set autocommit mode
    original_autocommit = migrator.connection.autocommit
    migrator.connection.autocommit = True

    execution_time_ms = 0
    success = False

    try:
        # Trigger BEFORE_EXECUTE hook
        migrator._trigger_hook(
            HookPhase.BEFORE_EXECUTE,
            migration,
            execution_time_ms=0,
            success=False,
        )

        logger.debug(f"Executing DDL for migration {migration.version} (autocommit)")
        start_time = time.perf_counter()
        migration.up()
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        success = True

        # Trigger AFTER_EXECUTE hook
        migrator._trigger_hook(
            HookPhase.AFTER_EXECUTE,
            migration,
            execution_time_ms=execution_time_ms,
            success=True,
        )

        # Record migration (in autocommit, this commits immediately)
        if not already_applied:
            migrator._record_migration(
                migration, execution_time_ms, migration_file, applied_by=applied_by
            )

        logger.info(
            f"Successfully applied non-transactional migration "
            f"{migration.version} ({migration.name})"
        )

    except Exception as e:
        # Trigger AFTER_EXECUTE hook for failure case
        if "start_time" in locals():
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        migrator._trigger_hook(
            HookPhase.AFTER_EXECUTE,
            migration,
            execution_time_ms=execution_time_ms,
            success=False,
            error=str(e),
        )

        logger.error(
            f"Non-transactional migration {migration.version} failed. "
            "Manual cleanup may be required."
        )
        hint = "Inspect the database for partial changes and manually revert any applied DDL statements"
        if isinstance(e, psycopg.Error) and _VIEW_COLUMN_RENAME_RE.search(str(e)):
            hint = (
                "Dependent views block this column change. "
                "Call confiture.save_and_drop_dependent_views() before the ALTER "
                "and confiture.recreate_saved_views() after it. "
                "If you renamed a column, views referencing the old name cannot be "
                "auto-recreated — check SELECT schema_name, view_name, error_message, "
                "definition FROM confiture.saved_views for preserved definitions"
            )
        raise MigrationError(
            f"Failed to apply non-transactional migration "
            f"{migration.version} ({migration.name}): {e}. "
            "Manual cleanup may be required.",
            migration.version,
            migration.name,
            resolution_hint=hint,
        ) from e

    finally:
        # Restore original autocommit setting
        migrator.connection.autocommit = original_autocommit


def create_savepoint(migrator: Migrator, name: str) -> None:
    """Create a savepoint for transaction rollback."""
    with migrator.connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("SAVEPOINT {}").format(pgsql.Identifier(name)))


def release_savepoint(migrator: Migrator, name: str) -> None:
    """Release a savepoint (commit nested transaction)."""
    with migrator.connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("RELEASE SAVEPOINT {}").format(pgsql.Identifier(name)))


def rollback_to_savepoint(migrator: Migrator, name: str, *, commit: bool = True) -> None:
    """Rollback to a savepoint (undo nested transaction).

    See :meth:`Migrator._rollback_to_savepoint` for the ``commit`` semantics.
    """
    try:
        with migrator.connection.cursor() as cursor:
            cursor.execute(pgsql.SQL("ROLLBACK TO SAVEPOINT {}").format(pgsql.Identifier(name)))
        if commit:
            migrator.connection.commit()
    except Exception:
        if commit:
            # Savepoint rollback failed, do full rollback
            migrator.connection.rollback()
        else:
            raise


def record_migration(
    migrator: Migrator,
    migration: Migration,
    execution_time_ms: int,
    migration_file: Path | None = None,
    *,
    applied_by: str | None = None,
) -> None:
    """Record migration in tracking table with checksum.

    See :meth:`Migrator._record_migration` for the ``applied_by`` contract.
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"{migration.name}_{timestamp}"

    # Compute checksum if file path provided
    checksum = None
    if migration_file is not None and migration_file.exists():
        checksum = compute_checksum(migration_file)
        logger.debug(f"Computed checksum for {migration.version}: {checksum[:16]}...")

    if applied_by is None:
        # Capture the role that opened the connection.  Quoting
        # is unnecessary — current_user is read-only on the server.
        row = migrator.connection.execute("SELECT current_user").fetchone()
        applied_by = row[0] if row else None

    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("""
            INSERT INTO {}
                (id, slug, version, name, execution_time_ms, checksum, applied_by)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s)
            """).format(migrator._table_ident),
            (
                slug,
                migration.version,
                migration.name,
                execution_time_ms,
                checksum,
                applied_by,
            ),
        )


def mark_applied(
    migrator: Migrator,
    migration_file: Path,
    reason: str = "baseline",
) -> str:
    """Mark a migration as applied without executing it.

    See :meth:`Migrator.mark_applied` for the full contract.
    """
    from datetime import datetime

    from confiture.core.connection import load_migration_class

    # Load the migration class to get version and name
    migration_class = load_migration_class(migration_file)

    # Create a minimal instance just to read attributes
    # We need to pass a connection but won't use it
    migration = migration_class(connection=migrator.connection)

    # Check if already applied
    applied_versions = set(migrator.get_applied_versions())
    if migration.version in applied_versions:
        logger.info(f"Migration {migration.version} already applied, skipping")
        return migration.version

    # Generate slug with reason marker
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"{migration.name}_{timestamp}_{reason}"

    # Compute checksum
    checksum = compute_checksum(migration_file)

    # Record in tracking table with execution_time_ms = 0 (not executed)
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("""
            INSERT INTO {}
                (id, slug, version, name, execution_time_ms, checksum)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s)
            """).format(migrator._table_ident),
            (slug, migration.version, migration.name, 0, checksum),
        )

    migrator.connection.commit()
    logger.info(
        f"Marked migration {migration.version} ({migration.name}) as applied ({reason})"
    )

    return migration.version


def migrate_up(
    migrator: Migrator,
    force: bool = False,
    migrations_dir: Path | None = None,
    target: str | None = None,
    lock_config: LockConfig | None = None,
    checksum_config: ChecksumConfig | None = None,
    progress: ProgressManager | None = None,
) -> list[str]:
    """Apply pending migrations up to target version.

    See :meth:`Migrator.migrate_up` for the full contract.
    """
    effective_migrations_dir = migrations_dir or Path("db/migrations")

    verify_task = None
    if progress:
        verify_task = progress.add_task("Verifying checksums...", total=None)

    # Verify checksums before running migrations (unless force mode)
    if checksum_config is None:
        checksum_config = ChecksumConfig()

    if checksum_config.enabled and not force:
        verifier = MigrationChecksumVerifier(
            migrator.connection, checksum_config, migration_table=migrator.migration_table
        )
        verifier.verify_all(effective_migrations_dir)

    if progress and verify_task is not None:
        progress.finish_task(verify_task)

    # Create lock manager
    lock = MigrationLock(migrator.connection, lock_config)

    # Acquire lock and run migrations
    with lock.acquire():
        return migrator._migrate_up_internal(force, migrations_dir, target, progress=progress)


def migrate_up_internal(
    migrator: Migrator,
    force: bool = False,
    migrations_dir: Path | None = None,
    target: str | None = None,
    progress: ProgressManager | None = None,
) -> list[str]:
    """Internal implementation of migrate_up (called within lock)."""
    discover_task = None
    if progress:
        discover_task = progress.add_task("Discovering migrations...", total=None)

    # Find migrations to apply
    if force:
        # In force mode, apply all migrations regardless of state
        migrations_to_apply = migrator.find_migration_files(migrations_dir)
    else:
        # Normal mode: only apply pending migrations
        migrations_to_apply = migrator.find_pending(migrations_dir)

    if progress and discover_task is not None:
        progress.update(discover_task, len(migrations_to_apply))

    # Check for mixed transactional modes and warn
    migrator._warn_mixed_transactional_modes(migrations_to_apply)

    apply_task = None
    if progress:
        apply_task = progress.add_task("Applying migrations...", total=len(migrations_to_apply))

    applied_versions = []

    for migration_file in migrations_to_apply:
        # Load migration module
        module = load_migration_module(migration_file)
        migration_class = get_migration_class(module)

        # Create migration instance
        migration = migration_class(connection=migrator.connection)

        # Check target
        if target and migration.version > target:
            break

        # Apply migration with file path for checksum computation
        migrator.apply(migration, force=force, migration_file=migration_file)
        applied_versions.append(migration.version)

        # Update progress
        if progress and apply_task is not None:
            progress.update(apply_task, advance=1)

    if progress and apply_task is not None:
        progress.finish_task(apply_task)

    return applied_versions


def warn_mixed_transactional_modes(migration_files: list[Path]) -> None:
    """Warn if batch contains both transactional and non-transactional migrations."""
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


def dry_run(migrator: Migrator, migration: Migration) -> DryRunResult:
    """Test a migration without making permanent changes.

    See :meth:`Migrator.dry_run` for the full contract.
    """
    statements = migration.get_up_sql_statements()
    if not statements:
        # Fallback to old simulation mode for Python migrations
        # Note: This creates a basic simulation result since the old executor
        # is no longer available. In practice, Python migrations should implement
        # get_up_sql_statements() or use SQL-based migrations.
        from confiture.core.dry_run import DryRunResult

        return DryRunResult(
            migration_name=migration.name,
            success=True,
            total_time_ms=0,
            confidence_pct=40,  # Low confidence for unsupported migrations
            statements=[],
        )

    executor = DryRunExecutor(migrator.connection)
    return executor.run(migration_name=migration.name, statements=statements)


def check_preconditions(
    migrator: Migrator,
    migration: Migration,
    direction: str = "up",
) -> tuple[bool, list[tuple[Any, str]]]:
    """Check migration preconditions without running the migration.

    See :meth:`Migrator.check_preconditions` for the full contract.
    """
    preconditions = (
        migration.up_preconditions if direction == "up" else migration.down_preconditions
    )

    if not preconditions:
        return (True, [])

    validator = PreconditionValidator(migrator.connection)
    return validator.check(preconditions)
