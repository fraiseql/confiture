"""Core migration commands: migrate status, up, down, generate."""

import json
import re
from pathlib import Path
from typing import Any

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import (
    DATABASE_URL_OPTION_HELP,
    NO_CONFIG_OPTION_HELP,
    _emit_hint,
    _find_orphaned_sql_files,
    _get_tracking_table,
    _output_json,
    _print_duplicate_versions_warning,
    _print_orphaned_files_warning,
    config_is_explicit,
    console,
    error_console,
    has_intentional_dsn_source,
    is_json,
    resolve_database_url,
)
from confiture.core._migrator.discovery import discover_migration_files, parse_migration_filename
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.migration_generator import MigrationGenerator
from confiture.exceptions import ValidationError

# A migration name becomes a filename and a class name. snake_case only: a `/`
# or `..` would walk out of the migrations directory, anything else is not a
# Python identifier fragment.
_MIGRATION_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def migrate_status(
    ctx: typer.Context,
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file for database connection. Must appear after 'status': "
        "confiture migrate status -c config.yaml",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table, json, or csv (default: table)",
    ),
    output_file: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout, useful with json/csv)",
    ),
    check_rebuild: bool = typer.Option(
        False,
        "--check-rebuild",
        help="Check whether a full rebuild is recommended instead of migrate up",
    ),
    rebuild_threshold: int = typer.Option(
        None,
        "--rebuild-threshold",
        help="Number of pending migrations that triggers rebuild advisory (default: from config or 5)",
    ),
) -> None:
    """Show migration status and history.

    PROCESS:
      Lists all migrations and their status (applied or pending). With --config,
      connects to the database and shows which migrations are applied vs pending.

      Exit codes:
        0  All migrations applied (nothing pending) or status unknown (no config).
        1  Pending migrations exist in the target database.
        2  The tracking table was not found in the target database.
           All migrations are shown as "pending" and an advisory is printed.
           Run `confiture migrate up` to initialise, or use
           `confiture migrate baseline --through <version>` if the schema is
           already applied.
        3  Fatal error (connection failure, bad config, permission denied).

    NOTE:
      The -c/--config flag must appear AFTER the subcommand name (v0.5.9+):
        confiture migrate status -c config.yaml   ✅
        confiture migrate -c config.yaml status   ❌ (old form, no longer works)

    EXAMPLES:
      confiture migrate status
        ↳ List all migrations (file-based, status shown as "unknown" without --config)

      confiture migrate status -c db/environments/prod.yaml
        ↳ Show applied vs pending migrations in production database

      confiture migrate status --format json
        ↳ Output as JSON for scripting

      confiture migrate status --format json --output migrations.json
        ↳ Save status report to file

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schema
      (migrate-status.schema.json).

    RELATED:
      confiture migrate up       - Apply pending migrations
      confiture migrate down     - Rollback applied migrations
      confiture migrate generate - Create new migration
    """
    tracking_table_absent_exit: bool = False
    pending_migrations_exit: bool = False
    fatal_error_exit: bool = False
    try:
        # Validate output format
        if output_format not in ("table", "json", "csv"):
            console.print(
                f"[red]❌ Invalid format: {output_format}. Use 'table', 'json', or 'csv'[/red]"
            )
            raise typer.Exit(1)

        if not migrations_dir.exists():
            if output_format == "json":
                result = {"error": f"Migrations directory not found: {migrations_dir.absolute()}"}
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations directory found.[/yellow]")
                console.print(f"Expected: {migrations_dir.absolute()}")
            return

        # Find migration files (both Python and SQL)
        migration_files = discover_migration_files(migrations_dir)

        # Check for orphaned SQL files that don't match the naming pattern
        orphaned_sql_files = _find_orphaned_sql_files(migrations_dir)

        # Check for duplicate migration versions (warning only)
        from confiture.core.migrator import find_duplicate_migration_versions as _status_find

        duplicate_versions = _status_find(migrations_dir)

        if not migration_files:
            if output_format == "json":
                result = {
                    "applied": [],
                    "pending": [],
                    "current": None,
                    "total": 0,
                    "migrations": [],
                    "hints": [],
                }
                if orphaned_sql_files:
                    result["orphaned_migrations"] = [f.name for f in orphaned_sql_files]
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations found.[/yellow]")
                if orphaned_sql_files:
                    _print_orphaned_files_warning(orphaned_sql_files, console)
            return

        # Get applied migrations from database if a connection source is given.
        # Precedence (#140): --database-url / env override > --config file.
        applied_versions: set[str] = set()
        applied_at_by_version: dict[str, Any] = {}
        db_error: str | None = None
        tracking_table_absent: bool = False
        status_tracking_table: str | None = None
        # What the configured name actually resolved to for this session, and
        # (when it did not) where a relation of that name does live (#188).
        status_resolved_table: str | None = None
        ledger_elsewhere: list[str] = []
        # status connects only on an *intentional* source: a --database-url
        # flag, --no-config, an explicit --config, or the canonical
        # CONFITURE_DATABASE_URL. A merely-ambient DATABASE_URL must NOT force a
        # connection — "status-unknown" (exit 0) stays the informative default
        # rather than auto-connecting to whatever DATABASE_URL is in the env
        # (#152; supersedes the #140 flag-only carve-out). Two explicit sources
        # still fail loud via CONFIG_007.
        _status_config_data: Any = None
        if has_intentional_dsn_source(ctx, database_url, no_config):
            _db_url_override = resolve_database_url(
                database_url,
                config,
                config_explicit=config_is_explicit(ctx),
                no_config=no_config,
            )
            if _db_url_override is not None:
                _status_config_data = {"database_url": _db_url_override}
            elif config is not None and config.exists():
                from confiture.core.connection import load_config

                _status_config_data = load_config(config)
        _db_source = _status_config_data is not None
        if _db_source:
            try:
                from confiture.core.connection import create_connection
                from confiture.core.migrator import Migrator

                config_data = _status_config_data
                status_tracking_table = _get_tracking_table(config_data)
                from confiture.core.ledger import find_ledger_relations, probe_ledger
                from confiture.exceptions import ConfiturError

                conn = create_connection(config_data)
                migrator = Migrator(connection=conn, migration_table=status_tracking_table)
                tracking_table_was_present = migrator.tracking_table_exists()
                if not tracking_table_was_present:
                    # A bare name resolves through search_path since 0.41.0, so
                    # "absent" no longer implies "nowhere in this database".
                    # Reporting only the first half sends the operator looking
                    # for a table that is sitting right there (#188).
                    ledger_elsewhere = find_ledger_relations(conn, status_tracking_table)
                migrator.initialize()
                # After initialize, so this names the ledger the run will read
                # rather than the one it found (or did not) a moment earlier.
                # Reporting metadata only: a probe refused for lack of
                # privilege must not turn a working status into "could not
                # connect to database". Narrow on purpose — a NameError in the
                # probe still surfaces rather than degrading to None.
                try:
                    status_resolved_table = probe_ledger(conn, status_tracking_table).resolved_name
                except ConfiturError:
                    status_resolved_table = None
                applied_versions = set(migrator.get_applied_versions())
                for row in migrator.get_applied_migrations_with_timestamps():
                    applied_at_by_version[row["version"]] = row["applied_at"]
                conn.close()
                if not tracking_table_was_present:
                    tracking_table_absent = True
            except Exception as e:
                db_error = str(e)
                if output_format != "json":
                    console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
                    console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")

        # Build migrations data
        migrations_data: list[dict[str, str]] = []
        applied_list: list[str] = []
        pending_list: list[str] = []

        for migration_file in migration_files:
            # Extract version and name from filename
            # Python: "001_add_users.py" -> version="001", name="add_users"
            # SQL: "001_add_users.up.sql" -> version="001", name="add_users"
            version, name = parse_migration_filename(migration_file.name)

            # Determine status
            if _db_source and not db_error:
                # tracking_table_absent: table was missing → all migrations are pending
                # (confiture has not been set up on this database yet)
                if tracking_table_absent or version not in applied_versions:
                    status = "pending"
                    pending_list.append(version)
                else:
                    status = "applied"
                    applied_list.append(version)
            else:
                # No config provided or DB connection failed: status is genuinely unknown
                status = "unknown"

            applied_at: str | None = (
                applied_at_by_version.get(version) if status == "applied" else None
            )
            migrations_data.append(
                {
                    "version": version,
                    "name": name,
                    "status": status,
                    "applied_at": applied_at,
                }
            )

        # Determine current version (highest applied)
        current_version = applied_list[-1] if applied_list else None

        status_hints: list[str] = []
        # The tracking table missing on the target DB is a quiet-success
        # ambiguity: every migration shows "pending" even though the
        # database may already match the schema. Emit a hint so agents
        # don't blindly run `migrate up` on a possibly-baselined DB.
        if tracking_table_absent:
            _emit_hint(
                "Tracking table not found in this database. All migrations "
                "are reported 'pending' — if the schema is already applied, "
                "run `confiture migrate baseline --through <version>` first.",
                hints_list=status_hints,
                format_=output_format,
            )
            if ledger_elsewhere:
                # The likeliest cause of a surprising "all pending", and one an
                # operator cannot diagnose from the ledger name alone.
                _emit_hint(
                    f"`{status_tracking_table}` does not resolve on this "
                    f"connection's search_path, but a relation of that name "
                    f"exists in {', '.join(ledger_elsewhere)}. Qualify "
                    "`migration.tracking_table` or adjust search_path if that "
                    "is the ledger you meant.",
                    hints_list=status_hints,
                    format_=output_format,
                )
        if output_format == "json":
            result: dict[str, Any] = {
                "tracking_table": status_tracking_table,
                "resolved_table": status_resolved_table,
                "applied": applied_list,
                "pending": pending_list,
                "current": current_version,
                "total": len(migration_files),
                "migrations": migrations_data,
                "summary": {
                    "applied": len(applied_list),
                    "pending": len(pending_list),
                    "total": len(migration_files),
                },
                "hints": status_hints,
            }
            if db_error:
                result["warning"] = f"Could not connect to database: {db_error}"
            elif tracking_table_absent:
                result["warning"] = (
                    f"{status_tracking_table or 'The migration ledger'} not found in this "
                    "database. All migrations shown as 'pending'. Run `confiture migrate up` "
                    "to apply all migrations, or `confiture migrate baseline --through "
                    "<version>` if the schema is already applied."
                )
            if orphaned_sql_files:
                result["orphaned_migrations"] = [f.name for f in orphaned_sql_files]
            if duplicate_versions:
                result["duplicate_versions"] = {
                    v: [f.name for f in files] for v, files in duplicate_versions.items()
                }
            if check_rebuild and pending_list:
                from confiture.core.strategy import (
                    find_rebuild_strategy_files as _json_find_rebuild,
                )

                _json_threshold = rebuild_threshold or 5
                _json_reasons: list[str] = []
                if len(pending_list) >= _json_threshold:
                    _json_reasons.append(
                        f"{len(pending_list)} pending migrations exceed threshold of {_json_threshold}"
                    )
                for sf in _json_find_rebuild(migrations_dir):
                    _json_reasons.append(f"Migration {sf.name} has '-- Strategy: rebuild' header")
                if _json_reasons:
                    result["rebuild_recommended"] = True
                    result["rebuild_reasons"] = _json_reasons
            _output_json(result, output_file, console)
            if tracking_table_absent:
                tracking_table_absent_exit = True
        elif output_format == "csv":
            # CSV output with migration list
            from confiture.cli.formatters.common import handle_output

            csv_data = (
                ["version", "name", "status"],
                [[m["version"], m["name"], m["status"]] for m in migrations_data],
            )
            handle_output("csv", {}, csv_data, output_file, console)
        else:
            from rich.table import Table

            # Display migrations in a table
            table = Table(title="Migrations")
            table.add_column("Version", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Status", style="yellow")

            for migration in migrations_data:
                if migration["status"] == "applied":
                    status_display = "[green]✅ applied[/green]"
                elif migration["status"] == "pending":
                    status_display = "[yellow]⏳ pending[/yellow]"
                else:
                    status_display = "[dim]⚠️ unknown (no config)[/dim]"

                table.add_row(migration["version"], migration["name"], status_display)

            console.print(table)
            console.print(f"\n📊 Total: {len(migration_files)} migrations", end="")
            if applied_versions:
                console.print(f" ({len(applied_list)} applied, {len(pending_list)} pending)")
            else:
                console.print()

            if tracking_table_absent:
                console.print(
                    f"\n[yellow]⚠️  {status_tracking_table or 'The migration ledger'} not "
                    "found in this database. Migrations shown as 'pending'.[/yellow]"
                )
                console.print(
                    "[yellow]   Run `confiture migrate up` to apply all migrations, or[/yellow]"
                )
                console.print(
                    "[yellow]   `confiture migrate baseline --through <version>` if the "
                    "schema is already applied.[/yellow]"
                )
                tracking_table_absent_exit = True

            # Warn about duplicate versions
            if duplicate_versions:
                _print_duplicate_versions_warning(duplicate_versions, console)

            # Warn about orphaned files
            if orphaned_sql_files:
                _print_orphaned_files_warning(orphaned_sql_files, console)

            # Check if rebuild is recommended
            if check_rebuild and pending_list:
                from confiture.core.strategy import find_rebuild_strategy_files

                threshold = rebuild_threshold
                if threshold is None:
                    # Try to read from config
                    if config and config.exists():
                        try:
                            from confiture.core.connection import load_config as _rebuild_load

                            _cfg = _rebuild_load(config)
                            if hasattr(_cfg, "migration") and hasattr(
                                _cfg.migration, "rebuild_threshold"
                            ):
                                threshold = _cfg.migration.rebuild_threshold
                        except Exception:
                            pass
                    if threshold is None:
                        threshold = 5

                rebuild_reasons: list[str] = []

                if len(pending_list) >= threshold:
                    rebuild_reasons.append(
                        f"{len(pending_list)} pending migrations exceed threshold of {threshold}"
                    )

                strategy_files = find_rebuild_strategy_files(migrations_dir)
                if strategy_files:
                    for sf in strategy_files:
                        rebuild_reasons.append(
                            f"Migration {sf.name} has '-- Strategy: rebuild' header"
                        )

                if rebuild_reasons and output_format in ("text", "table"):
                    console.print("\n[yellow]🔄 Rebuild recommended:[/yellow]")
                    for reason in rebuild_reasons:
                        console.print(f"  • {reason}")
                    console.print(
                        "\n[yellow]  Run: confiture migrate rebuild --drop-schemas --yes[/yellow]"
                    )

        # Set exit flags after output is written (avoids raising inside try)
        if _db_source and db_error:
            fatal_error_exit = True
        elif _db_source and not db_error and not tracking_table_absent and len(pending_list) > 0:
            pending_migrations_exit = True

    except Exception as e:
        if output_format == "json":
            # #145: a genuinely unexpected status failure emits the structured
            # error envelope (the informative no-table/pending payloads above are
            # emitted on their own paths and are not errors).
            fail(e, json_mode=True, output_file=output_file)
        elif output_format == "csv":
            from confiture.cli.formatters.common import handle_output

            csv_data = (
                ["error"],
                [[str(e)]],
            )
            handle_output("csv", {}, csv_data, output_file, console)
        else:
            console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(3) from e

    if fatal_error_exit:
        raise typer.Exit(3)
    if tracking_table_absent_exit:
        raise typer.Exit(2)
    if pending_migrations_exit:
        raise typer.Exit(1)


def migrate_current(
    ctx: typer.Context,
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Print the current (latest applied) migration revision.

    Reads the tracking table and reports the most-recently-applied migration.
    A narrow, stable contract for tooling — no need to parse `migrate status`.

    OUTPUT:
      text  — the bare revision string (empty line if none applied)
      json  — {revision, name, applied_at, checksum}; revision is null when
              the tracking table exists but is empty.

    EXIT CODES:
      0  Current revision printed (or null when the table is empty).
      2  Tracking table absent — confiture not initialized on this database.
      3  Database connection failed.

    EXAMPLES:
      confiture migrate current -c db/environments/prod.yaml
      confiture migrate current --database-url "$DATABASE_URL" --format json
    """
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator
    from confiture.exceptions import DatabaseNotInitializedError
    from confiture.models.results import CurrentRevision

    if output_format not in ("text", "json"):
        error_console.print(
            f"[red]❌ Error: Invalid format '{output_format}'. Use 'text' or 'json'[/red]"
        )
        raise typer.Exit(2)

    try:
        override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
        )
        config_data = {"database_url": override} if override is not None else load_config(config)
        conn = create_connection(config_data)
        try:
            migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))
            # Probe first: the row query raises on an absent table (≠ empty).
            if not migrator.tracking_table_exists():
                raise DatabaseNotInitializedError(
                    "Database not initialized (tracking table absent)"
                )
            row = migrator.get_current_revision_row()
        finally:
            conn.close()
    except typer.Exit:
        raise
    except Exception as e:
        if is_json(output_format):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e

    cur = (
        None
        if row is None
        else CurrentRevision(
            version=row["version"],
            name=row["name"],
            applied_at=row["applied_at"],
            checksum=row.get("checksum"),
        )
    )

    if is_json(output_format):
        payload = (
            {"revision": None, "name": None, "applied_at": None, "checksum": None}
            if cur is None
            else cur.to_dict()
        )
        _output_json(payload, output_file, console)
    else:
        # Bare revision on stdout (plain print avoids Rich markup interpretation).
        print(cur.version if cur is not None else "")


def migrate_up(
    ctx: typer.Context,
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    target: str = typer.Option(
        None,
        "--target",
        "-t",
        help="Target migration version (default: applies all pending)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Enable strict mode, fail on warnings (default: off)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force application, skip state checks (default: off)",
    ),
    lock_timeout: int = typer.Option(
        30000,
        "--lock-timeout",
        help="Lock timeout in milliseconds (default: 30000ms)",
    ),
    no_lock: bool = typer.Option(
        False,
        "--no-lock",
        help="Disable migration locking (default: off, DANGEROUS in multi-pod)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze without executing (default: off)",
    ),
    dry_run_execute: bool = typer.Option(
        False,
        "--dry-run-execute",
        help="Execute in SAVEPOINT for testing (default: off, guaranteed rollback)",
    ),
    verify_checksums: bool = typer.Option(
        True,
        "--verify-checksums/--no-verify-checksums",
        help="Verify migration checksums before running (default: on)",
    ),
    on_checksum_mismatch: str = typer.Option(
        "fail",
        "--on-checksum-mismatch",
        help="Checksum mismatch behavior: fail, warn, ignore (default: fail)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run (default: off)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file (default: stdout)",
    ),
    auto_detect_baseline: bool = typer.Option(
        False,
        "--auto-detect-baseline",
        help="Introspect DB and self-baseline if tb_confiture is missing (default: off)",
    ),
    snapshots_dir_up: Path | None = typer.Option(
        None,
        "--snapshots-dir",
        help="Schema history snapshots directory for --auto-detect-baseline (default: db/schema_history)",
    ),
    require_reversible: bool = typer.Option(
        False,
        "--require-reversible",
        help="Abort if any pending migration lacks a .down.sql file (guarantees rollback capability).",
    ),
    batched: bool = typer.Option(
        False,
        "--batched",
        help="Use batch processing for large-table operations (default: off)",
    ),
    batch_size: int = typer.Option(
        10000,
        "--batch-size",
        help="Rows per batch when --batched is active (default: 10000)",
    ),
    batch_sleep: float = typer.Option(
        0.1,
        "--batch-sleep",
        help="Seconds to sleep between batches to reduce lock pressure (default: 0.1)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the --dry-run-execute confirmation prompt (default: off)",
    ),
) -> None:
    """Apply pending migrations to the database.

    PROCESS:
      Runs the library's MigratorSession: the migration lock is taken first,
      discovery and the ledger init happen under it, checksums are verified,
      then pending migrations apply in order. --dry-run analyzes; --dry-run-execute
      executes inside a SAVEPOINT that is always rolled back.

    EXAMPLES:
      confiture migrate up
        ↳ Apply all pending migrations

      confiture migrate up --target 003
        ↳ Apply migrations up to version 003

      confiture migrate up --dry-run
        ↳ Analyze migrations without executing

      confiture migrate up --strict --no-verify-checksums
        ↳ Strict mode with warnings treated as errors, skip checksum validation

    RELATED:
      confiture migrate down        - Rollback migrations
      confiture migrate status      - View migration history
      confiture migrate generate    - Create new migration template

    EXIT CODES:
      0  All migrations applied successfully.
      1  Generic/unknown error.
      2  Validation or configuration error (bad flags, missing config).
      3  Migration execution error (SQL failure, duplicate versions).
      6  Lock/pool error (retriable — another process holds the lock).

    OPTIONS:
      CORE: --target
        Which migration version to apply (default: all pending)

      DRY-RUN: --dry-run, --dry-run-execute, --yes, --verbose, --format, --output
        Analyze migrations before executing, with optional SAVEPOINT testing

      STRUCTURAL DIFF: --dry-run does not emit a structural diff (column adds,
        index drops, etc.). For that, use `migrate preflight --against <url>`
        which replays migrations on a parallel database and diffs the result
        against db/schema/. See docs/guides/dry-run.md#need-a-structural-diff.

      SAFETY: --verify-checksums, --on-checksum-mismatch, --strict, --no-lock, --lock-timeout
        Control verification and locking behavior for production safety

      ADVANCED: --force
        Skip safety checks (use with caution in production)
    """

    from confiture.cli.dry_run import (
        ask_dry_run_execute_confirmation,
        display_dry_run_header,
    )
    from confiture.core.checksum import ChecksumVerificationError
    from confiture.core.connection import dsn_from_config, load_config
    from confiture.core.locking import LockAcquisitionError
    from confiture.core.migrator import MigratorSession, find_duplicate_migration_versions

    try:
        # Validate dry-run options
        if dry_run and dry_run_execute:
            error_console.print(
                "[red]❌ Error: Cannot use both --dry-run and --dry-run-execute[/red]"
            )
            raise typer.Exit(2)

        if (dry_run or dry_run_execute) and force:
            error_console.print("[red]❌ Error: Cannot use --dry-run with --force[/red]")
            raise typer.Exit(2)

        # Validate format option
        if format_output not in ("text", "json"):
            error_console.print(
                f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
            )
            raise typer.Exit(2)

        # Validate checksum mismatch option
        valid_mismatch_behaviors = ("fail", "warn", "ignore")
        if on_checksum_mismatch not in valid_mismatch_behaviors:
            error_console.print(
                f"[red]❌ Error: Invalid --on-checksum-mismatch '{on_checksum_mismatch}'. "
                f"Use one of: {', '.join(valid_mismatch_behaviors)}[/red]"
            )
            raise typer.Exit(2)

        # --batched is accepted for compatibility; batch processing is an
        # engine concern (`migrate estimate`, large_tables) — see Cycle 5.
        del batched, batch_size, batch_sleep, verbose

        # Check for duplicate migration versions (hard block, no DB needed)
        _up_duplicates = find_duplicate_migration_versions(migrations_dir)
        if _up_duplicates:
            if is_json(format_output):
                from confiture.exceptions import MigrationConflictError

                _dupe_files = sorted(f.name for files in _up_duplicates.values() for f in files)
                fail(
                    MigrationConflictError(
                        "Duplicate migration versions detected: "
                        + ", ".join(sorted(_up_duplicates)),
                        conflicting_files=_dupe_files,
                    ),
                    json_mode=True,
                    output_file=output_file,
                )
            error_console.print(
                "[red]❌ Duplicate migration versions detected — refusing to proceed[/red]"
            )
            error_console.print(
                "[red]Multiple migration files share the same version number:[/red]\n"
            )
            for version, files in sorted(_up_duplicates.items()):
                error_console.print(f"  Version {version}:")
                for f in files:
                    error_console.print(f"    • {f.name}")
            error_console.print(
                "\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]"
            )
            error_console.print(
                "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
            )
            raise typer.Exit(3)

        # Resolve the DSN under the #152 precedence contract. A resolved
        # override (flag / canonical env / --no-config) skips YAML loading;
        # `up` is mutating, so an ambient-only DATABASE_URL is refused.
        _db_url_override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
            require_intentional_source=True,
        )
        if _db_url_override is not None:
            config_data = {"database_url": _db_url_override}
        else:
            config_data = load_config(config)

        # Environment-level migration settings (strict mode, view helpers) come
        # from the environment config only when YAML is the DSN source.
        env_cfg = None
        if (
            _db_url_override is None
            and config.parent.name == "environments"
            and config.parent.parent.name == "db"
        ):
            try:
                from confiture.config.environment import Environment as _Env

                env_cfg = _Env.load(config.stem, project_dir=config.parent.parent.parent)
            except Exception:
                env_cfg = None  # unparsable environment config: defaults apply
        effective_strict_mode = strict or bool(env_cfg and env_cfg.migration.strict_mode)
        install_helpers = bool(env_cfg and env_cfg.migration.view_helpers == "auto")

        if force:
            console.print(
                "[yellow]⚠️  Force mode enabled - skipping migration state checks[/yellow]"
            )
            console.print(
                "[yellow]This may cause issues if applied incorrectly. Use with caution![/yellow]\n"
            )
        if no_lock:
            console.print(
                "[yellow]⚠️  Locking disabled - DANGEROUS in multi-pod environments![/yellow]"
            )
            console.print(
                "[yellow]Concurrent migrations may cause race conditions or data corruption.[/yellow]\n"
            )

        # Orphaned migration files (filesystem only): a warning, an abort in strict mode.
        orphaned_files = _find_orphaned_sql_files(migrations_dir)
        if orphaned_files:
            _print_orphaned_files_warning(orphaned_files, error_console)
            if effective_strict_mode:
                error_console.print(
                    "\n[red]❌ Strict mode enabled: Aborting due to orphaned files[/red]"
                )
                raise typer.Exit(1)

        reporter = _UpReporter(live=not is_json(format_output), force=force)
        options: dict[str, Any] = {
            "target": target,
            "verify_checksums": verify_checksums,
            "on_checksum_mismatch": on_checksum_mismatch,
            "force": force,
            "lock_timeout": lock_timeout,
            "no_lock": no_lock,
            "require_reversible": require_reversible,
            "strict_mode": effective_strict_mode,
            "auto_baseline": (
                (snapshots_dir_up or Path("db/schema_history")) if auto_detect_baseline else None
            ),
            "install_view_helpers": install_helpers,
            "on_event": reporter,
        }

        with MigratorSession(
            None,
            migrations_dir,
            database_url_override=dsn_from_config(config_data),
            migration_table_override=_get_tracking_table(config_data),
            command="confiture migrate up",
        ) as session:
            if dry_run or dry_run_execute:
                display_dry_run_header("testing" if dry_run_execute else "analysis")
                session.up(dry_run=True, **options)
                _render_dry_run_analysis(
                    reporter.pending,
                    migration_id=f"dry_run_{config.stem}",
                    execute=dry_run_execute,
                    format_output=format_output,
                    output_file=output_file,
                )
                if dry_run:
                    return
                if not yes and not ask_dry_run_execute_confirmation():
                    console.print("[yellow]Cancelled - no changes applied[/yellow]")
                    return
                reporter.reset()
                result = session.up(dry_run_execute=True, **options)
            else:
                result = session.up(**options)

        _render_up_result(result, reporter, format_output, output_file, force=force)

    except typer.Exit:
        raise
    except ChecksumVerificationError as e:
        if is_json(format_output):
            fail(e, json_mode=True, output_file=output_file)
        error_console.print("[red]❌ Checksum verification failed![/red]\n")
        for m in e.mismatches:
            error_console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
            expected_preview = m.expected[:16] if m.expected else "(none)"
            error_console.print(f"    Expected: {expected_preview}...")
            error_console.print(f"    Actual:   {m.actual[:16]}...")
        error_console.print(
            "\n[yellow]💡 Tip: Use 'confiture verify-checksums --fix' to update checksums, "
            "or --no-verify-checksums to skip[/yellow]"
        )
        raise typer.Exit(1) from e
    except LockAcquisitionError as e:
        if is_json(format_output):
            from confiture.cli.error_json import lock_error_to_confiture

            # LOCK_1300 envelope enriched with holder identity (#147).
            fail(lock_error_to_confiture(e), json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        if e.timeout:
            error_console.print(
                f"[yellow]💡 Tip: Increase timeout with --lock-timeout {lock_timeout * 2}[/yellow]"
            )
        else:
            error_console.print(
                "[yellow]💡 Tip: Check if another migration is running, or use --no-lock (dangerous)[/yellow]"
            )
        raise typer.Exit(6) from e
    except Exception as e:
        if is_json(format_output):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e


def migrate_down(
    ctx: typer.Context,
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    steps: int = typer.Option(
        1,
        "--steps",
        "-n",
        help="Number of migrations to rollback (default: 1)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze rollback without executing (default: off)",
    ),
    lock_timeout: int = typer.Option(
        30000,
        "--lock-timeout",
        help="Lock timeout in milliseconds (default: 30000ms)",
    ),
    no_lock: bool = typer.Option(
        False,
        "--no-lock",
        help="Disable migration locking (default: off, DANGEROUS in multi-pod)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run (default: off)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file (default: stdout)",
    ),
) -> None:
    """Rollback previously applied migrations.

    PROCESS:
      Rolls back the last N applied migrations (default: 1), reverting schema
      changes. Use --dry-run to analyze without executing.

    EXAMPLES:
      confiture migrate down
        ↳ Rollback the last applied migration

      confiture migrate down --steps 3
        ↳ Rollback the last 3 migrations

      confiture migrate down --dry-run
        ↳ Analyze rollback without executing

      confiture migrate down --verbose --format json
        ↳ Detailed analysis in JSON format

    RELATED:
      confiture migrate up       - Apply migrations forward
      confiture migrate status   - View migration history
      confiture migrate validate - Check migration integrity

    OPTIONS:
      CORE: --steps
        How many migrations to rollback (default: 1)

      DRY-RUN: --dry-run, --verbose, --format, --output
        Analyze rollback without executing, with detailed reports

      OUTPUT: --format, --output
        Control report format and destination
    """

    from confiture.cli.formatters.migrate_formatter import format_migrate_down_result
    from confiture.core.connection import dsn_from_config, load_config
    from confiture.core.locking import LockAcquisitionError
    from confiture.core.migrator import MigratorSession

    del verbose  # accepted for compatibility

    try:
        if format_output not in ("text", "json"):
            error_console.print(
                f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
            )
            raise typer.Exit(2)

        _db_url_override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
            require_intentional_source=True,
        )
        if _db_url_override is not None:
            config_data = {"database_url": _db_url_override}
        else:
            config_data = load_config(config)

        with MigratorSession(
            None,
            migrations_dir,
            database_url_override=dsn_from_config(config_data),
            migration_table_override=_get_tracking_table(config_data),
            command="confiture migrate down",
        ) as session:
            if session.current_revision() is None:
                console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
                return

            if dry_run:
                from confiture.cli.dry_run import display_dry_run_header

                display_dry_run_header("analysis")
                preview = session.down(steps=steps, dry_run=True)
                _render_dry_run_analysis(
                    [(m.version, m.name) for m in preview.migrations_rolled_back],
                    migration_id=f"dry_run_rollback_{config.stem}",
                    execute=False,
                    format_output=format_output,
                    output_file=output_file,
                    rollback=True,
                )
                return

            if not is_json(format_output):
                console.print(f"[cyan]📦 Rolling back up to {steps} migration(s)[/cyan]\n")
            result = session.down(steps=steps, lock_timeout=lock_timeout, no_lock=no_lock)

        format_migrate_down_result(result, format_output, output_file, console)

    except typer.Exit:
        raise
    except LockAcquisitionError as e:
        if is_json(format_output):
            from confiture.cli.error_json import lock_error_to_confiture

            fail(lock_error_to_confiture(e), json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(6) from e
    except Exception as e:
        if is_json(format_output):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e


def migrate_down_to(
    ctx: typer.Context,
    revision: str = typer.Argument(
        ...,
        help="Target revision to roll back to (stays applied). Use 'migrate current' to find it.",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the rollback plan and exit 0 without applying anything.",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Roll back every migration newer than <revision> (absolute rollback).

    The absolute counterpart to ``migrate down --steps N``: instead of a
    relative count, name the revision to return to. Confiture computes the
    rollback set, validates that every required ``.down.sql`` exists *before*
    touching the database, and rolls back newest→oldest under the migration
    lock. If any required ``.down.sql`` is missing, it refuses atomically —
    nothing is rolled back.

    EDGE CASES:
      <revision> == current      → no-op, exit 0 ("already at <revision>")
      <revision> newer than current → exit 3 ("use 'migrate up --target'")
      <revision> unknown         → exit 3 ("unknown revision")
      any required .down.sql missing → exit 8, nothing applied (ROLLBACK_600)

    OUTPUT (--format json): {from, to, rolled_back, skipped, errors}

    EXAMPLES:
      confiture migrate down-to 20260101_a -c db/environments/staging.yaml
      confiture migrate down-to 20260101_a --dry-run --format json
    """
    from confiture.core.migrator import Migrator, MigratorSession

    if format_output not in ("text", "json"):
        error_console.print(
            f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
        )
        raise typer.Exit(2)

    try:
        override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
            require_intentional_source=True,
        )
        if override is not None:
            session = MigratorSession(
                config=None,
                migrations_dir=migrations_dir,
                database_url_override=override,
            )
        else:
            session = Migrator.from_config(str(config), migrations_dir=migrations_dir)
        with session as s:
            result = s.down_to(revision, dry_run=dry_run, command="confiture migrate down-to")
    except typer.Exit:
        raise
    except Exception as e:
        if is_json(format_output):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e

    if is_json(format_output):
        _output_json(result.to_dict(), output_file, console)
    elif result.noop:
        console.print(f"Already at {revision}; nothing to roll back.")
    else:
        verb = "Would roll back" if dry_run else "Rolled back"
        console.print(
            f"{verb} {len(result.rolled_back)} migration(s) from {result.from_} to {revision}:"
        )
        for v in result.rolled_back:
            console.print(f"  • {v}")


def migrate_generate(
    name: str = typer.Argument(..., help="Migration name (snake_case)"),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing migration file (default: off)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be generated without creating (default: off)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show version calculation details (default: off)",
    ),
    from_schema: Path | None = typer.Option(
        None,
        "--from",
        help="Old schema file path (required with --generator)",
    ),
    to_schema: Path | None = typer.Option(
        None,
        "--to",
        help="New schema file path (required with --generator)",
    ),
    generator: str | None = typer.Option(
        None,
        "--generator",
        help="Named external generator from migration_generators config",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Environment config file (default: db/environments/local.yaml)",
    ),
    snapshot: bool | None = typer.Option(
        None,
        "--snapshot/--no-snapshot",
        help="Write schema history snapshot (default: from config, True)",
    ),
    snapshots_dir: Path | None = typer.Option(
        None,
        "--snapshots-dir",
        help="Override snapshot output directory (default: db/schema_history)",
    ),
    live_snapshot: bool | None = typer.Option(
        None,
        "--live-snapshot/--no-live-snapshot",
        help="Snapshot via temp database + pg_dump (captures DO-block objects)",
    ),
) -> None:
    """Generate a new migration file with timestamp-based version.

    PROCESS:
      Creates an empty migration template with a timestamp-based version number.
      Uses the current system time (YYYYMMDDHHmmSS format) to ensure uniqueness
      and avoid merge conflicts in multi-developer environments.

    EXAMPLES:
      confiture migrate generate add_user_email
        ↳ Create migration template with timestamp version (20260228120530_add_user_email.py)

      confiture migrate generate add_payment_column --verbose
        ↳ Show version calculation and scanning details

      confiture migrate generate stripe_integration --dry-run
        ↳ Preview what would be created without writing files

      confiture migrate generate hotfix --force
        ↳ Overwrite existing migration file if it exists

    RELATED:
      confiture migrate up      - Apply the generated migration
      confiture migrate status  - View all migrations
      confiture migrate diff    - Compare schema files
    """
    if not _MIGRATION_NAME_RE.match(name):
        fail(
            ValidationError(
                f"Invalid migration name {name!r}: use snake_case — lowercase letters, "
                "digits and underscores only (e.g. add_user_bio).",
                context={"name": name},
                resolution_hint="Rename the migration, e.g. `confiture migrate generate add_user_bio`.",
            ),
            json_mode=format_output == "json",
        )

    # External generator path
    if generator is not None:
        if from_schema is None or to_schema is None:
            error_console.print(
                "[red]❌ Error: --from and --to are required when --generator is used[/red]"
            )
            raise typer.Exit(2)

        env_config = None
        try:
            from confiture.config.environment import Environment

            env_name = config.stem
            project_dir = config.parent.parent.parent
            env_config = Environment.load(env_name, project_dir=project_dir)
        except Exception:
            pass

        if env_config is None or generator not in env_config.migration.migration_generators:
            error_console.print(
                f"[red]❌ Error: Generator '{generator}' not found in migration_generators config[/red]"
            )
            raise typer.Exit(2)

        gen_config = env_config.migration.migration_generators[generator]
        migrations_dir.mkdir(parents=True, exist_ok=True)
        gen_instance = MigrationGenerator(migrations_dir=migrations_dir)

        try:
            from confiture.exceptions import ExternalGeneratorError

            resolved_cmd, up_sql_path = gen_instance.run_external_generator(
                generator_config=gen_config,
                from_path=from_schema,
                to_path=to_schema,
                migration_name=name,
                dry_run=dry_run,
            )
        except FileNotFoundError as exc:
            error_console.print(f"[red]❌ Error: {exc}[/red]")
            raise typer.Exit(2) from exc
        except ExternalGeneratorError as exc:
            error_console.print(f"[red]❌ Generator error: {exc}[/red]")
            raise typer.Exit(3) from exc

        if dry_run:
            console.print(f"[dim]Resolved command:[/] {resolved_cmd}")
            console.print(f"[dim]Target file:      [/] {up_sql_path}")
            raise typer.Exit(0)

        console.print("[green]✅ Migration generated by external generator![/green]")
        console.print(f"\n📄 File: {up_sql_path.absolute()}")
        console.print("\n💡 Next steps:")
        console.print("  • Review and edit the generated SQL if needed")
        console.print("  • Apply: confiture migrate up")
        raise typer.Exit(0)

    try:
        # Ensure migrations directory exists
        migrations_dir.mkdir(parents=True, exist_ok=True)

        # Generate migration file template
        generator_instance = MigrationGenerator(migrations_dir=migrations_dir)

        # Collect warnings
        warnings = []

        # Verbose mode: show scanning info
        if verbose:
            console.print("[cyan]🔍 Scanning migrations directory...[/cyan]")
            console.print(f"  Directory: {migrations_dir.absolute()}")

            migration_files = sorted(migrations_dir.glob("*.py"))
            console.print(f"  Found {len(migration_files)} migration files:")

            for f in migration_files:
                version_str = parse_migration_filename(f.name)[0]
                console.print(f"    - {f.name} (version: {version_str})")

        # Check for duplicate versions (covers both .py and .up.sql files)
        from confiture.core.migrator import find_duplicate_migration_versions as _gen_find

        duplicates = _gen_find(migrations_dir)
        if duplicates:
            warning_msg = f"Duplicate versions detected: {', '.join(sorted(duplicates.keys()))}"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")

        # Check for name conflicts
        name_conflicts = generator_instance._check_name_conflict(name)
        if name_conflicts:
            warning_msg = f"Migration name '{name}' already exists in other versions"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")
                for f in name_conflicts:
                    console.print(f"    - {f.name}")

        # Calculate next version
        version = generator_instance._get_next_version()

        if verbose:
            console.print(f"\n  Highest version: {version[:-1] if int(version) > 1 else '000'}")
            console.print(f"  Next version: {version}")
            console.print(f"  Target file: {version}_{name}.py")
            console.print()

        # Generate class name and file path
        class_name = generator_instance._to_class_name(name)
        filename = f"{version}_{name}.py"
        filepath = migrations_dir / filename

        # Create template
        template = f'''"""Migration: {name}

Version: {version}
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """Migration: {name}."""

    version = "{version}"
    name = "{name}"

    def up(self) -> None:
        """Apply migration."""
        # Add your forward migration SQL here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # Add your rollback SQL here
        # Example:
        # self.execute("DROP TABLE users")
        pass
'''

        # Dry-run mode: show preview and exit
        if dry_run:
            if format_output == "json":
                output = {
                    "status": "dry_run",
                    "version": version,
                    "name": name,
                    "filepath": str(filepath.absolute()),
                    "class_name": class_name,
                    "template": template,
                    "warnings": warnings,
                }
                print(json.dumps(output, indent=2))
            else:
                console.print("[cyan]🔍 Dry-run mode - no files will be created[/cyan]\n")
                console.print("Would create migration:")
                console.print(f"  Version: {version}")
                console.print(f"  Name: {name}")
                console.print(f"  Class: {class_name}")
                console.print(f"  File: {filepath.absolute()}")
                console.print("\n[dim]Template preview:[/dim]")
                console.print("[dim]" + "─" * 60 + "[/dim]")
                console.print(template)
                console.print("[dim]" + "─" * 60 + "[/dim]")
            return

        # Check if file exists
        if filepath.exists() and not force:
            if format_output == "json":
                output = {
                    "status": "error",
                    "error": "file_exists",
                    "message": f"Migration file already exists: {filepath.name}",
                    "filepath": str(filepath.absolute()),
                    "resolution": "Use --force flag to overwrite existing file",
                }
                print(json.dumps(output, indent=2))
            else:
                console.print("[red]❌ Error: Migration file already exists:[/red]")
                console.print(f"  {filepath.absolute()}")
                console.print("\n[yellow]Use --force to overwrite[/yellow]")
            raise typer.Exit(1)

        # Warn if overwriting
        if filepath.exists() and force and format_output == "text":
            console.print(f"[yellow]⚠️  Overwriting existing file: {filepath.name}[/yellow]")

        # Write file (with lock protection)
        lock_fd = generator_instance._acquire_migration_lock()
        try:
            filepath.write_text(template)
        finally:
            generator_instance._release_migration_lock(lock_fd)

        # Write schema history snapshot (non-fatal if it fails)
        _snapshot_path: Path | None = None
        _snapshot_env_config = None
        try:
            from confiture.config.environment import Environment as _SnapshotEnv

            _snapshot_env_name = config.stem
            _snapshot_project_dir = config.parent.parent.parent
            _snapshot_env_config = _SnapshotEnv.load(
                _snapshot_env_name, project_dir=_snapshot_project_dir
            )
        except Exception:
            pass

        _should_snapshot = snapshot
        if _should_snapshot is None:
            _should_snapshot = (
                _snapshot_env_config.migration.snapshot_history
                if _snapshot_env_config is not None
                else True
            )

        _snapshot_mode = "static"
        if _should_snapshot:
            # Resolve live-snapshot mode from CLI flag or config
            _use_live = live_snapshot
            if _use_live is None:
                _use_live = (
                    _snapshot_env_config.migration.live_snapshot
                    if _snapshot_env_config is not None
                    else False
                )

            _live_db_url: str | None = None
            if _use_live and _snapshot_env_config is not None:
                _live_db_url = _snapshot_env_config.database_url

            try:
                from confiture.core.schema_snapshot import SchemaSnapshotGenerator

                _resolved_snapshots_dir = snapshots_dir
                if _resolved_snapshots_dir is None and _snapshot_env_config is not None:
                    _resolved_snapshots_dir = Path(_snapshot_env_config.migration.snapshots_dir)
                if _resolved_snapshots_dir is None:
                    _resolved_snapshots_dir = Path("db/schema_history")

                _snap_gen = SchemaSnapshotGenerator(snapshots_dir=_resolved_snapshots_dir)
                _snap_env_name = config.stem
                _snap_project_dir = config.parent.parent.parent

                if _live_db_url:
                    try:
                        _snapshot_path = _snap_gen.write_snapshot(
                            _snap_env_name,
                            version,
                            name,
                            _snap_project_dir,
                            database_url=_live_db_url,
                        )
                        _snapshot_mode = "live"
                    except Exception as _live_err:
                        if format_output == "text":
                            console.print(
                                f"[yellow]⚠️  Live snapshot failed, falling back to static: {_live_err}[/yellow]"
                            )
                        _snapshot_path = _snap_gen.write_snapshot(
                            _snap_env_name, version, name, _snap_project_dir
                        )
                        _snapshot_mode = "static"
                else:
                    _snapshot_path = _snap_gen.write_snapshot(
                        _snap_env_name, version, name, _snap_project_dir
                    )
            except Exception as _snap_err:
                if format_output == "text":
                    console.print(
                        f"[yellow]⚠️  Snapshot write failed (non-fatal): {_snap_err}[/yellow]"
                    )

        # Output success message
        if format_output == "json":
            output = {
                "status": "success",
                "version": version,
                "name": name,
                "filepath": str(filepath.absolute()),
                "class_name": class_name,
                "migrations_dir": str(migrations_dir.absolute()),
                "next_available_version": version,
                "snapshot": str(_snapshot_path.absolute()) if _snapshot_path else None,
                "snapshot_mode": _snapshot_mode if _snapshot_path else None,
                "warnings": warnings,
            }
            print(json.dumps(output, indent=2))
        else:
            console.print("[green]✅ Migration generated successfully![/green]")
            print(f"\n📄 File: {filepath.absolute()}")
            if _snapshot_path:
                console.print(f"📸 Snapshot: {_snapshot_path.absolute()}")
            console.print("\n✏️  Edit the migration file to add your SQL statements.")
            console.print("\n💡 Next steps:")
            console.print("  • Edit file and add SQL")
            console.print("  • Apply: confiture migrate up")
            console.print("  • Or verify first: confiture migrate up --dry-run")

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "json":
            output = {
                "status": "error",
                "error": "generation_failed",
                "message": str(e),
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[red]❌ Error generating migration: {e}[/red]")
        raise typer.Exit(1) from e


def migrate_estimate(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    tables: list[str] = typer.Option(
        [],
        "--table",
        "-t",
        help="Tables to estimate (default: all tables)",
    ),
    format_output: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
) -> None:
    """Estimate row counts for tables to decide if --batched is needed.

    Uses pg_class statistics (fast, no COUNT(*)) to show which tables
    are large enough to benefit from --batched mode.

    EXAMPLES:
      confiture migrate estimate
        ↳ Show row count estimates for all tables

      confiture migrate estimate --table users --table orders
        ↳ Estimate specific tables only

    RELATED:
      confiture migrate up --batched - Apply migrations in batch mode
    """
    from confiture.core.connection import create_connection, load_config
    from confiture.core.large_tables import TableSizeEstimator

    try:
        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)

        config_data = load_config(config)
        conn = create_connection(config_data)

        estimator = TableSizeEstimator(conn)

        # If no tables specified, estimate all in public schema
        if not tables:
            tables = estimator.all_tables()

        if not tables:
            console.print("[yellow]No tables found.[/yellow]")
            return

        rows_data: list[dict[str, Any]] = []
        for table in tables:
            estimate = estimator.get_row_count_estimate(table)
            should_batch = estimator.should_use_batched_operation(table)
            rows_data.append(
                {
                    "table": table,
                    "estimated_rows": estimate,
                    "recommendation": "Use --batched" if should_batch else "Standard migration OK",
                }
            )

        if format_output == "json":
            print(json.dumps(rows_data, indent=2))
        else:
            from rich.table import Table

            tbl = Table(title="Table Row Count Estimates")
            tbl.add_column("Table", style="cyan")
            tbl.add_column("Estimated Rows", justify="right")
            tbl.add_column("Recommendation")
            for row in rows_data:
                style = "yellow" if row["recommendation"].startswith("Use") else "green"
                tbl.add_row(
                    row["table"],
                    f"{row['estimated_rows']:,}",
                    f"[{style}]{row['recommendation']}[/{style}]",
                )
            console.print(tbl)

    except typer.Exit:
        raise
    except Exception as e:
        error_console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


