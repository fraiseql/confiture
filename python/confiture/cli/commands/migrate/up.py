"""`confiture migrate up`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
from confiture.cli.helpers import (
    _find_orphaned_sql_files,
    _get_tracking_table,
    _print_orphaned_files_warning,
    console,
    error_console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.locking import resolve_lock_settings


@cli_boundary
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
    format_output: str = format_option("text", "json"),
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
        _validate_up_flags(
            dry_run=dry_run,
            dry_run_execute=dry_run_execute,
            force=force,
            on_checksum_mismatch=on_checksum_mismatch,
        )
        if verbose:
            logging.getLogger("confiture").setLevel(logging.DEBUG)
        batch = None
        if batched:
            from confiture.core.large_tables import BatchConfig

            batch = BatchConfig(batch_size=batch_size, sleep_between_batches=batch_sleep)

        # Duplicate versions are a hard block; no database needed to see them.
        duplicates = find_duplicate_migration_versions(migrations_dir)
        if duplicates:
            _refuse_duplicate_versions(duplicates, format_output, output_file)

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
        config_data = (
            {"database_url": _db_url_override}
            if _db_url_override is not None
            else load_config(config)
        )
        # Environment-level migration settings apply only when YAML is the DSN
        # source; an invalid file is an error, only its absence means defaults.
        env_cfg = _load_environment_if_present(config) if _db_url_override is None else None
        effective_strict_mode = strict or bool(env_cfg and env_cfg.migration.strict_mode)
        install_helpers = bool(env_cfg and env_cfg.migration.view_helpers == "auto")
        lock_timeout, no_lock = resolve_lock_settings(
            env_cfg.migration.locking if env_cfg else None, lock_timeout, no_lock
        )

        # Advisory lines go to stderr in JSON mode: stdout is the payload.
        say = error_console if is_json(format_output) else console
        _print_mode_warnings(say, force=force, no_lock=no_lock)
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
            "batch": batch,
        }
        with MigratorSession(
            None,
            migrations_dir,
            database_url_override=dsn_from_config(config_data),
            migration_table_override=_get_tracking_table(config_data),
            command="confiture migrate up",
        ) as session:
            if dry_run or dry_run_execute:
                if not is_json(format_output):
                    display_dry_run_header("testing" if dry_run_execute else "analysis")
                session.up(dry_run=True, **options)
                _render_dry_run_analysis(
                    reporter.pending,
                    migrations_dir=migrations_dir,
                    migration_id=f"dry_run_{config.stem}",
                    execute=dry_run_execute,
                    format_output=format_output,
                    output_file=output_file,
                    estimate_rows=_row_estimator(session.connection),
                )
                if dry_run:
                    return
                if not yes and not ask_dry_run_execute_confirmation():
                    say.print("[yellow]Cancelled - no changes applied[/yellow]")
                    return
                reporter.reset()
                result = session.up(dry_run_execute=True, **options)
            else:
                result = session.up(**options)
        _render_up_result(result, reporter, format_output, output_file, force=force)
    except typer.Exit:
        raise
    except ChecksumVerificationError as e:
        _report_checksum_failure(e, format_output, output_file)
    except LockAcquisitionError as e:
        _report_lock_failure(e, lock_timeout, format_output, output_file)
    except Exception as e:
        if is_json(format_output):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e


def _validate_up_flags(
    *, dry_run: bool, dry_run_execute: bool, force: bool, on_checksum_mismatch: str
) -> None:
    """Flag combinations that make no sense exit 2 before anything runs."""
    if dry_run and dry_run_execute:
        error_console.print("[red]❌ Error: Cannot use both --dry-run and --dry-run-execute[/red]")
        raise typer.Exit(2)
    if (dry_run or dry_run_execute) and force:
        error_console.print("[red]❌ Error: Cannot use --dry-run with --force[/red]")
        raise typer.Exit(2)
    valid_mismatch_behaviors = ("fail", "warn", "ignore")
    if on_checksum_mismatch not in valid_mismatch_behaviors:
        error_console.print(
            f"[red]❌ Error: Invalid --on-checksum-mismatch '{on_checksum_mismatch}'. "
            f"Use one of: {', '.join(valid_mismatch_behaviors)}[/red]"
        )
        raise typer.Exit(2)


def _refuse_duplicate_versions(
    duplicates: dict[str, list[Path]], format_output: str, output_file: Path | None
) -> None:
    if is_json(format_output):
        from confiture.exceptions import MigrationConflictError

        fail(
            MigrationConflictError(
                "Duplicate migration versions detected: " + ", ".join(sorted(duplicates)),
                conflicting_files=sorted(f.name for files in duplicates.values() for f in files),
            ),
            json_mode=True,
            output_file=output_file,
        )
    error_console.print("[red]❌ Duplicate migration versions detected — refusing to proceed[/red]")
    error_console.print("[red]Multiple migration files share the same version number:[/red]\n")
    for version, files in sorted(duplicates.items()):
        error_console.print(f"  Version {version}:")
        for f in files:
            error_console.print(f"    • {f.name}")
    error_console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
    error_console.print(
        "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
    )
    raise typer.Exit(3)


def _print_mode_warnings(say: Any, *, force: bool, no_lock: bool) -> None:
    if force:
        say.print("[yellow]⚠️  Force mode enabled - skipping migration state checks[/yellow]")
        say.print(
            "[yellow]This may cause issues if applied incorrectly. Use with caution![/yellow]\n"
        )
    if no_lock:
        say.print("[yellow]⚠️  Locking disabled - DANGEROUS in multi-pod environments![/yellow]")
        say.print(
            "[yellow]Concurrent migrations may cause race conditions or data corruption.[/yellow]\n"
        )


def _report_checksum_failure(error: Any, format_output: str, output_file: Path | None) -> None:
    if is_json(format_output):
        fail(error, json_mode=True, output_file=output_file)
    error_console.print("[red]❌ Checksum verification failed![/red]\n")
    for m in error.mismatches:
        error_console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
        expected_preview = m.expected[:16] if m.expected else "(none)"
        error_console.print(f"    Expected: {expected_preview}...")
        error_console.print(f"    Actual:   {m.actual[:16]}...")
    error_console.print(
        "\n[yellow]💡 Tip: Use 'confiture verify-checksums --fix' to update checksums, "
        "or --no-verify-checksums to skip[/yellow]"
    )
    raise typer.Exit(1) from error


def _report_lock_failure(
    error: Any, lock_timeout: int, format_output: str, output_file: Path | None
) -> None:
    if is_json(format_output):
        from confiture.cli.error_json import lock_error_to_confiture

        # LOCK_1300 envelope enriched with holder identity (#147).
        fail(lock_error_to_confiture(error), json_mode=True, output_file=output_file)
    print_error_to_console(error, error_console)
    if error.timeout:
        error_console.print(
            f"[yellow]💡 Tip: Increase timeout with --lock-timeout {lock_timeout * 2}[/yellow]"
        )
    else:
        error_console.print(
            "[yellow]💡 Tip: Check if another migration is running, or use --no-lock (dangerous)[/yellow]"
        )
    raise typer.Exit(6) from error


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
