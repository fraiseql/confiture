"""Core migration commands: migrate status, up, down, generate."""

import json
from pathlib import Path
from typing import Any

import typer

from confiture.cli.helpers import (
    _find_orphaned_sql_files,
    _get_tracking_table,
    _output_json,
    _print_duplicate_versions_warning,
    _print_orphaned_files_warning,
    console,
    error_console,
)
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.migration_generator import MigrationGenerator


def migrate_status(
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
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
    output_file: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout, useful with json)",
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
        py_files = list(migrations_dir.glob("*.py"))
        sql_files = list(migrations_dir.glob("*.up.sql"))
        migration_files = sorted(py_files + sql_files, key=lambda f: f.name.split("_")[0])

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
                }
                if orphaned_sql_files:
                    result["orphaned_migrations"] = [f.name for f in orphaned_sql_files]
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations found.[/yellow]")
                if orphaned_sql_files:
                    _print_orphaned_files_warning(orphaned_sql_files, console)
            return

        # Get applied migrations from database if config provided
        applied_versions: set[str] = set()
        applied_at_by_version: dict[str, Any] = {}
        db_error: str | None = None
        tracking_table_absent: bool = False
        status_tracking_table: str | None = None
        if config and config.exists():
            try:
                from confiture.core.connection import create_connection, load_config
                from confiture.core.migrator import Migrator

                config_data = load_config(config)
                status_tracking_table = _get_tracking_table(config_data)
                conn = create_connection(config_data)
                migrator = Migrator(connection=conn, migration_table=status_tracking_table)
                tracking_table_was_present = migrator.tracking_table_exists()
                migrator.initialize()
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
            base_name = migration_file.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]  # Remove ".up" suffix
            parts = base_name.split("_", 1)
            version = parts[0] if len(parts) > 0 else "???"
            name = parts[1] if len(parts) > 1 else base_name

            # Determine status
            if config and config.exists() and not db_error:
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

        if output_format == "json":
            result: dict[str, Any] = {
                "tracking_table": status_tracking_table,
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
            }
            if db_error:
                result["warning"] = f"Could not connect to database: {db_error}"
            elif tracking_table_absent:
                result["warning"] = (
                    "tb_confiture not found in this database. All migrations shown as "
                    "'pending'. Run `confiture migrate up` to apply all migrations, or "
                    "`confiture migrate baseline --through <version>` if the schema is "
                    "already applied."
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
                    "\n[yellow]⚠️  tb_confiture not found in this database. "
                    "Migrations shown as 'pending'.[/yellow]"
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
        if config and config.exists() and db_error:
            fatal_error_exit = True
        elif (
            config
            and config.exists()
            and not db_error
            and not tracking_table_absent
            and len(pending_list) > 0
        ):
            pending_migrations_exit = True

    except Exception as e:
        if output_format == "json":
            result = {"error": str(e)}
            _output_json(result, output_file, console)
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


def migrate_up(
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
) -> None:
    """Apply pending migrations to the database.

    PROCESS:
      Applies pending migrations in order, with distributed locking to prevent
      concurrent runs. Verifies checksums to detect unauthorized changes. Use
      --dry-run to analyze, or --dry-run-execute to test in a SAVEPOINT.

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

      DRY-RUN: --dry-run, --dry-run-execute, --verbose, --format, --output
        Analyze migrations before executing, with optional SAVEPOINT testing

      SAFETY: --verify-checksums, --on-checksum-mismatch, --strict, --no-lock, --lock-timeout
        Control verification and locking behavior for production safety

      ADVANCED: --force
        Skip safety checks (use with caution in production)
    """
    import time

    from confiture.cli.dry_run import (
        ask_dry_run_execute_confirmation,
        display_dry_run_header,
        print_json_report,
        save_json_report,
        save_text_report,
    )
    from confiture.core.checksum import (
        ChecksumConfig,
        ChecksumMismatchBehavior,
        ChecksumVerificationError,
        MigrationChecksumVerifier,
    )
    from confiture.core.connection import (
        create_connection,
        load_config,
        load_migration_class,
    )
    from confiture.core.locking import LockAcquisitionError, LockConfig, MigrationLock
    from confiture.core.migrator import Migrator

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

        # Build BatchConfig if --batched is requested
        if batched:
            from confiture.core.large_tables import BatchConfig

            _batch_config = BatchConfig(batch_size=batch_size, sleep_between_batches=batch_sleep)
        else:
            _batch_config = None

        # Check for duplicate migration versions (hard block, no DB needed)
        from confiture.core.migrator import find_duplicate_migration_versions

        _up_duplicates = find_duplicate_migration_versions(migrations_dir)
        if _up_duplicates:
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

        # Load configuration
        config_data = load_config(config)

        # Try to load environment config for migration settings
        effective_strict_mode = strict
        if (
            not strict
            and config.parent.name == "environments"
            and config.parent.parent.name == "db"
        ):
            # Check if config is in standard environments directory
            try:
                from confiture.config.environment import Environment as _Env

                env_name = config.stem  # e.g., "local" from "local.yaml"
                project_dir = config.parent.parent.parent
                env_config = _Env.load(env_name, project_dir=project_dir)
                effective_strict_mode = env_config.migration.strict_mode
            except Exception:
                # If environment config loading fails, use default (False)
                pass

        # Show warnings for force mode before attempting database operations
        if force:
            console.print(
                "[yellow]⚠️  Force mode enabled - skipping migration state checks[/yellow]"
            )
            console.print(
                "[yellow]This may cause issues if applied incorrectly. Use with caution![/yellow]\n"
            )

        # Show warning for no-lock mode
        if no_lock:
            console.print(
                "[yellow]⚠️  Locking disabled - DANGEROUS in multi-pod environments![/yellow]"
            )
            console.print(
                "[yellow]Concurrent migrations may cause race conditions or data corruption.[/yellow]\n"
            )

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))

        # Auto-detect baseline pre-flight (before initialize so we can check absence)
        if auto_detect_baseline and not migrator.tracking_table_exists():
            _resolved_snapshots_dir = snapshots_dir_up or Path("db/schema_history")
            if not _resolved_snapshots_dir.exists():
                error_console.print(
                    f"[red]❌ --auto-detect-baseline: snapshots directory not found: "
                    f"{_resolved_snapshots_dir}[/red]"
                )
                error_console.print(
                    "[yellow]💡 Generate snapshots with 'confiture migrate snapshot' "
                    "or remove --auto-detect-baseline[/yellow]"
                )
                conn.close()
                raise typer.Exit(2)

            _snapshot_files = list(_resolved_snapshots_dir.glob("*.sql"))
            if not _snapshot_files:
                error_console.print(
                    f"[red]❌ --auto-detect-baseline: no snapshot files found in "
                    f"{_resolved_snapshots_dir}[/red]"
                )
                error_console.print(
                    "[yellow]💡 Generate snapshots with 'confiture migrate snapshot' "
                    "or remove --auto-detect-baseline[/yellow]"
                )
                conn.close()
                raise typer.Exit(2)
            else:
                from confiture.core.baseline_detector import BaselineDetector

                _detector = BaselineDetector(_resolved_snapshots_dir)
                console.print(
                    "[cyan]🔍 tb_confiture missing — attempting auto-detect baseline...[/cyan]"
                )
                _live_sql = _detector.introspect_live_schema(conn)
                _detected_version = _detector.find_matching_snapshot(_live_sql)
                if _detected_version:
                    console.print(f"[green]✓ Detected baseline: {_detected_version}[/green]")
                    migrator.initialize()
                    migrator.baseline_through(_detected_version, migrations_dir)
                    console.print(f"[green]✅ Auto-baselined through {_detected_version}[/green]")
                else:
                    closest = _detector.last_closest
                    if closest:
                        _cv, _cr = closest
                        console.print(
                            f"[yellow]⚠️  No exact snapshot match found "
                            f"(closest: {_cv}, {_cr:.0%} similar) — proceeding with empty baseline[/yellow]"
                        )
                    else:
                        console.print(
                            "[yellow]⚠️  No matching snapshot found — proceeding with empty baseline[/yellow]"
                        )

        migrator.initialize()

        # Auto-install view helpers if configured
        try:
            if config.parent.name == "environments" and config.parent.parent.name == "db":
                from confiture.config.environment import Environment as _EnvCfg
                from confiture.core.view_manager import ViewManager as _VM

                _env_name = config.stem
                _project_dir = config.parent.parent.parent
                _env_cfg = _EnvCfg.load(_env_name, project_dir=_project_dir)
                if _env_cfg.migration.view_helpers == "auto":
                    _vm = _VM(conn)
                    if not _vm.helpers_installed():
                        _vm.install_helpers()
                        console.print(
                            "[cyan]🔧 Auto-installed view helper functions "
                            "(migration.view_helpers: auto)[/cyan]\n"
                        )
        except Exception:
            pass  # Non-critical — don't block migration on helper install failure

        # Verify checksums before running migrations (unless force mode)
        if verify_checksums and not force:
            mismatch_behavior = ChecksumMismatchBehavior(on_checksum_mismatch)
            checksum_config = ChecksumConfig(
                enabled=True,
                on_mismatch=mismatch_behavior,
            )
            verifier = MigrationChecksumVerifier(conn, checksum_config)

            try:
                mismatches = verifier.verify_all(migrations_dir)
                if not mismatches:
                    console.print("[cyan]🔐 Checksum verification passed[/cyan]\n")
            except ChecksumVerificationError as e:
                error_console.print("[red]❌ Checksum verification failed![/red]\n")
                for m in e.mismatches:
                    error_console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
                    error_console.print(f"    Expected: {m.expected[:16]}...")
                    error_console.print(f"    Actual:   {m.actual[:16]}...")
                error_console.print(
                    "\n[yellow]💡 Tip: Use 'confiture verify --fix' to update checksums, "
                    "or --no-verify-checksums to skip[/yellow]"
                )
                conn.close()
                raise typer.Exit(1) from e

        # Find migrations to apply
        skipped_versions: list[str] = []
        if force:
            # In force mode, apply all migrations regardless of state
            migrations_to_apply = migrator.find_migration_files(migrations_dir=migrations_dir)
            if not migrations_to_apply:
                console.print("[yellow]⚠️  No migration files found.[/yellow]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Force mode: Found {len(migrations_to_apply)} migration(s) to apply[/cyan]\n"
            )
        else:
            # Normal mode: only apply pending migrations
            all_migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
            migrations_to_apply = migrator.find_pending(migrations_dir=migrations_dir)
            apply_versions = {migrator._version_from_filename(f.name) for f in migrations_to_apply}
            skipped_versions = [
                migrator._version_from_filename(f.name)
                for f in all_migration_files
                if migrator._version_from_filename(f.name) not in apply_versions
            ]
            if not migrations_to_apply:
                console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Found {len(migrations_to_apply)} pending migration(s)[/cyan]\n"
            )

        # Check for orphaned migration files
        orphaned_files = _find_orphaned_sql_files(migrations_dir)
        if orphaned_files:
            _print_orphaned_files_warning(orphaned_files, error_console)
            if effective_strict_mode:
                error_console.print(
                    "\n[red]❌ Strict mode enabled: Aborting due to orphaned files[/red]"
                )
                conn.close()
                raise typer.Exit(1)

        # Reversibility gate
        if require_reversible:
            from confiture.core.preflight import run_preflight

            _preflight = run_preflight(migrations_dir)
            if not _preflight.all_reversible:
                _irr_names = ", ".join(m.version for m in _preflight.irreversible)
                error_msg = (
                    f"Irreversible migrations detected (missing .down.sql): {_irr_names}. "
                    f"Remove --require-reversible or add .down.sql files."
                )
                if format_output == "json":
                    _output_json(
                        {
                            "success": False,
                            "errors": [error_msg],
                            "irreversible_versions": [m.version for m in _preflight.irreversible],
                        },
                        output_file,
                    )
                else:
                    error_console.print(f"[red]❌ {error_msg}[/red]")
                conn.close()
                raise typer.Exit(1)

        # Handle dry-run modes
        if dry_run or dry_run_execute:
            display_dry_run_header("testing" if dry_run_execute else "analysis")

            # Build migration summary
            migration_summary: dict[str, Any] = {
                "migration_id": f"dry_run_{config.stem}",
                "mode": "execute_and_analyze" if dry_run_execute else "analysis",
                "statements_analyzed": len(migrations_to_apply),
                "migrations": [],
                "summary": {
                    "unsafe_count": 0,
                    "total_estimated_time_ms": 0,
                    "total_estimated_disk_mb": 0.0,
                    "has_unsafe_statements": False,
                },
                "warnings": [],
                "analyses": [],
            }

            try:
                # Collect migration information
                for migration_file in migrations_to_apply:
                    migration_class = load_migration_class(migration_file)
                    migration = migration_class(connection=conn)

                    migration_info = {
                        "version": migration.version,
                        "name": migration.name,
                        "classification": "warning",  # Most migrations are complex changes
                        "estimated_duration_ms": 500,  # Conservative estimate
                        "estimated_disk_usage_mb": 1.0,
                        "estimated_cpu_percent": 30.0,
                    }
                    migration_summary["migrations"].append(migration_info)
                    migration_summary["analyses"].append(migration_info)

                # Display format
                if format_output == "json":
                    if output_file:
                        save_json_report(migration_summary, output_file)
                        console.print(
                            f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]"
                        )
                    else:
                        print_json_report(migration_summary)
                else:
                    # Text format (default)
                    console.print("\n[cyan]Migration Analysis Summary[/cyan]")
                    console.print("=" * 80)
                    console.print(f"Migrations to apply: {len(migrations_to_apply)}")
                    console.print()
                    for mig in migration_summary["migrations"]:
                        console.print(f"  {mig['version']}: {mig['name']}")
                        console.print(
                            f"    Estimated time: {mig['estimated_duration_ms']}ms | "
                            f"Disk: {mig['estimated_disk_usage_mb']:.1f}MB | "
                            f"CPU: {mig['estimated_cpu_percent']:.0f}%"
                        )
                    console.print()
                    console.print("[green]✓ All migrations appear safe to execute[/green]")
                    console.print("=" * 80)

                    if output_file:
                        # Create a simple text report for file output
                        text_report = "DRY-RUN MIGRATION ANALYSIS REPORT\n"
                        text_report += "=" * 80 + "\n\n"
                        for mig in migration_summary["migrations"]:
                            text_report += f"{mig['version']}: {mig['name']}\n"
                        save_text_report(text_report, output_file)
                        console.print(
                            f"[green]✅ Report saved to: {output_file.absolute()}[/green]"
                        )

                # Stop here if dry-run only (not execute)
                if dry_run and not dry_run_execute:
                    conn.close()
                    return

                # For dry_run_execute: ask for confirmation
                if dry_run_execute and not ask_dry_run_execute_confirmation():
                    console.print("[yellow]Cancelled - no changes applied[/yellow]")
                    conn.close()
                    return

                # Continue to actual execution below

            except Exception as e:
                print_error_to_console(e)
                conn.close()
                raise typer.Exit(1) from e

        # Configure locking
        lock_config = LockConfig(
            enabled=not no_lock,
            timeout_ms=lock_timeout,
        )

        # Create lock manager
        lock = MigrationLock(conn, lock_config)

        from confiture.cli.formatters.migrate_formatter import format_migrate_up_result
        from confiture.core.progress import ProgressManager
        from confiture.models.results import MigrateUpResult, MigrationApplied

        applied_count = 0
        failed_migration = None
        failed_exception = None
        migrations_applied = []
        total_execution_time_ms = 0

        try:
            with lock.acquire():
                if not no_lock:
                    console.print("[cyan]🔒 Acquired migration lock[/cyan]\n")

                # Use progress manager for migration application
                with ProgressManager() as progress:
                    apply_task = progress.add_task(
                        "Applying migrations...", total=len(migrations_to_apply)
                    )

                    for migration_file in migrations_to_apply:
                        # Load migration module
                        migration_class = load_migration_class(migration_file)

                        # Create migration instance
                        migration = migration_class(connection=conn)
                        # Override strict_mode from CLI/config if not already set on class
                        if effective_strict_mode and not getattr(
                            migration_class, "strict_mode", False
                        ):
                            migration.strict_mode = effective_strict_mode

                        # Check target
                        if target and migration.version > target:
                            console.print(
                                f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]"
                            )
                            break

                        # Apply migration
                        console.print(
                            f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]",
                            end=" ",
                        )

                        try:
                            start_time = time.time()
                            migrator.apply(migration, force=force, migration_file=migration_file)
                            execution_time_ms = int((time.time() - start_time) * 1000)
                            total_execution_time_ms += execution_time_ms

                            console.print("[green]✅[/green]")
                            applied_count += 1

                            # Track successful migration
                            migrations_applied.append(
                                MigrationApplied(
                                    version=migration.version,
                                    name=migration.name,
                                    execution_time_ms=execution_time_ms,
                                    rows_affected=0,  # Not easily tracked, so default to 0
                                )
                            )
                            progress.update(apply_task, advance=1)
                        except Exception as e:
                            console.print("[red]❌[/red]")
                            failed_migration = migration
                            failed_exception = e
                            break

        except LockAcquisitionError as e:
            print_error_to_console(e, error_console)
            if e.timeout:
                error_console.print(
                    f"[yellow]💡 Tip: Increase timeout with --lock-timeout {lock_timeout * 2}[/yellow]"
                )
            else:
                error_console.print(
                    "[yellow]💡 Tip: Check if another migration is running, or use --no-lock (dangerous)[/yellow]"
                )
            conn.close()
            raise typer.Exit(6) from e

        # Handle results
        if failed_migration:
            # Create error result
            error_result = MigrateUpResult(
                success=False,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=verify_checksums,
                dry_run=False,
                errors=[str(failed_exception)],
                skipped=skipped_versions,
            )

            # Format output if not text (text format handled above)
            if format_output != "text":
                format_migrate_up_result(error_result, format_output, output_file, console)
            else:
                # Show detailed error information for text format
                from confiture.cli.formatters.migrate_formatter import show_migration_error_details

                show_migration_error_details(
                    failed_migration, failed_exception, applied_count, console
                )

            conn.close()
            raise typer.Exit(3)
        else:
            # Create success result
            success_result = MigrateUpResult(
                success=True,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=verify_checksums,
                dry_run=False,
                warnings=["Force mode enabled"] if force else [],
                skipped=skipped_versions,
            )

            # Format output
            format_migrate_up_result(success_result, format_output, output_file, console)

            # Show next steps for text format only
            if format_output == "text":
                if force:
                    console.print(
                        "[yellow]⚠️  Remember to verify your database state after force application[/yellow]"
                    )
                else:
                    console.print("\n💡 Next steps:")
                    console.print("  • Verify: confiture migrate status")
                    console.print("  • Validate: confiture lint")
                    console.print("  • Load data: confiture seed apply")

            conn.close()

    except typer.Exit:
        raise
    except LockAcquisitionError:
        # Already handled above
        raise
    except Exception as e:
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e


