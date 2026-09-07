"""The one apply loop — planning, checksum verification and application under the lock.

Split out of ``session.py``. Every function takes the
``MigratorSession`` as its first argument; the session's methods delegate here.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
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
from confiture.exceptions import ConfigurationError, MigrationError, ValidationError
from confiture.models.results import MigrateUpResult, MigrationApplied, SkippedMigration

if TYPE_CHECKING:
    from confiture.core._migrator.session import MigratorSession


def _plan_under_lock(session: MigratorSession, *, force: bool) -> tuple[list[Path], list[str]]:
    """Initialize the ledger and discover what to apply — the caller holds the lock.

    Returns:
        ``(pending_files, skipped_versions)``: the files to apply (every file
        when *force*), and the versions the ledger already records.
    """
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
    """Check every applied migration file against the ledger — the caller holds the lock.

    Returns:
        ``(verified, warnings)``: *verified* is True only when the verifier
        ran and found no mismatch; *warnings* carries the mismatches under
        ``"warn"``. Under ``"fail"`` a mismatch raises
        :class:`~confiture.core.checksum.ChecksumVerificationError`.
    """
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


@dataclass
class _Plan:
    """What ``up`` decided before applying anything, under the lock."""

    pending_files: list[Path]
    skipped_versions: list[str]
    pending_versions: list[str]
    checksums_verified: bool
    checksum_warnings: list[str]
    strict: bool
    loaded: dict[Path, type] = field(default_factory=dict)  # each file's class, loaded once


def _migration_class(session: MigratorSession, plan: _Plan, path: Path) -> type:
    """The migration class for ``path``, loaded once per ``up`` and shared by every step."""
    if path not in plan.loaded:
        plan.loaded[path] = session.migration_loader(path)
    return plan.loaded[path]


@dataclass
class _Applied:
    """What the apply loop did: the migrations it ran and how it stopped."""

    migrations: list[MigrationApplied] = field(default_factory=list)
    skipped_superuser: list[SkippedMigration] = field(default_factory=list)
    pending_after_halt: list[str] = field(default_factory=list)
    total_duration_ms: int = 0
    failure: Exception | None = None
    halted: bool = False


def _up_under_lock(
    session: MigratorSession,
    *,
    allow_destructive: bool,
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
    batch: Any | None = None,
) -> MigrateUpResult:
    """The body of :meth:`MigratorSession.up`, run while the migration lock is held."""
    plan = _plan(
        session,
        force=force,
        verify_checksums=verify_checksums,
        on_checksum_mismatch=on_checksum_mismatch,
        strict_mode=strict_mode,
        auto_baseline=auto_baseline,
        install_view_helpers=install_view_helpers,
        on_event=on_event,
    )
    early = _before_apply(
        session,
        plan,
        dry_run=dry_run,
        require_reversible=require_reversible,
        allow_destructive=allow_destructive,
        target=target,
    )
    if early is not None:
        return early
    if dry_run_execute:
        return _up_dry_run_execute(
            session, plan, target=target, force=force, on_event=on_event, batch=batch
        )
    applied = _apply_pending(
        session, plan, target=target, force=force, on_event=on_event, batch=batch
    )
    return _up_result(plan, applied, force=force)


def _plan(
    session: MigratorSession,
    *,
    force: bool,
    verify_checksums: bool,
    on_checksum_mismatch: str,
    strict_mode: bool | None,
    auto_baseline: Path | None,
    install_view_helpers: bool | None,
    on_event: UpObserver | None,
) -> _Plan:
    """Baseline, plan, view helpers, checksums and strict mode — the lock is held."""
    assert session._migrator is not None
    if auto_baseline is not None:
        _policy.auto_baseline(
            conn=session._conn,
            migrator=session._migrator,
            migrations_dir=session._migrations_dir,
            snapshots_dir=auto_baseline,
            on_event=on_event,
        )
    pending_files, skipped_versions = _plan_under_lock(session, force=force)
    if _policy.wants_view_helpers(install_view_helpers, session._config):
        _policy.install_view_helpers(session._conn, on_event)
    checksums_verified, checksum_warnings = _verify_checksums(
        session, enabled=verify_checksums and not force, on_mismatch=on_checksum_mismatch
    )
    if checksums_verified:
        emit(on_event, "checksums_verified")
    pending_versions: list[str] = []
    for migration_file in pending_files:
        version, name = parse_migration_filename(migration_file.name)
        pending_versions.append(version)
        emit(on_event, "pending", version=version, name=name)
    return _Plan(
        pending_files=pending_files,
        skipped_versions=skipped_versions,
        pending_versions=pending_versions,
        checksums_verified=checksums_verified,
        checksum_warnings=checksum_warnings,
        strict=_policy.resolve_strict_mode(strict_mode, session._config),
    )


def _before_apply(
    session: MigratorSession,
    plan: _Plan,
    *,
    dry_run: bool,
    require_reversible: bool,
    allow_destructive: bool = False,
    target: str | None = None,
) -> MigrateUpResult | None:
    """The result ``up`` returns without applying anything, or ``None`` to go on."""
    if dry_run:
        return MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_duration_ms=0,
            checksums_verified=plan.checksums_verified,
            dry_run=True,
            skipped=plan.skipped_versions,
            warnings=plan.checksum_warnings,
            pending=plan.pending_versions,
        )
    if not plan.pending_files:
        return MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_duration_ms=0,
            checksums_verified=plan.checksums_verified,
            dry_run=False,
            skipped=plan.skipped_versions,
            warnings=plan.checksum_warnings,
        )
    # Reversibility gate — check before any SQL execution
    if require_reversible:
        preflight_result = session.preflight()
        if not preflight_result.all_reversible:
            names = ", ".join(m.version for m in preflight_result.irreversible)
            return MigrateUpResult(
                success=False,
                migrations_applied=[],
                total_duration_ms=0,
                checksums_verified=plan.checksums_verified,
                dry_run=False,
                errors=[
                    f"Irreversible migrations detected (missing .down.sql): {names}. "
                    f"Use require_reversible=False or add .down.sql files."
                ],
                skipped=plan.skipped_versions,
            )
    # Destructive gate — a migration that loses data needs the operator's word
    if not allow_destructive:
        gated = [
            path.name
            for path, version in zip(plan.pending_files, plan.pending_versions, strict=True)
            if not (target and version > target)
            and getattr(_migration_class(session, plan, path), "destructive", False) is True
        ]
        if gated:
            raise ValidationError(
                "Destructive migration refused: data is lost when it applies: " + ", ".join(gated),
                error_code="VALID_002",
                resolution_hint="Review the migration, then run migrate up --allow-destructive",
            )
    return None


def _apply_pending(
    session: MigratorSession,
    plan: _Plan,
    *,
    target: str | None,
    force: bool,
    on_event: UpObserver | None,
    batch: Any | None,
) -> _Applied:
    """Apply the pending files in order; stop at the target, a superuser halt or a failure."""
    assert session._migrator is not None
    applied = _Applied()
    try:
        for idx, migration_file in enumerate(plan.pending_files):
            migration_class = _migration_class(session, plan, migration_file)
            migration = migration_class(connection=session._conn)
            _apply_strict_mode(migration, plan.strict)
            _apply_batch(migration, batch)

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
                applied.skipped_superuser.append(
                    SkippedMigration(
                        version=migration.version,
                        name=migration.name,
                        reason=(
                            "requires_superuser=True; resolve with "
                            f"`confiture migrate apply-as <role> {migration.version}`"
                        ),
                    )
                )
                applied.pending_after_halt = [
                    session._migrator._version_from_filename(f.name)
                    for f in plan.pending_files[idx + 1 :]
                ]
                applied.halted = True
                break

            emit(on_event, "applying", version=migration.version, name=migration.name)
            try:
                start = _time.time()
                session._migrator.apply(migration, force=force, migration_file=migration_file)
                elapsed = int((_time.time() - start) * 1000)
                applied.total_duration_ms += elapsed
                applied.migrations.append(
                    MigrationApplied(
                        version=migration.version,
                        name=migration.name,
                        duration_ms=elapsed,
                    )
                )
                emit(
                    on_event,
                    "applied",
                    version=migration.version,
                    name=migration.name,
                    elapsed_ms=elapsed,
                )
            except Exception as exc:  # Reason: a migration's up() is user code and may raise anything; the failure is recorded and reported
                applied.failure = exc
                emit(
                    on_event,
                    "failed",
                    version=migration.version,
                    name=migration.name,
                    message=str(exc),
                )
                break
    except Exception as exc:  # Reason: loader/constructor of a user migration module may raise anything; recorded and reported
        if applied.failure is None:
            applied.failure = exc
            emit(on_event, "failed", message=str(exc))
    return applied


def _up_result(plan: _Plan, applied: _Applied, *, force: bool) -> MigrateUpResult:
    """The :class:`MigrateUpResult` for what the loop did."""
    if applied.failure is not None:
        return MigrateUpResult(
            success=False,
            migrations_applied=applied.migrations,
            total_duration_ms=applied.total_duration_ms,
            checksums_verified=plan.checksums_verified,
            dry_run=False,
            errors=[str(applied.failure)],
            failure=applied.failure,
            skipped=plan.skipped_versions,
            skipped_superuser=applied.skipped_superuser,
            pending=applied.pending_after_halt,
        )
    return MigrateUpResult(
        success=not applied.halted,
        migrations_applied=applied.migrations,
        total_duration_ms=applied.total_duration_ms,
        checksums_verified=plan.checksums_verified,
        dry_run=False,
        warnings=(["Force mode enabled"] if force else []) + plan.checksum_warnings,
        skipped=plan.skipped_versions,
        skipped_superuser=applied.skipped_superuser,
        pending=applied.pending_after_halt,
    )


def _up_dry_run_execute(
    session: MigratorSession,
    plan: _Plan,
    *,
    target: str | None,
    force: bool,
    on_event: UpObserver | None = None,
    batch: Any | None = None,
) -> MigrateUpResult:
    """Execute pending migrations inside a SAVEPOINT, then roll back.

    This catches real SQL errors (syntax, constraints, type mismatches)
    without persisting any changes. Non-transactional DDL (e.g. ``CREATE
    INDEX CONCURRENTLY``) cannot run inside a SAVEPOINT and is skipped.
    """
    # Invariant: this helper only runs inside an active session (callers guard).
    assert session._conn is not None
    assert session._migrator is not None

    migrations_tested: list[MigrationApplied] = []
    total_time = 0
    failed_exception: Exception | None = None

    try:
        session._conn.execute("SAVEPOINT dry_run_execute")
        try:
            for migration_file in plan.pending_files:
                migration_class = _migration_class(session, plan, migration_file)
                migration = migration_class(connection=session._conn)
                _apply_strict_mode(migration, plan.strict)
                _apply_batch(migration, batch)

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
                    plan.skipped_versions.append(migration.version)
                    plan.checksum_warnings = [
                        *plan.checksum_warnings,
                        f"dry_run_execute: skipped {migration.version}_{migration.name} — "
                        "non-transactional migrations cannot run inside a SAVEPOINT",
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
                            duration_ms=elapsed,
                        )
                    )
                    emit(
                        on_event,
                        "applied",
                        version=migration.version,
                        name=migration.name,
                        elapsed_ms=elapsed,
                    )
                except Exception as exc:  # Reason: a migration's up() is user code and may raise anything; recorded and reported
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
    except Exception as exc:  # Reason: user migration code under the dry-run savepoint may raise anything; recorded and reported
        if failed_exception is None:
            failed_exception = exc

    if failed_exception is not None:
        return MigrateUpResult(
            success=False,
            migrations_applied=migrations_tested,
            total_duration_ms=total_time,
            checksums_verified=plan.checksums_verified,
            dry_run=True,
            dry_run_execute=True,
            errors=[str(failed_exception)],
            failure=failed_exception,
            skipped=plan.skipped_versions,
        )

    return MigrateUpResult(
        success=True,
        migrations_applied=migrations_tested,
        total_duration_ms=total_time,
        checksums_verified=plan.checksums_verified,
        dry_run=True,
        dry_run_execute=True,
        skipped=plan.skipped_versions,
        warnings=[
            "dry_run_execute: all SQL executed successfully, changes rolled back",
            *plan.checksum_warnings,
        ],
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
    allow_destructive: bool = False,
    strict_mode: bool | None = None,
    auto_baseline: Path | None = None,
    install_view_helpers: bool | None = None,
    on_event: UpObserver | None = None,
    batch: Any | None = None,
) -> MigrateUpResult:
    """See :meth:`MigratorSession.up`."""
    # Bound at call time through the module, so a test that patches
    # confiture.core.migrator.<name> still holds.
    # Reason: import cycle — session → apply_loop → migrator → session
    import confiture.core.migrator as _m

    # Import through confiture.core.migrator so tests can patch
    # confiture.core.migrator.load_migration_class and confiture.core.migrator.MigrationLock.

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

    # Everything from here runs under the migration lock: the plan
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
        return _up_under_lock(
            session,
            allow_destructive=allow_destructive,
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
            batch=batch,
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
    # Bound at call time through the module, so a test that patches
    # confiture.core.migrator.<name> still holds.
    # Reason: import cycle — session → apply_loop → migrator → session
    import confiture.core.migrator as _m

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
        migration = session.migration_loader(migration_file)(connection=session._conn)
        start = _time.time()
        session._migrator.apply(migration, migration_file=migration_file, applied_by=applied_by)
        return MigrationApplied(
            version=migration.version,
            name=migration.name,
            duration_ms=int((_time.time() - start) * 1000),
        )


def _apply_batch(migration: Any, batch: Any | None) -> None:
    """The operator's ``BatchConfig`` (``--batched``) reaches the migration."""
    if batch is not None:
        migration.batch_config = batch
