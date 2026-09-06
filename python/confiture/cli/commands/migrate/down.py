"""`confiture migrate down` and `down-to`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from confiture.cli.commands.migrate._dry_run_render import _render_dry_run_analysis, _row_estimator
from confiture.cli.commands.migrate._settings import _load_environment_if_present
from confiture.cli.dsn import (
    DATABASE_URL_OPTION_HELP,
    NO_CONFIG_OPTION_HELP,
    config_is_explicit,
    resolve_database_url,
)
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import _get_tracking_table, _output_json, console, error_console, is_json
from confiture.cli.options import format_option
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.locking import resolve_lock_settings


@cli_boundary
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
    lock_timeout: int | None = typer.Option(
        None,
        "--lock-timeout",
        help="Lock timeout in milliseconds (default: migration.locking.timeout_ms, else 30000)",
    ),
    no_lock: bool | None = typer.Option(
        None,
        "--no-lock",
        help="Disable migration locking (default: migration.locking.enabled; DANGEROUS in multi-pod)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run (default: off)",
    ),
    format_output: str = format_option("text", "json"),
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

    if verbose:
        logging.getLogger("confiture").setLevel(logging.DEBUG)

    try:
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
                    migrations_dir=migrations_dir,
                    migration_id=f"dry_run_rollback_{config.stem}",
                    execute=False,
                    format_output=format_output,
                    output_file=output_file,
                    estimate_rows=_row_estimator(session.connection),
                    rollback=True,
                )
                return

            if not is_json(format_output):
                console.print(f"[cyan]📦 Rolling back up to {steps} migration(s)[/cyan]\n")
            env_cfg = _load_environment_if_present(config) if _db_url_override is None else None
            lock_timeout, no_lock = resolve_lock_settings(
                env_cfg.migration.locking if env_cfg else None, lock_timeout, no_lock
            )
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


@cli_boundary
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
    format_output: str = format_option("text", "json"),
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
