"""The one apply loop — planning, checksum verification and application under the lock.

Split out of ``session.py`` (Phase 03, Cycle 9). Every function takes the
``MigratorSession`` as its first argument; the session's methods delegate here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.core._migrator import policy as _policy
from confiture.core._migrator.discovery import parse_migration_filename
from confiture.core._migrator.events import UpObserver, emit
from confiture.core.checksum import (
    ChecksumConfig,
    ChecksumMismatchBehavior,
    MigrationChecksumVerifier,
)
from confiture.exceptions import MigrationError

if TYPE_CHECKING:
    from confiture.core._migrator.session import MigratorSession
    from confiture.models.results import (
        MigrateUpResult,
        MigrationApplied,
    )


def _plan_under_lock(session: MigratorSession, *, force: bool) -> tuple[list[Path], list[str]]:
    """See :meth:`MigratorSession._plan_under_lock`."""
    assert session._migrator is not None
    session._migrator.initialize()

    # Resolve migrations to apply
    all_files = session._migrator.find_migration_files(migrations_dir=session._migrations_dir)
    if force:
        pending_files = all_files
    else:
        pending_files = session._migrator.find_pending(migrations_dir=session._migrations_dir)

    apply_versions = {session._migrator._version_from_filename(f.name) for f in pending_files}
    skipped_versions = [
        session._migrator._version_from_filename(f.name)
        for f in all_files
        if session._migrator._version_from_filename(f.name) not in apply_versions
    ]

    return pending_files, skipped_versions


def _verify_checksums(
    session: MigratorSession, *, enabled: bool, on_mismatch: str
) -> tuple[bool, list[str]]:
    """See :meth:`MigratorSession._verify_checksums`."""
    assert session._migrator is not None
    if not enabled:
        return False, []
    behaviour = ChecksumMismatchBehavior(on_mismatch)
    verifier = MigrationChecksumVerifier(
        session._conn,
        ChecksumConfig(enabled=True, on_mismatch=behaviour),
        migration_table=session._migrator.migration_table,
    )
    mismatches = verifier.verify_all(session._migrations_dir)
    if not mismatches:
        return True, []
    return False, [
        f"Checksum mismatch: {m.version}_{m.name} was modified after it was applied"
        for m in mismatches
    ]


def _up_under_lock(
    session: MigratorSession,
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
    """See :meth:`MigratorSession._up_under_lock`."""
    import time as _time

    import confiture.core.migrator as _m
    from confiture.models.results import (
        MigrateUpResult,
        MigrationApplied,
        SkippedMigration,
    )

    assert session._migrator is not None
    if auto_baseline is not None:
        _policy.auto_baseline(
            conn=session._conn,
            migrator=session._migrator,
            migrations_dir=session._migrations_dir,
            snapshots_dir=auto_baseline,
            on_event=on_event,
        )
    pending_files, skipped_versions = session._plan_under_lock(force=force)
    if _policy.wants_view_helpers(install_view_helpers, session._config):
        _policy.install_view_helpers(session._conn, on_event)
    checksums_verified, checksum_warnings = session._verify_checksums(
        enabled=verify_checksums and not force, on_mismatch=on_checksum_mismatch
    )
    if checksums_verified:
        emit(on_event, "checksums_verified")
    effective_strict = _policy.resolve_strict_mode(strict_mode, session._config)
    pending_versions: list[str] = []
    for migration_file in pending_files:
        version, name = parse_migration_filename(migration_file.name)
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
        preflight_result = session.preflight()
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
        return session._up_dry_run_execute(
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
            migration = migration_class(connection=session._conn)
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
                    session._migrator._version_from_filename(f.name)
                    for f in pending_files[idx + 1 :]
                ]
                halted = True
                break

            emit(on_event, "applying", version=migration.version, name=migration.name)
            try:
                start = _time.time()
                session._migrator.apply(migration, force=force, migration_file=migration_file)
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
    session: MigratorSession,
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
    """See :meth:`MigratorSession._up_dry_run_execute`."""
    import time as _time

    import confiture.core.migrator as _m
    from confiture.models.results import MigrateUpResult, MigrationApplied

    # Invariant: this helper only runs inside an active session (callers guard).
    assert session._conn is not None
    assert session._migrator is not None

    migrations_tested: list[MigrationApplied] = []
    total_time = 0
    failed_exception: Exception | None = None

    try:
        session._conn.execute("SAVEPOINT dry_run_execute")
        try:
            for migration_file in pending_files:
                migration_class = _m.load_migration_class(migration_file)
                migration = migration_class(connection=session._conn)
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
                    session._migrator.apply(
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
            session._conn.execute("ROLLBACK TO SAVEPOINT dry_run_execute")
            session._conn.execute("RELEASE SAVEPOINT dry_run_execute")
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


def _apply_strict_mode(migration: Any, strict: bool) -> None:
    """Strict mode from the session/config, unless the class already pins it."""
    if strict and not getattr(type(migration), "strict_mode", False):
        migration.strict_mode = True


def up(
    session: MigratorSession,
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
    """See :meth:`MigratorSession.up`."""

    import confiture.core.migrator as _m

    # Import through confiture.core.migrator so tests can patch
    # confiture.core.migrator.load_migration_class and confiture.core.migrator.MigrationLock.
    from confiture.exceptions import ConfigurationError

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )

    if dry_run and dry_run_execute:
        raise ConfigurationError(
            "Cannot use both dry_run and dry_run_execute",
            resolution_hint="Use dry_run for analysis-only, or dry_run_execute for SAVEPOINT-based verification.",
        )

    if not session._migrations_dir.exists():
        raise MigrationError(
            f"Migrations directory not found: {session._migrations_dir.absolute()}",
            resolution_hint=f"Create the migrations directory at {session._migrations_dir} or run 'confiture migrate generate' to scaffold it",
        )

    # Everything from here runs under the migration lock (ENG-03): the plan
    # is made against the ledger as the lock holder sees it, so a second
    # deployer that waited for the lock finds nothing left to apply instead
    # of failing on what the first one just recorded — and two first-run
    # deployers cannot race the ledger CREATE.
    lock_config = _m.LockConfig(
        enabled=not no_lock, timeout_ms=lock_timeout, command=session._command
    )
    lock = _m.MigrationLock(session._conn, lock_config)
    with lock.acquire():
        if not no_lock:
            emit(on_event, "lock_acquired")
        return session._up_under_lock(
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


def apply_one(
    session: MigratorSession,
    version: str,
    *,
    applied_by: str | None = None,
    lock_timeout: int = 30000,
    no_lock: bool = False,
) -> MigrationApplied:
    """See :meth:`MigratorSession.apply_one`."""
    import time as _time

    import confiture.core.migrator as _m
    from confiture.exceptions import ConfigurationError, MigrationError
    from confiture.models.results import MigrationApplied

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )
    lock = _m.MigrationLock(
        session._conn,
        _m.LockConfig(enabled=not no_lock, timeout_ms=lock_timeout, command=session._command),
    )
    with lock.acquire():
        session._migrator.initialize()
        if version in set(session._migrator.get_applied_versions()):
            raise MigrationError(
                f"Migration {version} is already applied.",
                version=version,
                error_code="MIGR_001",
                context={"reason": "already_applied"},
                resolution_hint="Nothing to do — the version is already in the tracking table.",
            )
        files = session._migrator.find_migration_files(migrations_dir=session._migrations_dir)
        matches = [f for f in files if session._migrator._version_from_filename(f.name) == version]
        if not matches:
            raise MigrationError(
                f"No migration with version {version} in {session._migrations_dir}",
                version=version,
                error_code="MIGR_100",
                resolution_hint="Check the version and --migrations-dir.",
            )
        migration_file = sorted(matches)[0]
        migration = _m.load_migration_class(migration_file)(connection=session._conn)
        start = _time.time()
        session._migrator.apply(migration, migration_file=migration_file, applied_by=applied_by)
        return MigrationApplied(
            version=migration.version,
            name=migration.name,
            execution_time_ms=int((_time.time() - start) * 1000),
        )
