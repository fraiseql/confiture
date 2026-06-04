"""Rollback concern for :class:`~confiture.core._migrator.engine.Migrator`.

Peeled out of ``engine.py``. These are free functions that
take the ``Migrator`` instance as their first argument; the class keeps thin
delegating methods so its public surface and patch targets are unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from psycopg import sql as pgsql

from confiture.exceptions import MigrationError

if TYPE_CHECKING:
    from confiture.core._migrator.engine import Migrator
    from confiture.models.migration import Migration

logger = logging.getLogger(__name__)


def rollback(
    migrator: Migrator,
    migration: Migration,
    skip_preconditions: bool = False,
) -> None:
    """Rollback a migration and remove it from the tracking table.

    Validates the migration was applied, runs down-preconditions (unless
    skipped), then dispatches to the transactional or autocommit path.

    Raises:
        MigrationError: If the migration was not applied or the rollback fails.
        PreconditionValidationError: If precondition validation fails.
    """
    if not migrator._is_applied(migration.version):
        raise MigrationError(
            f"Migration {migration.version} ({migration.name}) "
            "has not been applied, cannot rollback",
            migration.version,
            migration.name,
            error_code="MIGR_100",
            resolution_hint="Run 'confiture migrate status' to see which migrations are applied",
        )

    if not skip_preconditions:
        migrator._validate_preconditions(
            migration, direction="down", preconditions=migration.down_preconditions
        )

    if migration.transactional:
        _rollback_transactional(migrator, migration)
    else:
        _rollback_non_transactional(migrator, migration)


def _rollback_transactional(migrator: Migrator, migration: Migration) -> None:
    """Rollback a migration within a transaction."""
    try:
        logger.debug(f"Executing rollback (down) for migration {migration.version}")
        migration.down()

        migrator._execute_sql(
            pgsql.SQL("DELETE FROM {} WHERE version = %s").format(migrator._table_ident),
            (migration.version,),
        )

        migrator.connection.commit()
        logger.info(
            f"Successfully rolled back migration {migration.version} ({migration.name})"
        )

    except Exception as e:
        migrator.connection.rollback()
        raise MigrationError(
            f"Failed to rollback migration {migration.version} ({migration.name}): {e}",
            migration.version,
            migration.name,
            resolution_hint="Check the down migration SQL and ensure the database objects being reversed still exist",
        ) from e


def _rollback_non_transactional(migrator: Migrator, migration: Migration) -> None:
    """Rollback a migration in autocommit mode (no transaction).

    WARNING: If this fails, manual cleanup may be required.
    """
    logger.warning(
        f"Rolling back migration {migration.version} in non-transactional mode. "
        "Manual cleanup may be required on failure."
    )

    migrator.connection.commit()

    original_autocommit = migrator.connection.autocommit
    migrator.connection.autocommit = True

    try:
        logger.debug(
            f"Executing rollback (down) for migration {migration.version} (autocommit)"
        )
        migration.down()

        migrator._execute_sql(
            pgsql.SQL("DELETE FROM {} WHERE version = %s").format(migrator._table_ident),
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
            "Manual cleanup may be required.",
            migration.version,
            migration.name,
            resolution_hint="Inspect the database for partial rollback changes and manually complete the reversal",
        ) from e

    finally:
        migrator.connection.autocommit = original_autocommit
