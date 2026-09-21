"""One pipeline applies a migration, whatever runs its body.

A migration's body runs one of three ways: inside a transaction behind a savepoint
(:class:`Transactional`), in autocommit for the DDL that cannot run in a transaction
(:class:`Autocommit`), or as ``--online`` expand/contract stages with a checkpoint
after each (:class:`Online`). The first two were free functions that took the engine
and called back into it; the third was reached from the apply loop *past* the
engine, so it never asked a precondition and never ran a hook.

Every migration now goes through :class:`ApplyPipeline`: the gates each strategy
shares — already applied, a body that must commit asked to run inside a caller's
savepoint, the preconditions — then the strategy, which runs the body between the
``BEFORE_EXECUTE`` and ``AFTER_EXECUTE`` hooks and records the ledger row. A
strategy receives its collaborators as arguments (:class:`ApplyStage`); none of
them knows the engine exists.

The ledger writes (:func:`record_applied`, :func:`mark_applied`), the dry run and the
precondition checks live here too, and still take the engine; they are the next
stage to be given their collaborators.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import psycopg
import psycopg.pq
from psycopg import sql as pgsql

from confiture.core._migrator._constants import _VIEW_COLUMN_RENAME_RE
from confiture.core._migrator.loader import load_migration_class
from confiture.core._migrator.ports import ApplyStage, EngineHost, Strategy
from confiture.core.checksum import compute_checksum
from confiture.core.dry_run import DryRunExecutor, DryRunResult
from confiture.core.expand_contract import StagedPlan
from confiture.core.hooks import HookError
from confiture.core.hooks.phases import HookPhase
from confiture.core.ledger import LedgerRow, record_migration
from confiture.core.preconditions import PreconditionValidationError, PreconditionValidator
from confiture.core.step_runner import CheckpointStore, RunOptions, run, steps_table
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration

logger = logging.getLogger(__name__)

_DEPENDENT_VIEWS_HINT = (
    "Dependent views block this column change. "
    "Call confiture.save_and_drop_dependent_views() before the ALTER "
    "and confiture.recreate_saved_views() after it. "
    "If you renamed a column, views referencing the old name cannot be "
    "auto-recreated — check SELECT schema_name, view_name, error_message, "
    "definition FROM confiture.saved_views for preserved definitions"
)


def create_savepoint(connection: Any, name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("SAVEPOINT {}").format(pgsql.Identifier(name)))


def release_savepoint(connection: Any, name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("RELEASE SAVEPOINT {}").format(pgsql.Identifier(name)))


def rollback_to_savepoint(connection: Any, name: str, *, commit: bool = True) -> None:
    """Undo to *name*; with ``commit``, end the transaction too (a full rollback if that fails)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(pgsql.SQL("ROLLBACK TO SAVEPOINT {}").format(pgsql.Identifier(name)))
        if commit:
            connection.commit()
    except psycopg.Error:
        if commit:
            connection.rollback()
        else:
            raise


def _hint(error: Exception, default: str) -> str:
    if isinstance(error, psycopg.Error) and _VIEW_COLUMN_RENAME_RE.search(str(error)):
        return _DEPENDENT_VIEWS_HINT
    return default


def _elapsed_ms(started: float | None) -> int:
    return 0 if started is None else int((time.perf_counter() - started) * 1000)


