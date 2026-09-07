"""The one rollback loop — ``down()``/``down_to()`` planning and execution under the lock.

Split out of ``session.py`` (Phase 03, Cycle 9). Every function takes the
``MigratorSession`` as its first argument; the session's methods delegate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.exceptions import MigrationError

if TYPE_CHECKING:
    from confiture.core._migrator.session import MigratorSession
    from confiture.models.results import (
        DownToResult,
        MigrateDownResult,
    )
import time as _time

from confiture.exceptions import ConfigurationError, RollbackError
from confiture.models.results import MigrationApplied


def _rollback_sequence(
    session: MigratorSession, versions: list[str], *, dry_run: bool = False
) -> tuple[list, int]:
    """See :meth:`MigratorSession._rollback_sequence`."""

    # Import through confiture.core.migrator so tests can patch
    # confiture.core.migrator.load_migration_class.

    assert session._migrator is not None

    migration_files = session._migrator.find_migration_files(migrations_dir=session._migrations_dir)
    by_version = {session._migrator._version_from_filename(f.name): f for f in migration_files}

    rolled_back: list[MigrationApplied] = []
    total_duration_ms = 0

    for version in versions:
        migration_file = by_version.get(version)
        if migration_file is None:
            continue

        migration_class = session.migration_loader(migration_file)
        migration = migration_class(connection=session._conn)

        if not dry_run:
            start = _time.time()
            session._migrator.rollback(migration)
            elapsed = int((_time.time() - start) * 1000)
            total_duration_ms += elapsed
        else:
            elapsed = 0

        rolled_back.append(
            MigrationApplied(
                version=migration.version,
                name=migration.name,
                duration_ms=elapsed,
            )
        )

    return rolled_back, total_duration_ms


def _reversible_versions(session: MigratorSession) -> set[str]:
    """See :meth:`MigratorSession._reversible_versions`."""
    assert session._migrator is not None

    reversible: set[str] = set()
    for f in session._migrator.find_migration_files(migrations_dir=session._migrations_dir):
        version = session._migrator._version_from_filename(f.name)
        if f.name.endswith(".up.sql"):
            down_file = f.parent / f.name.replace(".up.sql", ".down.sql")
            if down_file.exists():
                reversible.add(version)
        else:
            reversible.add(version)
    return reversible


def down(
    session: MigratorSession,
    *,
    steps: int = 1,
    dry_run: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    command: str | None = None,
) -> MigrateDownResult:
    """See :meth:`MigratorSession.down`."""
    import confiture.core.migrator as _m
    from confiture.models.results import MigrateDownResult

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )

    def _plan_and_roll_back(dry: bool) -> tuple[list, int]:
        # Planning reads the ledger; under the lock it sees what the previous
        # writer committed (ENG-03 for the rollback path).
        assert session._migrator is not None
        session._migrator.initialize()
        applied_versions = session._migrator.get_applied_versions()
        if not applied_versions:
            return [], 0
        versions_to_rollback = list(reversed(applied_versions[-steps:]))  # newest → oldest
        return session._rollback_sequence(versions_to_rollback, dry_run=dry)

    if dry_run:
        rolled_back, total_ms = _plan_and_roll_back(True)
    else:
        lock_config = _m.LockConfig(
            enabled=not no_lock, timeout_ms=lock_timeout, command=command or session._command
        )
        lock = _m.MigrationLock(session._conn, lock_config)
        with lock.acquire():
            rolled_back, total_ms = _plan_and_roll_back(False)
    return MigrateDownResult(
        success=True,
        migrations_rolled_back=rolled_back,
        total_duration_ms=total_ms,
    )


def down_to(
    session: MigratorSession,
    target: str,
    *,
    dry_run: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    command: str | None = None,
) -> DownToResult:
    """See :meth:`MigratorSession.down_to`."""
    import confiture.core.migrator as _m
    from confiture.exceptions import ConfigurationError

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )

    if dry_run:
        return _down_to_under_lock(session, target, dry_run=True)
    lock_config = _m.LockConfig(
        enabled=not no_lock, timeout_ms=lock_timeout, command=command or session._command
    )
    lock = _m.MigrationLock(session._conn, lock_config)
    with lock.acquire():
        return _down_to_under_lock(session, target, dry_run=False)


def _down_to_under_lock(session: MigratorSession, target: str, *, dry_run: bool) -> DownToResult:
    """Plan and execute ``down_to`` — the caller holds the lock unless ``dry_run``."""
    from confiture.core._migrator.rollback_planner import (
        REASON_IRREVERSIBLE,
        REASON_TARGET_NEWER,
        plan_down_to,
    )
    from confiture.models.results import DownToResult

    assert session._migrator is not None
    session._migrator.initialize()
    applied = session._migrator.get_applied_versions()  # ASC
    known = {
        session._migrator._version_from_filename(f.name)
        for f in session._migrator.find_migration_files(migrations_dir=session._migrations_dir)
    }
    down_available = session._reversible_versions()

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

    session._rollback_sequence(to_execute, dry_run=False)
    return DownToResult(from_=from_, to=target, rolled_back=to_execute, skipped=skipped)
