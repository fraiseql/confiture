"""`confiture migrate status`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from confiture.cli.commands.migrate._settings import _effective_rebuild_threshold
from confiture.cli.dsn import (
    DATABASE_URL_OPTION_HELP,
    NO_CONFIG_OPTION_HELP,
    config_is_explicit,
    has_intentional_dsn_source,
    resolve_database_url,
)
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.common import handle_output
from confiture.cli.helpers import (
    _emit_hint,
    _find_orphaned_sql_files,
    _get_tracking_table,
    _output_json,
    _print_duplicate_versions_warning,
    _print_orphaned_files_warning,
    console,
    error_console,
    open_connection,
)
from confiture.cli.options import format_option
from confiture.core import connection as _core_connection
from confiture.core import ledger as _core_ledger
from confiture.core import migrator as _core_migrator
from confiture.core.migrator import (
    discover_migration_files,
    parse_migration_filename,
)
from confiture.core.migrator import (
    find_duplicate_migration_versions as _status_find,
)
from confiture.core.strategy import find_rebuild_strategy_files
from confiture.exceptions import ConfiturError


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
    if not migrations_dir.exists():
        _report_missing_migrations_dir(migrations_dir, output_format, output_file)
        return
    migration_files = discover_migration_files(migrations_dir)
    orphaned_sql_files = _find_orphaned_sql_files(migrations_dir)

    duplicate_versions = _status_find(migrations_dir)
    if not migration_files:
        _report_no_migrations(orphaned_sql_files, output_format, output_file)
        return

    try:
        facts = _probe_database(
            ctx,
            database_url=database_url,
            config=config,
            no_config=no_config,
            output_format=output_format,
        )
        rows = _migration_rows(migration_files, facts)
        hints = _status_hints(facts, output_format)
        rebuild_reasons = (
            _rebuild_reasons(rows.pending, migrations_dir, rebuild_threshold, config)
            if check_rebuild and rows.pending
            else []
        )
        if output_format == "json":
            _render_status_json(
                facts,
                rows,
                hints=hints,
                total=len(migration_files),
                orphaned=orphaned_sql_files,
                duplicates=duplicate_versions,
                rebuild_reasons=rebuild_reasons,
                output_file=output_file,
            )
        elif output_format == "csv":
            csv_data = (
                ["version", "name", "status"],
                [[m["version"], m["name"], m["status"]] for m in rows.migrations],
            )
            handle_output("csv", {}, csv_data, output_file, console)
        else:
            _render_status_table(
                facts,
                rows,
                total=len(migration_files),
                orphaned=orphaned_sql_files,
                duplicates=duplicate_versions,
                rebuild_reasons=rebuild_reasons,
            )
    except typer.Exit:
        raise
    # Reason: documented: a probe failure of any kind is status's exit 3 with its own rendering
    except Exception as e:
        _render_status_error(e, output_format, output_file)
        raise typer.Exit(3) from e

    # Exit flags after output is written (avoids raising inside the try).
    if facts.db_source and facts.db_error:
        raise typer.Exit(3)
    if facts.tracking_table_absent and output_format != "csv":
        raise typer.Exit(2)
    if facts.db_source and not facts.db_error and not facts.tracking_table_absent and rows.pending:
        raise typer.Exit(1)


@dataclass(frozen=True)
class _StatusFacts:
    """What the database said — or that nothing was asked of it."""

    db_source: bool = False
    applied_versions: frozenset[str] = frozenset()
    applied_at_by_version: dict[str, Any] = field(default_factory=dict)
    db_error: str | None = None
    tracking_table_absent: bool = False
    tracking_table: str | None = None
    resolved_table: str | None = None
    ledger_elsewhere: tuple[str, ...] = ()


@dataclass(frozen=True)
class _StatusRows:
    migrations: list[dict[str, Any]]
    applied: list[str]
    pending: list[str]

    @property
    def current(self) -> str | None:
        return self.applied[-1] if self.applied else None


def _report_missing_migrations_dir(
    migrations_dir: Path, output_format: str, output_file: Path | None
) -> None:
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


def _report_no_migrations(
    orphaned: list[Path], output_format: str, output_file: Path | None
) -> None:
    if output_format == "json":
        result: dict[str, Any] = {
            "applied": [],
            "pending": [],
            "current": None,
            "total": 0,
            "migrations": [],
            "hints": [],
        }
        if orphaned:
            result["orphaned_migrations"] = [f.name for f in orphaned]
        _output_json(result, output_file, console)
    else:
        console.print("[yellow]No migrations found.[/yellow]")
        if orphaned:
            _print_orphaned_files_warning(orphaned, console)


def _probe_database(
    ctx: typer.Context,
    *,
    database_url: str | None,
    config: Path,
    no_config: bool,
    output_format: str,
) -> _StatusFacts:
    """Read the ledger — only on an *intentional* DSN source.

    A --database-url flag, --no-config, an explicit --config, or the canonical
    CONFITURE_DATABASE_URL connects. A merely-ambient DATABASE_URL must NOT force
    a connection — "status-unknown" (exit 0) stays the informative default
    (#152; supersedes the #140 flag-only carve-out). Two explicit sources still
    fail loud via CONFIG_007.
    """
    config_data: Any = None
    if has_intentional_dsn_source(ctx, database_url, no_config):
        override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
        )
        if override is not None:
            config_data = {"database_url": override}
        elif config is not None and config.exists():
            config_data = _core_connection.load_config(config)
    if config_data is None:
        return _StatusFacts()

    tracking_table = _get_tracking_table(config_data)
    try:
        with open_connection(config_data) as conn:
            migrator = _core_migrator.Migrator(connection=conn, migration_table=tracking_table)
            was_present = migrator.tracking_table_exists()
            # A bare name resolves through search_path since 0.41.0, so "absent" no
            # longer implies "nowhere in this database" (#188).
            elsewhere = (
                ()
                if was_present
                else tuple(_core_ledger.find_ledger_relations(conn, tracking_table))
            )
            migrator.initialize()
            # Reporting metadata only: a probe refused for lack of privilege must not
            # turn a working status into "could not connect to database".
            try:
                resolved = _core_ledger.probe_ledger(conn, tracking_table).resolved_name
            except ConfiturError:
                resolved = None
            applied = frozenset(migrator.get_applied_versions())
            applied_at = {
                row["version"]: row["applied_at"]
                for row in migrator.get_applied_migrations_with_timestamps()
            }
        return _StatusFacts(
            db_source=True,
            applied_versions=applied,
            applied_at_by_version=applied_at,
            tracking_table_absent=not was_present,
            tracking_table=tracking_table,
            resolved_table=resolved,
            ledger_elsewhere=elsewhere,
        )
    # Reason: status degrades to the file list when the database cannot be reached for any reason
    except Exception as e:
        if output_format != "json":
            error_console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
            console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")
        return _StatusFacts(db_source=True, db_error=str(e), tracking_table=tracking_table)


def _migration_rows(migration_files: list[Path], facts: _StatusFacts) -> _StatusRows:
    migrations: list[dict[str, Any]] = []
    applied: list[str] = []
    pending: list[str] = []
    known = facts.db_source and not facts.db_error
    for migration_file in migration_files:
        version, name = parse_migration_filename(migration_file.name)
        if known:
            # An absent tracking table means confiture has not been set up on
            # this database yet: every migration is pending.
            if facts.tracking_table_absent or version not in facts.applied_versions:
                status = "pending"
                pending.append(version)
            else:
                status = "applied"
                applied.append(version)
        else:
            status = "unknown"  # no config, or the connection failed
        migrations.append(
            {
                "version": version,
                "name": name,
                "status": status,
                "applied_at": (
                    facts.applied_at_by_version.get(version) if status == "applied" else None
                ),
            }
        )
    return _StatusRows(migrations=migrations, applied=applied, pending=pending)


def _status_hints(facts: _StatusFacts, output_format: str) -> list[str]:
    """An absent ledger is a quiet-success ambiguity worth a hint."""
    hints: list[str] = []
    if facts.tracking_table_absent:
        _emit_hint(
            "Tracking table not found in this database. All migrations "
            "are reported 'pending' — if the schema is already applied, "
            "run `confiture migrate baseline --through <version>` first.",
            hints_list=hints,
            format_=output_format,
        )
        if facts.ledger_elsewhere:
            _emit_hint(
                f"`{facts.tracking_table}` does not resolve on this "
                f"connection's search_path, but a relation of that name "
                f"exists in {', '.join(facts.ledger_elsewhere)}. Qualify "
                "`migration.tracking_table` or adjust search_path if that "
                "is the ledger you meant.",
                hints_list=hints,
                format_=output_format,
            )
    return hints


def _rebuild_reasons(
    pending: list[str], migrations_dir: Path, rebuild_threshold: int | None, config: Path
) -> list[str]:

    threshold = _effective_rebuild_threshold(rebuild_threshold, config)
    reasons: list[str] = []
    if len(pending) >= threshold:
        reasons.append(f"{len(pending)} pending migrations exceed threshold of {threshold}")
    reasons.extend(
        f"Migration {sf.name} has '-- Strategy: rebuild' header"
        for sf in find_rebuild_strategy_files(migrations_dir)
    )
    return reasons


def _absent_ledger_warning(facts: _StatusFacts) -> str:
    return (
        f"{facts.tracking_table or 'The migration ledger'} not found in this "
        "database. All migrations shown as 'pending'. Run `confiture migrate up` "
        "to apply all migrations, or `confiture migrate baseline --through "
        "<version>` if the schema is already applied."
    )


def _render_status_json(
    facts: _StatusFacts,
    rows: _StatusRows,
    *,
    hints: list[str],
    total: int,
    orphaned: list[Path],
    duplicates: dict[str, list[Path]],
    rebuild_reasons: list[str],
    output_file: Path | None,
) -> None:
    result: dict[str, Any] = {
        "tracking_table": facts.tracking_table,
        "resolved_table": facts.resolved_table,
        "applied": rows.applied,
        "pending": rows.pending,
        "current": rows.current,
        "total": total,
        "migrations": rows.migrations,
        "summary": {"applied": len(rows.applied), "pending": len(rows.pending), "total": total},
        "hints": hints,
    }
    if facts.db_error:
        result["warning"] = f"Could not connect to database: {facts.db_error}"
    elif facts.tracking_table_absent:
        result["warning"] = _absent_ledger_warning(facts)
    if orphaned:
        result["orphaned_migrations"] = [f.name for f in orphaned]
    if duplicates:
        result["duplicate_versions"] = {
            v: [f.name for f in files] for v, files in duplicates.items()
        }
    if rebuild_reasons:
        result["rebuild_recommended"] = True
        result["rebuild_reasons"] = rebuild_reasons
    _output_json(result, output_file, console)


def _render_status_table(
    facts: _StatusFacts,
    rows: _StatusRows,
    *,
    total: int,
    orphaned: list[Path],
    duplicates: dict[str, list[Path]],
    rebuild_reasons: list[str],
) -> None:

    table = Table(title="Migrations")
    table.add_column("Version", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Status", style="yellow")
    for migration in rows.migrations:
        if migration["status"] == "applied":
            status_display = "[green]✅ applied[/green]"
        elif migration["status"] == "pending":
            status_display = "[yellow]⏳ pending[/yellow]"
        else:
            status_display = "[dim]⚠️ unknown (no config)[/dim]"
        table.add_row(migration["version"], migration["name"], status_display)
    console.print(table)
    console.print(f"\n📊 Total: {total} migrations", end="")
    if facts.applied_versions:
        console.print(f" ({len(rows.applied)} applied, {len(rows.pending)} pending)")
    else:
        console.print()
    if facts.tracking_table_absent:
        console.print(
            f"\n[yellow]⚠️  {facts.tracking_table or 'The migration ledger'} not "
            "found in this database. Migrations shown as 'pending'.[/yellow]"
        )
        console.print("[yellow]   Run `confiture migrate up` to apply all migrations, or[/yellow]")
        console.print(
            "[yellow]   `confiture migrate baseline --through <version>` if the "
            "schema is already applied.[/yellow]"
        )
    if duplicates:
        _print_duplicate_versions_warning(duplicates, console)
    if orphaned:
        _print_orphaned_files_warning(orphaned, console)
    if rebuild_reasons:
        console.print("\n[yellow]🔄 Rebuild recommended:[/yellow]")
        for reason in rebuild_reasons:
            console.print(f"  • {reason}")
        console.print("\n[yellow]  Run: confiture migrate rebuild --drop-schemas --yes[/yellow]")


def _render_status_error(error: Exception, output_format: str, output_file: Path | None) -> None:
    """#145: a genuinely unexpected status failure — the informative payloads above are not errors."""
    if output_format == "json":
        fail(error, json_mode=True, output_file=output_file)
    elif output_format == "csv":
        handle_output("csv", {}, (["error"], [[str(error)]]), output_file, console)
    else:
        console.print(f"[red]❌ Error: {error}[/red]")
