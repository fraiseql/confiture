"""Baseline / reinit / rebuild concern for ``Migrator``.

Peeled out of ``engine.py``. Free functions taking the
``Migrator`` instance as their first argument; the class keeps thin delegating
methods so its public surface and patch targets are unchanged. Pure refactor.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import sql as pgsql

from confiture.core._migrator._constants import _VALID_TABLE_RE
from confiture.exceptions import MigrationError

if TYPE_CHECKING:
    from confiture.config.environment import Environment
    from confiture.core._migrator.engine import Migrator
    from confiture.models.results import MigrateRebuildResult, MigrateReinitResult

logger = logging.getLogger(__name__)


def baseline_from_db(
    migrator: Migrator,
    source_dsn: str,
    migrations_dir: Path,
    *,
    through: str | None = None,
    dry_run: bool = False,
    source_table: str | None = None,
) -> dict[str, Any]:
    """Copy tracking-table rows from another database.

    See :meth:`Migrator.baseline_from_db` for the full contract.
    """
    from confiture.core._migrator.baseline_copy import _select_rows_to_copy

    local_files = migrator.find_migration_files(migrations_dir)
    local_versions = {migrator._version_from_filename(f.name) for f in local_files}

    source_table_name = source_table or migrator.migration_table
    source_rows = _read_source_tracking_table(source_dsn, source_table_name)

    selection = _select_rows_to_copy(
        source_rows,
        local_versions=local_versions,
        through=through,
    )

    applied_versions = set(migrator.get_applied_versions())
    copied: list[dict[str, Any]] = []
    skipped: list[str] = []

    for index, row in enumerate(selection.rows):
        if row["version"] in applied_versions:
            skipped.append(row["version"])
            continue
        if not dry_run:
            _insert_baseline_row(migrator, row, index=index)
        copied.append(row)

    if not dry_run:
        migrator.connection.commit()

    return {
        "copied": copied,
        "skipped": skipped,
        "source_only": selection.source_only,
        "warnings": selection.warnings,
        "dry_run": dry_run,
    }


def _read_source_tracking_table(
    source_dsn: str,
    source_table: str,
) -> list[dict[str, Any]]:
    """Open *source_dsn* and SELECT all rows from *source_table*.

    Returns rows as dicts keyed by column name, ordered by version ascending.
    Closes the source connection before returning.
    """
    if not _VALID_TABLE_RE.match(source_table):
        raise MigrationError(
            f"Invalid source table name: {source_table!r}.",
            resolution_hint="Pass --source-table with a valid identifier.",
        )
    src_parts = source_table.split(".", 1)
    if len(src_parts) == 2:
        src_ident = pgsql.Identifier(src_parts[0], src_parts[1])
    else:
        src_ident = pgsql.Identifier(src_parts[0])

    try:
        with psycopg.connect(source_dsn) as src_conn, src_conn.cursor() as cursor:
            cursor.execute(
                pgsql.SQL(
                    "SELECT version, name, applied_at, execution_time_ms, "
                    "checksum FROM {} ORDER BY version ASC"
                ).format(src_ident)
            )
            rows = cursor.fetchall()
            columns = [desc[0] for desc in (cursor.description or [])]
    except psycopg.Error as exc:
        raise MigrationError(
            f"Could not read source tracking table {source_table!r}: {exc}",
            resolution_hint=(
                "Verify the DSN, that the source DB is reachable, and that "
                "the tracking table exists and is readable."
            ),
        ) from exc

    return [dict(zip(columns, row, strict=False)) for row in rows]


def _insert_baseline_row(migrator: Migrator, row: dict[str, Any], *, index: int = 0) -> None:
    """Insert one source row into the target tracking table.

    See :meth:`Migrator._insert_baseline_row` for the slug/uniqueness contract.
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"{row['name']}_{timestamp}_{index:04d}_baseline_from_db"

    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("""
            INSERT INTO {}
                (id, slug, version, name, applied_at, execution_time_ms, checksum)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s)
            """).format(migrator._table_ident),
            (
                slug,
                row["version"],
                row["name"],
                row.get("applied_at"),
                row.get("execution_time_ms") or 0,
                row.get("checksum"),
            ),
        )