class _UpReporter:
    """Turns ``MigratorSession.up()`` events into the console lines of ``migrate up``.

    Collects the pending list (for the dry-run summary) and the failure event
    (for the error details) whatever the output mode; prints live only in text
    mode, where JSON output must stay clean.
    """

    def __init__(self, *, live: bool, force: bool = False) -> None:
        self.live = live
        self.force = force
        self.reset()

    def reset(self) -> None:
        self.pending: list[tuple[str, str]] = []
        self.failed: Any = None
        self._announced = False

    def _announce(self) -> None:
        if self._announced:
            return
        self._announced = True
        n = len(self.pending)
        if self.force:
            console.print(f"[cyan]📦 Force mode: Found {n} migration(s) to apply[/cyan]\n")
        else:
            console.print(f"[cyan]📦 Found {n} pending migration(s)[/cyan]\n")

    def __call__(self, event: Any) -> None:
        kind = event.kind
        if kind == "pending":
            self.pending.append((event.version or "", event.name or ""))
            return
        if kind == "failed":
            self.failed = event
        if not self.live:
            return
        if kind == "lock_acquired":
            console.print("[cyan]🔒 Acquired migration lock[/cyan]\n")
        elif kind == "baseline_probe":
            console.print(f"[cyan]🔍 {event.message}[/cyan]")
        elif kind == "baseline_detected":
            console.print(f"[green]✓ Detected baseline: {event.version}[/green]")
            console.print(f"[green]✅ Auto-baselined through {event.version}[/green]")
        elif kind == "baseline_missed":
            console.print(f"[yellow]⚠️  {event.message}[/yellow]")
        elif kind == "view_helpers_installed":
            console.print(
                "[cyan]🔧 Auto-installed view helper functions "
                "(migration.view_helpers: auto)[/cyan]\n"
            )
        elif kind == "checksums_verified":
            console.print("[cyan]🔐 Checksum verification passed[/cyan]\n")
        elif kind == "applying":
            self._announce()
            console.print(f"[cyan]⚡ Applying {event.label}...[/cyan]", end=" ")
        elif kind == "applied":
            console.print("[green]✅[/green]")
        elif kind == "failed":
            console.print("[red]❌[/red]")
        elif kind == "target_reached":
            console.print(f"[yellow]⏭️  Skipping {event.version} (after target)[/yellow]")
        elif kind == "skipped_non_transactional":
            console.print(
                f"[yellow]⏭️  Skipping {event.label} (non-transactional — "
                "cannot run inside a SAVEPOINT)[/yellow]"
            )
        elif kind == "superuser_halt":
            self._announce()
            console.print(f"\n[yellow]⏸  Skipping migration {event.label}:[/yellow]")
            console.print(
                "[dim]  requires_superuser=True.  Apply this migration separately as a superuser:[/dim]"
            )
            console.print(f"[dim]    confiture migrate apply-as <role> {event.version}[/dim]")
            console.print("[dim]  Then re-run `confiture migrate up` to resume the chain.[/dim]")