def _guard_the_envelope(connection: Any, migration: Migration) -> None:
    """A body that issued COMMIT or ROLLBACK broke the transaction confiture holds (#133).

    After a clean ``up()`` the connection is expected INTRANS; INERROR is the
    surrounding exception path's. Any other status means the body ended the
    transaction itself, and the migration cannot be recorded safely. A test double
    whose status is not a real ``TransactionStatus`` is not judged.
    """
    status = connection.info.transaction_status
    if isinstance(status, psycopg.pq.TransactionStatus) and status not in (
        psycopg.pq.TransactionStatus.INTRANS,
        psycopg.pq.TransactionStatus.INERROR,
    ):
        raise MigrationError(
            f"Migration {migration.version} ({migration.name}) issued "
            f"an explicit COMMIT or ROLLBACK in its body, breaking "
            f"confiture's transaction envelope "
            f"(connection status: {status.name}).",
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


def _between_hooks(
    stage: ApplyStage,
    migration: Migration,
    *,
    body: Callable[[], None],
    then: Callable[[int], None],
    failed: Callable[[Exception], Exception],
    prepare: Callable[[], None] = lambda: None,
) -> None:
    """``BEFORE_EXECUTE``, the body, ``AFTER_EXECUTE``, then *then* with the elapsed ms.

    A failure anywhere runs ``AFTER_EXECUTE`` with ``success=False`` and raises what
    *failed* makes of it — the error itself, or the ``MigrationError`` the strategy
    reports — after the strategy has cleaned up in it.
    """
    started: float | None = None
    try:
        prepare()
        stage.trigger_hook(HookPhase.BEFORE_EXECUTE, migration, execution_time_ms=0, success=False)
        started = time.perf_counter()
        body()
        elapsed = _elapsed_ms(started)
        stage.trigger_hook(
            HookPhase.AFTER_EXECUTE, migration, execution_time_ms=elapsed, success=True
        )
        then(elapsed)
    # Reason: migration and hook code is user code; any failure runs the failure hooks and is re-raised
    except Exception as e:
        stage.trigger_hook(
            HookPhase.AFTER_EXECUTE,
            migration,
            execution_time_ms=_elapsed_ms(started),
            success=False,
            error=str(e),
        )
        raised = failed(e)
        if raised is e:
            raise
        raise raised from e


class Transactional:
    """The body in the connection's transaction, behind a savepoint it rolls back to on failure."""

    transactional: ClassVar[bool] = True

    def execute(
        self,
        stage: ApplyStage,
        migration: Migration,
        *,
        already_applied: bool,
        migration_file: Path | None,
        commit: bool,
        applied_by: str | None,
    ) -> None:
        savepoint = f"migration_{migration.version}"

        def body() -> None:
            logger.debug(f"Executing DDL for migration {migration.version}")
            migration.up()
            _guard_the_envelope(stage.connection, migration)

        def then(elapsed: int) -> None:
            # A forced re-apply runs the body again but writes no second row.
            if not already_applied:
                stage.record(migration, elapsed, migration_file, applied_by=applied_by)
            release_savepoint(stage.connection, savepoint)
            if commit:
                stage.connection.commit()
            logger.info(f"Successfully applied migration {migration.version} ({migration.name})")

        def failed(e: Exception) -> Exception:
            rollback_to_savepoint(stage.connection, savepoint, commit=commit)
            if isinstance(e, (MigrationError, HookError)):
                return e
            return MigrationError(
                f"Failed to apply migration {migration.version} ({migration.name}): {e}",
                migration.version,
                migration.name,
                resolution_hint=_hint(
                    e,
                    "Check the migration SQL for errors and ensure the database is in the "
                    "expected state",
                ),
            )

        _between_hooks(
            stage,
            migration,
            prepare=lambda: create_savepoint(stage.connection, savepoint),
            body=body,
            then=then,
            failed=failed,
        )


class Autocommit:
    """The body in autocommit — for DDL no transaction may hold, with no rollback on failure."""

    transactional: ClassVar[bool] = False

    def execute(
        self,
        stage: ApplyStage,
        migration: Migration,
        *,
        already_applied: bool,
        migration_file: Path | None,
        commit: bool,  # noqa: ARG002
        applied_by: str | None,
    ) -> None:
        logger.warning(
            f"Running migration {migration.version} in non-transactional mode. "
            "Manual cleanup may be required on failure."
        )

        def then(elapsed: int) -> None:
            if not already_applied:
                stage.record(migration, elapsed, migration_file, applied_by=applied_by)
            logger.info(
                f"Successfully applied non-transactional migration "
                f"{migration.version} ({migration.name})"
            )

        def failed(e: Exception) -> Exception:
            logger.error(
                f"Non-transactional migration {migration.version} failed. "
                "Manual cleanup may be required."
            )
            return MigrationError(
                f"Failed to apply non-transactional migration "
                f"{migration.version} ({migration.name}): {e}. "
                "Manual cleanup may be required.",
                migration.version,
                migration.name,
                resolution_hint=_hint(
                    e,
                    "Inspect the database for partial changes and manually revert any "
                    "applied DDL statements",
                ),
            )

        connection = stage.connection
        connection.commit()
        original_autocommit = connection.autocommit
        connection.autocommit = True
        try:
            _between_hooks(stage, migration, body=migration.up, then=then, failed=failed)
        finally:
            connection.autocommit = original_autocommit


@dataclass(frozen=True)
class Online:
    """The body as its expand/contract stages, each checkpointed in ``<ledger>_steps``.

    The stages commit as they go, so this is not a body a caller's savepoint can
    hold. What it did not do before it was a strategy is what every other body does:
    run between its hooks, after its preconditions.
    """

    transactional: ClassVar[bool] = False

    plans: tuple[StagedPlan, ...]
    options: RunOptions
    ledger_table: str

    def execute(
        self,
        stage: ApplyStage,
        migration: Migration,
        *,
        already_applied: bool,
        migration_file: Path | None,
        commit: bool,  # noqa: ARG002
        applied_by: str | None,
    ) -> None:
        store = CheckpointStore(stage.connection, steps_table(self.ledger_table))
        store.ensure()

        def body() -> None:
            for index, staged in enumerate(self.plans):
                run(
                    staged,
                    stage.connection,
                    migration=migration.version,
                    store=store,
                    plan_index=index,
                    options=self.options,
                )

        def then(elapsed: int) -> None:
            if not already_applied:
                stage.record(migration, elapsed, migration_file, applied_by=applied_by)
            stage.connection.commit()

        _between_hooks(stage, migration, body=body, then=then, failed=lambda e: e)


def classic(migration: Migration) -> Strategy:
    """The strategy a migration declares: transactional unless it says otherwise."""
    return Transactional() if migration.transactional else Autocommit()


@dataclass(frozen=True)
class ApplyPipeline:
    """The gates every migration passes, then its strategy.

    ``is_applied(version)`` reads the ledger; ``validate(migration)`` asks the
    migration's ``up_preconditions`` and raises when one fails.
    """

    stage: ApplyStage
    is_applied: Callable[[str], bool]
    validate: Callable[[Migration], None]

    def apply(
        self,
        migration: Migration,
        strategy: Strategy,
        *,
        force: bool = False,
        migration_file: Path | None = None,
        skip_preconditions: bool = False,
        commit: bool = True,
        applied_by: str | None = None,
    ) -> None:
        already_applied = self.is_applied(migration.version)
        if already_applied and not force:
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) has already been applied",
                migration.version,
                migration.name,
                error_code="MIGR_101",
                resolution_hint="Use --force to re-apply this migration, or run 'confiture migrate status' to review applied migrations",
            )
        if not strategy.transactional and not commit:
            # ``commit=False`` means "inside a SAVEPOINT — persist nothing". A body
            # that commits as it goes cannot honour that, so it must not be asked to.
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) is non-transactional and "
                "cannot run with commit=False (inside a SAVEPOINT)",
                version=migration.version,
                error_code="MIGR_108",
                resolution_hint=(
                    "Run it for real with `migrate up`, or exclude it from the dry run; "
                    "`session.up(dry_run_execute=True)` skips non-transactional migrations."
                ),
            )
        if not skip_preconditions:
            self.validate(migration)
        strategy.execute(
            self.stage,
            migration,
            already_applied=already_applied,
            migration_file=migration_file,
            commit=commit,
            applied_by=applied_by,
        )