def clear_tracking_table(migrator: Migrator) -> int:
    """Delete all entries from the tracking table (DELETE, not TRUNCATE).

    Returns the number of rows deleted.
    """
    with migrator.connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("DELETE FROM {}").format(migrator._table_ident))
        deleted = cursor.rowcount
    return deleted


def reinit(
    migrator: Migrator,
    through: str | None = None,
    dry_run: bool = False,
    migrations_dir: Path | None = None,
) -> MigrateReinitResult:
    """Reset tracking table and re-mark migrations as applied.

    See :meth:`Migrator.reinit` for the full contract.
    """
    from confiture.models.results import MigrateReinitResult, MigrationApplied

    start_time = time.time()

    # Discover migration files
    all_migrations = migrator.find_migration_files(migrations_dir)

    # Filter to target version if specified
    if through is not None:
        migrations_to_mark: list[Path] = []
        found = False
        for migration_file in all_migrations:
            version = migrator._version_from_filename(migration_file.name)
            migrations_to_mark.append(migration_file)
            if version == through:
                found = True
                break
        if not found:
            raise MigrationError(
                f"Migration version '{through}' not found on disk",
                through,
                error_code="MIGR_100",
                resolution_hint=f"Run 'confiture migrate status' to list available versions, or check that version '{through}' exists in your migrations directory",
            )
    else:
        migrations_to_mark = list(all_migrations)

    try:
        # Clear tracking table
        deleted_count = migrator._clear_tracking_table()

        # Re-mark each migration using direct INSERT (avoid mark_applied's
        # commit which would interfere with dry-run rollback)
        from datetime import datetime

        from confiture.core.checksum import compute_checksum
        from confiture.core.connection import load_migration_class

        marked: list[MigrationApplied] = []
        for migration_file in migrations_to_mark:
            migration_class = load_migration_class(migration_file)
            migration = migration_class(connection=migrator.connection)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = f"{migration.name}_{timestamp}_reinit"
            checksum = compute_checksum(migration_file)

            with migrator.connection.cursor() as cursor:
                cursor.execute(
                    pgsql.SQL("""
                    INSERT INTO {}
                        (id, slug, version, name, execution_time_ms, checksum)
                    VALUES (gen_random_uuid(), %s, %s, %s, %s, %s)
                    """).format(migrator._table_ident),
                    (slug, migration.version, migration.name, 0, checksum),
                )

            name_parts = migration_file.stem.split("_", 1)
            name = name_parts[1] if len(name_parts) > 1 else migration_file.stem
            if name.endswith(".up"):
                name = name[:-3]
            marked.append(
                MigrationApplied(
                    version=migration.version,
                    name=name,
                    execution_time_ms=0,
                )
            )

        if dry_run:
            migrator.connection.rollback()
        else:
            migrator.connection.commit()

        elapsed_ms = int((time.time() - start_time) * 1000)

        return MigrateReinitResult(
            success=True,
            deleted_count=deleted_count,
            migrations_marked=marked,
            total_execution_time_ms=elapsed_ms,
            dry_run=dry_run,
        )

    except Exception:
        migrator.connection.rollback()
        raise


def discover_user_schemas(migrator: Migrator) -> list[str]:
    """Query all user-created schemas, excluding system schemas."""
    with migrator.connection.cursor() as cursor:
        cursor.execute("SELECT schema_name FROM information_schema.schemata")
        rows = cursor.fetchall()

    return [
        row[0]
        for row in rows
        if row[0] not in migrator._SYSTEM_SCHEMAS
        and not row[0].startswith("pg_temp_")
        and not row[0].startswith("pg_toast_temp_")
    ]