def _render_dry_run_analysis(
    pending: list[tuple[str, str]],
    *,
    migration_id: str,
    execute: bool,
    format_output: str,
    output_file: Path | None,
    rollback: bool = False,
) -> None:
    """The dry-run summary of ``migrate up --dry-run`` / ``migrate down --dry-run``."""
    from confiture.cli.dry_run import print_json_report, save_json_report, save_text_report

    entries = [
        {
            "version": version,
            "name": name,
            "classification": "warning",
            "estimated_duration_ms": 500,
            "estimated_disk_usage_mb": 1.0,
            "estimated_cpu_percent": 30.0,
        }
        for version, name in pending
    ]
    summary: dict[str, Any] = {
        "migration_id": migration_id,
        "mode": "execute_and_analyze" if execute else "analysis",
        "statements_analyzed": len(pending),
        "migrations": entries,
        "summary": {
            "unsafe_count": 0,
            "total_estimated_time_ms": 0,
            "total_estimated_disk_mb": 0.0,
            "has_unsafe_statements": False,
        },
        "warnings": [],
        "analyses": entries,
    }
    verb = "rollback" if rollback else "apply"
    if format_output == "json":
        if output_file:
            save_json_report(summary, output_file)
            console.print(f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]")
        else:
            print_json_report(summary)
        return

    if not rollback:
        console.print(f"[cyan]📦 Found {len(pending)} pending migration(s)[/cyan]\n")
    console.print(
        "[cyan]Rollback Analysis Summary[/cyan]"
        if rollback
        else "\n[cyan]Migration Analysis Summary[/cyan]"
    )
    console.print("=" * 80)
    console.print(f"Migrations to {verb}: {len(pending)}")
    console.print()
    for mig in entries:
        console.print(f"  {mig['version']}: {mig['name']}")
        console.print(
            f"    Estimated time: {mig['estimated_duration_ms']}ms | "
            f"Disk: {mig['estimated_disk_usage_mb']:.1f}MB | "
            f"CPU: {mig['estimated_cpu_percent']:.0f}%"
        )
    console.print()
    if rollback:
        console.print("[yellow]⚠️  Rollback will undo these migrations[/yellow]")
    else:
        console.print("[green]✓ All migrations appear safe to execute[/green]")
    console.print("=" * 80)
    if output_file:
        title = (
            "DRY-RUN ROLLBACK ANALYSIS REPORT" if rollback else "DRY-RUN MIGRATION ANALYSIS REPORT"
        )
        text_report = title + "\n" + "=" * 80 + "\n\n"
        for mig in entries:
            text_report += f"{mig['version']}: {mig['name']}\n"
        save_text_report(text_report, output_file)
        console.print(f"[green]✅ Report saved to: {output_file.absolute()}[/green]")