def validate_preconditions(
    migrator: EngineHost,
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


def record_applied(
    migrator: EngineHost,
    migration: Migration,
    execution_time_ms: int,
    migration_file: Path | None = None,
    *,
    applied_by: str | None = None,
) -> None:
    """Record a migration ``up()`` just applied, with its file's checksum."""
    checksum = None
    if migration_file is not None and migration_file.exists():
        checksum = compute_checksum(migration_file)
        logger.debug(f"Computed checksum for {migration.version}: {checksum[:16]}...")
    record_migration(
        migrator.connection,
        migrator._table_ident,
        LedgerRow(
            version=migration.version,
            name=migration.name,
            execution_time_ms=execution_time_ms,
            checksum=checksum,
            applied_by=applied_by,
        ),
    )


def mark_applied(
    migrator: EngineHost,
    migration_file: Path,
    reason: str = "baseline",
) -> str:
    """Mark a migration as applied without executing it.

    See :meth:`MigrationEngine.mark_applied` for the full contract.
    """

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

    # Compute checksum
    checksum = compute_checksum(migration_file)

    # Record in tracking table with execution_time_ms = 0 (not executed)
    record_migration(
        migrator.connection,
        migrator._table_ident,
        LedgerRow(
            version=migration.version,
            name=migration.name,
            checksum=checksum,
            reason=reason,
        ),
    )

    migrator.connection.commit()
    logger.info(f"Marked migration {migration.version} ({migration.name}) as applied ({reason})")

    return migration.version


def warn_mixed_transactional_modes(migration_files: list[Path]) -> None:
    """Warn if batch contains both transactional and non-transactional migrations."""
    if len(migration_files) <= 1:
        return

    transactional_migrations: list[str] = []
    non_transactional_migrations: list[str] = []

    for migration_file in migration_files:
        migration_class = load_migration_class(migration_file)

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


def dry_run(migrator: EngineHost, migration: Migration) -> DryRunResult:
    """Test a migration without making permanent changes.

    See :meth:`MigrationEngine.dry_run` for the full contract.
    """
    statements = migration.get_up_sql_statements()
    if not statements:
        # Fallback to old simulation mode for Python migrations
        # Note: This creates a basic simulation result since the old executor
        # is no longer available. In practice, Python migrations should implement
        # get_up_sql_statements() or use SQL-based migrations.

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
    migrator: EngineHost,
    migration: Migration,
    direction: str = "up",
) -> tuple[bool, list[tuple[Any, str]]]:
    """Check migration preconditions without running the migration.

    See :meth:`MigrationEngine.check_preconditions` for the full contract.
    """
    preconditions = (
        migration.up_preconditions if direction == "up" else migration.down_preconditions
    )

    if not preconditions:
        return (True, [])

    validator = PreconditionValidator(migrator.connection)
    return validator.check(preconditions)