def drop_user_schemas(migrator: Migrator, schemas: list[str]) -> list[str]:
    """Drop user schemas with CASCADE and recreate ``public`` (autocommit)."""
    if not schemas:
        return []

    original_autocommit = migrator.connection.autocommit
    # Close any open transaction before switching to autocommit (issue #93)
    migrator.connection.rollback()
    migrator.connection.autocommit = True
    try:
        with migrator.connection.cursor() as cursor:
            for schema in schemas:
                logger.info("Dropping schema %s", schema)
                cursor.execute(pgsql.SQL("DROP SCHEMA {} CASCADE").format(pgsql.Identifier(schema)))
            # Always recreate public
            cursor.execute("CREATE SCHEMA public")
        return list(schemas)
    finally:
        migrator.connection.autocommit = original_autocommit


def apply_ddl_string(migrator: Migrator, ddl: str) -> tuple[int, list[str]]:
    """Execute DDL statements in autocommit mode.

    Strips BEGIN/COMMIT wrappers, splits into statements, and executes each.
    CREATE EXTENSION failures are captured as warnings rather than raised.
    """
    import sqlparse

    from confiture.core.sql_utils import strip_transaction_wrappers

    cleaned = strip_transaction_wrappers(ddl)
    statements = [s.strip() for s in sqlparse.split(cleaned) if s.strip()]

    if not statements:
        return 0, []

    warnings: list[str] = []
    executed = 0

    original_autocommit = migrator.connection.autocommit
    # Close any open transaction before switching to autocommit (issue #93)
    migrator.connection.rollback()
    migrator.connection.autocommit = True
    try:
        with migrator.connection.cursor() as cursor:
            for stmt in statements:
                if not stmt or stmt == ";":
                    continue
                try:
                    cursor.execute(stmt)
                    executed += 1
                except Exception as exc:
                    if "CREATE EXTENSION" in stmt.upper():
                        warnings.append(f"CREATE EXTENSION warning: {exc}")
                    else:
                        raise
    finally:
        migrator.connection.autocommit = original_autocommit

    return executed, warnings


