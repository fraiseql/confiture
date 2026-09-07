"""``run_against``: replay pending migrations on a parallel database inside SAVEPOINTs.

Split out of ``session.py``. Every function takes the
``MigratorSession`` as its first argument; the session's methods delegate here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from psycopg import sql as pgsql

if TYPE_CHECKING:
    from confiture.core._migrator.session import MigratorSession
    from confiture.models.results import (
        PreflightAgainstResult,
    )
import time as _time

from confiture.exceptions import ConfigurationError


def run_against(
    session: MigratorSession,
    pending_files: list[Path],
    against_url: str,
    *,
    allow_non_transactional: bool = False,
) -> PreflightAgainstResult:
    """See :meth:`MigratorSession.run_against`."""

    from confiture.models.results import PreflightAgainstMigration, PreflightAgainstResult

    if session._conn is None:
        raise ConfigurationError(
            "MigratorSession must be used as a context manager",
            resolution_hint="Use: with MigratorSession(...) as s: s.run_against(...)",
        )

    results: list[PreflightAgainstMigration] = []
    db_consumed = False
    outer_sp = "preflight_run"
    outer_sp_active = True

    # Outer SAVEPOINT: ROLLBACK TO here at the end undoes all migration DDL.
    # No initialize() call — tracking table never needed (we skip apply()).
    session._conn.execute(pgsql.SQL("SAVEPOINT {}").format(pgsql.Identifier(outer_sp)))
    try:
        for migration_file in pending_files:
            migration_class = session.migration_loader(migration_file)
            migration = migration_class(connection=session._conn)

            # Non-transactional migration: cannot run inside a SAVEPOINT.
            # Use getattr with default True so migrations without the attribute
            # are treated as transactional (safe — they run inside SAVEPOINT).
            if not getattr(migration, "transactional", True):
                if not allow_non_transactional:
                    results.append(
                        PreflightAgainstMigration(
                            version=migration.version,
                            name=migration.name,
                            success=False,
                            skipped=True,
                            skipped_reason=("non-transactional: cannot run inside SAVEPOINT"),
                        )
                    )
                    continue

                # allow_non_transactional=True: commit() ends the outer SAVEPOINT
                # and permanently applies ALL DDL executed so far — including any
                # transactional migrations that ran before this one.
                # The preflight DB is now consumed regardless of what follows.
                if outer_sp_active:
                    session._conn.commit()
                    outer_sp_active = False
                db_consumed = True

                session._conn.autocommit = True
                try:
                    start = _time.time()
                    migration.up()
                    elapsed = int((_time.time() - start) * 1000)
                    results.append(
                        PreflightAgainstMigration(
                            version=migration.version,
                            name=migration.name,
                            success=True,
                            execution_time_ms=elapsed,
                        )
                    )
                except Exception as exc:  # Reason: replaying user migration code: any failure is the replay verdict for that version
                    results.append(
                        PreflightAgainstMigration(
                            version=migration.version,
                            name=migration.name,
                            success=False,
                            error=str(exc),
                        )
                    )
                finally:
                    session._conn.autocommit = False
                continue

            # Transactional migration: per-migration SAVEPOINT.
            per_sp = f"sp_{migration.version}"
            session._conn.execute(pgsql.SQL("SAVEPOINT {}").format(pgsql.Identifier(per_sp)))
            try:
                start = _time.time()
                migration.up()  # Direct call — no commit, no tracking
                elapsed = int((_time.time() - start) * 1000)
                session._conn.execute(
                    pgsql.SQL("RELEASE SAVEPOINT {}").format(pgsql.Identifier(per_sp))
                )
                results.append(
                    PreflightAgainstMigration(
                        version=migration.version,
                        name=migration.name,
                        success=True,
                        execution_time_ms=elapsed,
                    )
                )
            except Exception as exc:  # Reason: replaying user migration code under a savepoint: any failure is the verdict for that version
                # ROLLBACK TO resets to before per_sp without destroying outer_sp.
                session._conn.execute(
                    pgsql.SQL("ROLLBACK TO SAVEPOINT {}").format(pgsql.Identifier(per_sp))
                )
                session._conn.execute(
                    pgsql.SQL("RELEASE SAVEPOINT {}").format(pgsql.Identifier(per_sp))
                )
                results.append(
                    PreflightAgainstMigration(
                        version=migration.version,
                        name=migration.name,
                        success=False,
                        error=str(exc),
                    )
                )
    finally:
        # Roll back all migration DDL — only meaningful when outer_sp is still
        # active (i.e. no non-transactional migration triggered a commit).
        if outer_sp_active:
            session._conn.execute(
                pgsql.SQL("ROLLBACK TO SAVEPOINT {}").format(pgsql.Identifier(outer_sp))
            )
            session._conn.execute(
                pgsql.SQL("RELEASE SAVEPOINT {}").format(pgsql.Identifier(outer_sp))
            )

    return PreflightAgainstResult(
        migrations=results,
        against_url=against_url,
        db_consumed=db_consumed,
    )
