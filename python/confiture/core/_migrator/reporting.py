"""Read-only views of a session: ``status()``, ``current_revision()``, ``preflight()``.

Split out of ``session.py``. Every function takes the
``MigratorSession`` as its first argument; the session's methods delegate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core._migrator.discovery import parse_migration_filename

if TYPE_CHECKING:
    from datetime import datetime

    from confiture.core._migrator.session import MigratorSession
    from confiture.models.results import (
        CurrentRevision,
        PreflightResult,
        StatusResult,
    )
from confiture.exceptions import ConfigurationError


def status(session: MigratorSession) -> StatusResult:
    """See :meth:`MigratorSession.status`."""
    from datetime import datetime

    from confiture.models.results import MigrationInfo, StatusResult

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )

    tracking_table = session._migrator.migration_table

    # Discover migration files (Python and SQL)
    if not session._migrations_dir.exists():
        return StatusResult(
            migrations=[],
            tracking_table_exists=False,
            tracking_table=tracking_table,
            summary={"applied": 0, "pending": 0, "total": 0},
        )

    migration_files = session._migrator.find_migration_files(migrations_dir=session._migrations_dir)

    if not migration_files:
        table_exists = session._migrator.tracking_table_exists()
        return StatusResult(
            migrations=[],
            tracking_table_exists=table_exists,
            tracking_table=tracking_table,
            summary={"applied": 0, "pending": 0, "total": 0},
        )

    # Query tracking table
    table_exists = session._migrator.tracking_table_exists()
    applied_versions: set[str] = set()
    applied_at_by_version: dict[str, datetime | None] = {}

    if table_exists:
        applied_versions = set(session._migrator.get_applied_versions())
        for row in session._migrator.get_applied_migrations_with_timestamps():
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
        version, name = parse_migration_filename(mf.name)

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


def current_revision(session: MigratorSession) -> CurrentRevision | None:
    """See :meth:`MigratorSession.current_revision`."""
    from confiture.exceptions import ConfigurationError, DatabaseNotInitializedError
    from confiture.models.results import CurrentRevision

    if session._migrator is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with Migrator.from_config(...) as m: ...",
        )

    # MANDATORY probe: get_current_revision_row() raises psycopg's
    # UndefinedTable on an absent table — it does NOT return None. Translate
    # "absent" → PRECON_1001 (exit 2); reserve None for "exists but empty".
    if not session._migrator.tracking_table_exists():
        raise DatabaseNotInitializedError("Database not initialized (tracking table absent)")

    row = session._migrator.get_current_revision_row()
    if row is None:
        return None
    return CurrentRevision(
        version=row["version"],
        name=row["name"],
        applied_at=row["applied_at"],
        checksum=row.get("checksum"),
    )


def preflight(
    session: MigratorSession,
    *,
    versions: list[str] | None = None,
) -> PreflightResult:
    """See :meth:`MigratorSession.preflight`."""
    from confiture.core.preflight import run_preflight

    # Determine which versions to check
    check_versions = versions
    if check_versions is None and session._migrator is not None:
        # Inside context: check pending migrations only
        status = session.status()
        check_versions = status.pending if status.pending else None

    result = run_preflight(session._migrations_dir, versions=check_versions)

    # Checksum verification (only when DB is connected)
    if session._conn is not None:
        # #182: verify_all() raises psycopg's UndefinedTable on an absent
        # ledger. preflight is an advisory aggregator, not a gate, so it
        # skips and reports rather than raising — consistent with the
        # probes in status() and current_revision().
        if session._migrator is not None and not session._migrator.tracking_table_exists():
            result.checksum_verified = False
            result.checksum_skipped_reason = (
                "no migration ledger in this database — nothing recorded to "
                "verify checksums against"
            )
            return result

        from confiture.core.checksum import (
            ChecksumConfig,
            ChecksumMismatchBehavior,
            MigrationChecksumVerifier,
        )

        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
        verifier = MigrationChecksumVerifier(
            session._conn,
            config,
            migration_table=(
                session._migrator.migration_table
                if session._migrator is not None
                else "tb_confiture"
            ),
        )
        mismatches = verifier.verify_all(session._migrations_dir)
        result.checksum_mismatches = [
            f"{m.version}_{m.name}: expected {(m.expected or '')[:12]}..., got {m.actual[:12]}..."
            for m in mismatches
        ]
        result.checksum_verified = True

    return result