def backup_tracking_table(migrator: Migrator) -> list[dict[str, Any]]:
    """Dump current tracking table contents as list of dicts (empty if absent)."""
    if not migrator.tracking_table_exists():
        return []

    with migrator.connection.cursor() as cursor:
        cursor.execute(pgsql.SQL("SELECT * FROM {}").format(migrator._table_ident))
        columns = [desc[0] for desc in (cursor.description or [])]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def rebuild(
    migrator: Migrator,
    *,
    drop_schemas: bool = False,
    dry_run: bool = False,
    apply_seeds: bool = False,
    backup_tracking: bool = False,
    schema_dir: Path | None = None,
    migrations_dir: Path | None = None,
    seeds_dir: Path | None = None,
    env_config: Environment | None = None,
) -> MigrateRebuildResult:
    """Rebuild database from DDL and bootstrap tracking table.

    See :meth:`Migrator.rebuild` for the full contract.
    """
    from confiture.exceptions import RebuildError
    from confiture.models.results import MigrateRebuildResult

    start_time = time.time()
    warnings: list[str] = []
    schemas_dropped: list[str] = []
    ddl_count = 0
    seeds_applied: int | None = None

    if schema_dir is None:
        schema_dir = Path("db") / "schema"
    if migrations_dir is None:
        migrations_dir = Path("db") / "migrations"
    if seeds_dir is None:
        seeds_dir = Path("db") / "seeds"

    # Step 1: Backup tracking table if requested
    if backup_tracking:
        migrator._backup_tracking_table()  # result used by CLI for JSON dump

    # Step 2: Build DDL via SchemaBuilder
    try:
        from confiture.core.builder import SchemaBuilder

        builder = SchemaBuilder(
            env=env_config.name if env_config and hasattr(env_config, "name") else "rebuild",
        )
        ddl = builder.build(schema_only=True)
    except Exception as exc:
        raise RebuildError(
            f"Schema build failed: {exc}",
            resolution_hint="Check your schema DDL files for syntax errors and ensure the schema directory exists",
        ) from exc

    if dry_run:
        # Count what would be executed
        import sqlparse

        from confiture.core.sql_utils import strip_transaction_wrappers

        cleaned = strip_transaction_wrappers(ddl)
        stmts = [s.strip() for s in sqlparse.split(cleaned) if s.strip()]
        ddl_count = len(stmts)

        # Count migrations that would be marked
        all_migrations = migrator.find_migration_files(migrations_dir)
        from confiture.models.results import MigrationApplied

        marked = []
        for mf in all_migrations:
            version = migrator._version_from_filename(mf.name)
            name_parts = mf.stem.split("_", 1)
            name = name_parts[1] if len(name_parts) > 1 else mf.stem
            if name.endswith(".up"):
                name = name[:-3]
            marked.append(MigrationApplied(version=version, name=name, execution_time_ms=0))

        # Discover schemas that would be dropped
        if drop_schemas:
            schemas_dropped = migrator._discover_user_schemas()

        elapsed_ms = int((time.time() - start_time) * 1000)
        return MigrateRebuildResult(
            success=True,
            schemas_dropped=schemas_dropped,
            ddl_statements_executed=ddl_count,
            migrations_marked=marked,
            total_execution_time_ms=elapsed_ms,
            dry_run=True,
            warnings=warnings,
        )

    # Step 3: Drop schemas if requested
    if drop_schemas:
        user_schemas = migrator._discover_user_schemas()
        schemas_dropped = migrator._drop_user_schemas(user_schemas)

    # Step 4: Apply DDL
    ddl_count, ddl_warnings = migrator._apply_ddl_string(ddl)
    warnings.extend(ddl_warnings)

    # Step 5: Initialize tracking table + re-baseline
    migrator.initialize()
    reinit_result = migrator.reinit(migrations_dir=migrations_dir)
    migrations_marked = reinit_result.migrations_marked

    # Step 6: Optionally apply seeds
    if apply_seeds:
        from confiture.core.seed_applier import SeedApplier

        applier = SeedApplier(
            seeds_dir=seeds_dir,
            connection=migrator.connection,
        )
        seed_result = applier.apply_sequential()
        seeds_applied = seed_result.succeeded

    elapsed_ms = int((time.time() - start_time) * 1000)

    return MigrateRebuildResult(
        success=True,
        schemas_dropped=schemas_dropped,
        ddl_statements_executed=ddl_count,
        migrations_marked=migrations_marked,
        total_execution_time_ms=elapsed_ms,
        dry_run=False,
        warnings=warnings,
        seeds_applied=seeds_applied,
    )


def baseline_through(
    migrator: Migrator,
    through: str,
    migrations_dir: Path,
) -> list[str]:
    """Mark migrations applied through *through* without clearing the table.

    See :meth:`Migrator.baseline_through` for the full contract.
    """
    all_migrations = migrator.find_migration_files(migrations_dir)

    migrations_to_mark: list[Path] = []
    found = False
    for migration_file in all_migrations:
        version = migrator._version_from_filename(migration_file.name)
        migrations_to_mark.append(migration_file)
        if version == through:
            found = True
            break

    if not found:
        raise MigrationError(
            f"Migration version '{through}' not found on disk",
            through,
            resolution_hint=f"Run 'confiture migrate status' to list available versions, or check that version '{through}' exists in your migrations directory",
        )

    already_applied = set(migrator.get_applied_versions())
    newly_marked: list[str] = []
    for migration_file in migrations_to_mark:
        version = migrator._version_from_filename(migration_file.name)
        if version not in already_applied:
            migrator.mark_applied(migration_file, reason="auto-baseline")
            newly_marked.append(version)
    return newly_marked
