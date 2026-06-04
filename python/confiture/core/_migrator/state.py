"""Tracking-table state concern for ``Migrator``: init, queries, hook trigger.

Peeled out of ``engine.py``. Free functions taking the
``Migrator`` instance as their first argument; the class keeps thin delegating
methods, so its public surface and patch targets are unchanged. Pure refactor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from psycopg import sql as pgsql

from confiture.core.hooks.context import ExecutionContext
from confiture.exceptions import MigrationError, SQLError

if TYPE_CHECKING:
    from confiture.core._migrator.engine import Migrator
    from confiture.models.migration import Migration

logger = logging.getLogger(__name__)


def initialize(migrator: Migrator) -> None:
    """Create the tracking table (Trinity identity pattern). Idempotent.

    Raises:
        MigrationError: If table creation fails.
    """
    try:
        # Check if table exists (schema-aware)
        with migrator.connection.cursor() as cursor:
            if migrator._table_schema is not None:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    )
                    """,
                    (migrator._table_schema, migrator._table_base),
                )
            else:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = %s
                    )
                    """,
                    (migrator._table_base,),
                )
            result = cursor.fetchone()
            table_exists = result[0] if result else False

        if not table_exists:
            # Create new table with Trinity pattern
            migrator._execute_sql(
                pgsql.SQL("""
                CREATE TABLE {} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    version VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    execution_time_ms INTEGER,
                    checksum VARCHAR(64),
                    applied_by TEXT
                )
                """).format(migrator._table_ident)
            )

            # Create indexes — index names use the validated _table_base
            migrator._execute_sql(
                pgsql.SQL("CREATE INDEX {} ON {}(pk_confiture)").format(
                    pgsql.Identifier(f"idx_{migrator._table_base}_pk_confiture"),
                    migrator._table_ident,
                )
            )
            migrator._execute_sql(
                pgsql.SQL("CREATE INDEX {} ON {}(slug)").format(
                    pgsql.Identifier(f"idx_{migrator._table_base}_slug"),
                    migrator._table_ident,
                )
            )
            migrator._execute_sql(
                pgsql.SQL("CREATE INDEX {} ON {}(version)").format(
                    pgsql.Identifier(f"idx_{migrator._table_base}_version"),
                    migrator._table_ident,
                )
            )
            migrator._execute_sql(
                pgsql.SQL("CREATE INDEX {} ON {}(applied_at DESC)").format(
                    pgsql.Identifier(f"idx_{migrator._table_base}_applied_at"),
                    migrator._table_ident,
                )
            )
        else:
            # Issue #137 — `applied_by` column was added in 0.17.0.
            # Existing installs auto-migrate via IF NOT EXISTS; pre-0.17.0
            # rows keep `applied_by IS NULL` ("applied before 0.17.0;
            # role unknown") as a documented invariant.
            migrator._execute_sql(
                pgsql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS applied_by TEXT").format(
                    migrator._table_ident
                )
            )

        migrator.connection.commit()
    except Exception as e:
        migrator.connection.rollback()
        if isinstance(e, SQLError):
            raise MigrationError(
                f"Failed to initialize migrations table: {e}",
                resolution_hint="Check database permissions to CREATE TABLE in the target schema",
            ) from e
        else:
            raise MigrationError(
                f"Failed to initialize migrations table: {e}",
                resolution_hint="Check database permissions to CREATE TABLE in the target schema",
            ) from e


def is_applied(migrator: Migrator, version: str) -> bool:
    """Check if migration *version* has been applied."""
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("SELECT COUNT(*) FROM {} WHERE version = %s").format(migrator._table_ident),
            (version,),
        )
        result = cursor.fetchone()
        if result is None:
            return False
        count: int = result[0]
        return count > 0


def get_applied_versions(migrator: Migrator) -> list[str]:
    """Return all applied migration versions, ordered by applied_at ascending."""
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("SELECT version FROM {} ORDER BY applied_at ASC").format(
                migrator._table_ident
            )
        )
        return [row[0] for row in cursor.fetchall()]


def get_applied_migrations_with_timestamps(migrator: Migrator) -> list[dict[str, Any]]:
    """Return applied migrations with version, name, and applied_at timestamp."""
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL(
                "SELECT version, name, applied_at FROM {} ORDER BY applied_at ASC"
            ).format(migrator._table_ident)
        )
        return [
            {
                "version": row[0],
                "name": row[1],
                "applied_at": row[2].isoformat() if row[2] else None,
            }
            for row in cursor.fetchall()
        ]


def get_current_revision_row(migrator: Migrator) -> dict[str, Any] | None:
    """Return the most-recently-applied migration row, or None if empty.

    Raises psycopg's UndefinedTable when the tracking table is absent; callers
    must probe ``tracking_table_exists()`` first to distinguish absent from empty.
    """
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL(
                "SELECT version, name, applied_at, checksum FROM {} "
                "ORDER BY applied_at DESC LIMIT 1"
            ).format(migrator._table_ident)
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "version": row[0],
        "name": row[1],
        "applied_at": row[2].isoformat() if row[2] else None,
        "checksum": row[3],
    }


def tracking_table_exists(migrator: Migrator) -> bool:
    """Return True if the tracking table exists in the database."""
    with migrator.connection.cursor() as cursor:
        if migrator._table_schema is not None:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (migrator._table_schema, migrator._table_base),
            )
        else:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = %s
                )
                """,
                (migrator._table_base,),
            )
        result = cursor.fetchone()
        return bool(result[0]) if result else False


def trigger_hook(
    migrator: Migrator,
    phase: Any,
    migration: Migration,
    execution_time_ms: int = 0,
    success: bool = False,
    error: str | None = None,
) -> None:
    """Trigger hooks for a migration lifecycle event."""
    # Build execution context with migration metadata
    context = ExecutionContext(
        elapsed_time_ms=execution_time_ms,
        metadata={
            "migration_name": migration.name,
            "migration_version": migration.version,
            "direction": "up",  # Currently only supporting up migrations
            "success": success,
            "error": error,
            "executed_by": "migrator",  # Could be enhanced to track actual user
        },
    )

    from confiture.core.hooks.context import HookContext

    hook_context = HookContext(phase=phase, data=context)

    # Run async hook triggering in synchronous context
    import asyncio

    try:
        # Check if we're already in an event loop (e.g., during testing)
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, skip hook triggering to avoid conflicts
            logger.debug(f"Skipping hook triggering for {phase} due to running event loop")
            return
        except RuntimeError:
            # No running loop, we can create one
            pass

        # Create new event loop for synchronous context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(migrator.hook_registry.trigger(phase, hook_context))
        if result.failed_count > 0:
            logger.warning(
                f"Hook execution failed for phase {phase}: {result.failed_count} hook(s) failed"
            )
    except Exception as e:
        logger.error(f"Hook triggering failed for phase {phase}: {e}")
        # Don't let hook failures break migrations
    finally:
        try:
            if "loop" in locals():
                loop.close()
        except Exception:
            pass