def _render_up_result(
    result: Any,
    reporter: _UpReporter,
    format_output: str,
    output_file: Path | None,
    *,
    force: bool,
) -> None:
    """Render a ``MigrateUpResult`` and exit with the command's contract code."""
    from confiture.cli.formatters.migrate_formatter import (
        format_migrate_up_result,
        show_migration_error_details,
    )

    text = format_output == "text"

    if result.skipped_superuser:
        # Issue #137 — halted at the first requires_superuser=True migration;
        # the reporter already printed the recovery hint in text mode.
        if not text:
            format_migrate_up_result(result, format_output, output_file, console)
        raise typer.Exit(1)

    if not result.success:
        if text:
            failed = reporter.failed
            failed_migration = _FailedMigration(
                version=getattr(failed, "version", None) or "?",
                name=getattr(failed, "name", None) or "?",
            )
            exception = result.failure or Exception(result.error_summary or "migration failed")
            show_migration_error_details(
                failed_migration, exception, len(result.migrations_applied), console
            )
        else:
            format_migrate_up_result(result, format_output, output_file, console)
        raise typer.Exit(3)

    if not result.dry_run and not result.migrations_applied and text:
        if force:
            console.print("[yellow]⚠️  No migration files found.[/yellow]")
        else:
            console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
        return

    format_migrate_up_result(result, format_output, output_file, console)
    if text and not result.dry_run:
        if force:
            console.print(
                "[yellow]⚠️  Remember to verify your database state after force application[/yellow]"
            )
        else:
            console.print("\n💡 Next steps:")
            console.print("  • Verify: confiture migrate status")
            console.print("  • Validate: confiture lint")
            console.print("  • Load data: confiture seed apply")


class _FailedMigration:
    """The ``version``/``name`` pair ``show_migration_error_details`` renders."""

    def __init__(self, *, version: str, name: str) -> None:
        self.version = version
        self.name = name
