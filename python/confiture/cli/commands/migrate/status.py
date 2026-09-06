"""`confiture migrate status`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from confiture.cli.commands.migrate._settings import _effective_rebuild_threshold
from confiture.cli.error_json import cli_boundary, fail
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
    resolve_database_url,
)
from confiture.cli.options import format_option
from confiture.core._migrator.discovery import discover_migration_files, parse_migration_filename


@cli_boundary
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
    output_format: str = format_option("table", "json", "csv"),
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

        if not migrations_dir.exists():
            if output_format == "json":
                # The status payload shape, empty, with the situation as its warning —
                # not a hand-built error envelope (exit 0: nothing is wrong with the DB).
                _output_json(
                    {
                        "tracking_table": None,
                        "resolved_table": None,
                        "applied": [],
                        "pending": [],
                        "current": None,
                        "total": 0,
                        "migrations": [],
                        "summary": {"applied": 0, "pending": 0, "total": 0},
                        "hints": [],
                        "warning": f"Migrations directory not found: {migrations_dir.absolute()}",
                    },
                    output_file,
                    console,
                )
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
                    error_console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
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

                _json_threshold = _effective_rebuild_threshold(rebuild_threshold, config)
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

                threshold = _effective_rebuild_threshold(rebuild_threshold, config)

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

    except typer.Exit:
        raise
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