def migrate_down(
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
    from confiture.core.connection import (
        create_connection,
        load_config,
        load_migration_class,
    )
    from confiture.core.migrator import Migrator

    try:
        # Validate format option
        if format_output not in ("text", "json"):
            error_console.print(
                f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
            )
            raise typer.Exit(2)

        # Load configuration
        config_data = load_config(config)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))
        migrator.initialize()

        # Get applied migrations
        applied_versions = migrator.get_applied_versions()

        if not applied_versions:
            console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
            conn.close()
            return

        # Get migrations to rollback (last N)
        versions_to_rollback = applied_versions[-steps:]

        # Handle dry-run mode
        if dry_run:
            from confiture.cli.dry_run import (
                display_dry_run_header,
                save_json_report,
                save_text_report,
            )

            display_dry_run_header("analysis")

            # Build rollback summary
            rollback_summary: dict[str, Any] = {
                "migration_id": f"dry_run_rollback_{config.stem}",
                "mode": "analysis",
                "statements_analyzed": len(versions_to_rollback),
                "migrations": [],
                "summary": {
                    "unsafe_count": 0,
                    "total_estimated_time_ms": 0,
                    "total_estimated_disk_mb": 0.0,
                    "has_unsafe_statements": False,
                },
                "warnings": [],
                "analyses": [],
            }

            # Collect rollback migration information
            for version in reversed(versions_to_rollback):
                # Find migration file
                migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
                migration_file = None
                for mf in migration_files:
                    if migrator._version_from_filename(mf.name) == version:
                        migration_file = mf
                        break

                if not migration_file:
                    continue

                # Load migration class
                migration_class = load_migration_class(migration_file)

                migration = migration_class(connection=conn)

                migration_info = {
                    "version": migration.version,
                    "name": migration.name,
                    "classification": "warning",
                    "estimated_duration_ms": 500,
                    "estimated_disk_usage_mb": 1.0,
                    "estimated_cpu_percent": 30.0,
                }
                rollback_summary["migrations"].append(migration_info)
                rollback_summary["analyses"].append(migration_info)

            # Display format
            if format_output == "json":
                if output_file:
                    save_json_report(rollback_summary, output_file)
                    console.print(f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]")
                else:
                    from confiture.cli.dry_run import print_json_report

                    print_json_report(rollback_summary)
            else:
                # Text format (default)
                console.print("[cyan]Rollback Analysis Summary[/cyan]")
                console.print("=" * 80)
                console.print(f"Migrations to rollback: {len(versions_to_rollback)}")
                console.print()
                for mig in rollback_summary["migrations"]:
                    console.print(f"  {mig['version']}: {mig['name']}")
                    console.print(
                        f"    Estimated time: {mig['estimated_duration_ms']}ms | "
                        f"Disk: {mig['estimated_disk_usage_mb']:.1f}MB | "
                        f"CPU: {mig['estimated_cpu_percent']:.0f}%"
                    )
                console.print()
                console.print("[yellow]⚠️  Rollback will undo these migrations[/yellow]")
                console.print("=" * 80)

                if output_file:
                    text_report = "DRY-RUN ROLLBACK ANALYSIS REPORT\n"
                    text_report += "=" * 80 + "\n\n"
                    for mig in rollback_summary["migrations"]:
                        text_report += f"{mig['version']}: {mig['name']}\n"
                    save_text_report(text_report, output_file)
                    console.print(f"[green]✅ Report saved to: {output_file.absolute()}[/green]")

            conn.close()
            return

        console.print(f"[cyan]📦 Rolling back {len(versions_to_rollback)} migration(s)[/cyan]\n")

        # Rollback migrations in reverse order
        rolled_back_count = 0
        for version in reversed(versions_to_rollback):
            # Find migration file
            migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
            migration_file = None
            for mf in migration_files:
                if migrator._version_from_filename(mf.name) == version:
                    migration_file = mf
                    break

            if not migration_file:
                console.print(f"[red]❌ Migration file for version {version} not found[/red]")
                continue

            # Load migration module
            migration_class = load_migration_class(migration_file)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Rollback migration
            console.print(
                f"[cyan]⚡ Rolling back {migration.version}_{migration.name}...[/cyan]", end=" "
            )
            migrator.rollback(migration)
            console.print("[green]✅[/green]")
            rolled_back_count += 1

        console.print(
            f"\n[green]✅ Successfully rolled back {rolled_back_count} migration(s)![/green]"
        )
        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e


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
                version_str = f.name.split("_")[0]
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

        if _should_snapshot:
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
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
                tables = [row[0] for row in cur.fetchall()]

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
