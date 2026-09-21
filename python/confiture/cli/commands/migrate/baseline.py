"""`confiture migrate baseline`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _get_tracking_table,
    console,
    emit,
    is_json,
    open_connection,
    redact_url,
)
from confiture.cli.options import config_option, format_option, migrations_dir_option
from confiture.core import connection as _core_connection
from confiture.core import migrator as _core_migrator
from confiture.core.migrator import (
    find_duplicate_migration_versions as _baseline_find,
)
from confiture.core.migrator import (
    parse_migration_filename,
)
from confiture.exceptions import ConfigurationError, MigrationError


def _baseline_from_db_flow(
    *,
    from_db: str,
    through: str | None,
    source_table: str | None,
    migrations_dir: Path,
    config: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Drive the ``--from-db`` copy path and return what it copied (#119).

    Connects to the target database via the standard config flow and
    delegates to :meth:`Migrator.baseline_from_db`.
    """

    config_data = _core_connection.load_config(config)
    with open_connection(config_data) as conn:
        migrator = _core_migrator.Migrator(
            connection=conn,
            migration_table=_get_tracking_table(config_data),
        )
        migrator.initialize()
        report = migrator.baseline_from_db(
            source_dsn=from_db,
            migrations_dir=migrations_dir,
            through=through,
            dry_run=dry_run,
            source_table=source_table,
        )
    # The source DSN is printed and emitted, so never with its password.
    return {"mode": "from_db", "source": redact_url(from_db), "through": through, **report}


def _print_from_db(report: dict[str, Any]) -> None:
    dry_run = report["dry_run"]
    if report["through"] is not None:
        console.print(
            "[yellow]⚠️  --through with --from-db caps the copy at "
            f"version {report['through']!r}; source rows above the cap will be "
            "skipped.[/yellow]"
        )
    for warning in report["warnings"]:
        console.print(f"[yellow]⚠️  {warning}[/yellow]")
    if dry_run:
        console.print("\n[yellow]🔍 DRY RUN - no changes will be made[/yellow]")

    copied = report["copied"]
    skipped = report["skipped"]
    if not copied and not skipped:
        console.print("\n[yellow]No rows to copy.[/yellow]")
    else:
        console.print(f"\n[cyan]📋 Baseline from {report['source']}[/cyan]\n")
        for row in copied:
            marker = "would copy" if dry_run else "copied"
            console.print(f"  [green]✅ {row['version']} {row['name']} ({marker})[/green]")
        for version in skipped:
            console.print(f"  [dim]⏭️  {version} (already applied on target)[/dim]")

    if dry_run:
        console.print(
            f"\n[cyan]📊 Would copy {len(copied)} row(s); {len(skipped)} already applied.[/cyan]"
        )
        console.print("[yellow]Run without --dry-run to apply changes.[/yellow]")
    else:
        console.print(
            f"\n[green]✅ Copied {len(copied)} row(s); {len(skipped)} already applied.[/green]"
        )


ThroughOpt = Annotated[
    str | None,
    typer.Option(
        "--through",
        "-t",
        help="Mark all migrations through this version as applied.  Required "
        "unless --from-db is given.",
    ),
]
FromDbOpt = Annotated[
    str | None,
    typer.Option(
        "--from-db",
        help="Source DSN to copy tb_confiture rows from.  When set, history "
        "is copied from another database rather than marked manually.  "
        "Combined with --through, the copy is capped at the named version.",
    ),
]
SourceTableOpt = Annotated[
    str | None,
    typer.Option(
        "--source-table",
        help="Override the source DB's tracking table name when it differs "
        "from the target (default: same as target).",
    ),
]
DryRunOpt = Annotated[
    bool,
    typer.Option(
        "--dry-run", help="Show what would be marked without making changes (default: off)"
    ),
]


@cli_boundary
def migrate_baseline(
    through: ThroughOpt = None,
    from_db: FromDbOpt = None,
    source_table: SourceTableOpt = None,
    migrations_dir: Path = migrations_dir_option(),
    config: Path = config_option(),
    dry_run: DryRunOpt = False,
    format_output: str = format_option("text", "json"),
) -> None:
    """Mark migrations as applied without running them.

    PROCESS:
      Marks migrations as applied in the database without executing the SQL.
      Useful for establishing a baseline when adopting confiture on existing
      databases, setting up from backups, or recovering from failed states.

      With --from-db, copies the tracking-table rows from another database
      verbatim (preserving version, name, applied_at, execution_time_ms,
      checksum).  Use this after a pg_restore from another environment when
      tb_confiture has been lost — see Issue #119.

    EXAMPLES:
      confiture migrate baseline --through 002
        ↳ Mark migrations 001-002 as applied (manual baseline)

      confiture migrate baseline --through 005 --dry-run
        ↳ Preview what would be marked, without making changes

      confiture migrate baseline --from-db postgresql://prod-host/myapp
        ↳ Copy production's migration history into the local database

      confiture migrate baseline --from-db postgresql://prod/myapp --through 042
        ↳ Copy production's history, but stop at version 042

    RELATED:
      confiture migrate up       - Apply migrations normally
      confiture migrate status   - View migration history
      confiture migrate diff     - Compare schema versions
    """

    json_mode = is_json(format_output)
    _baseline_preconditions(through, from_db, config, migrations_dir, json_mode=json_mode)

    if from_db is not None:
        report = _baseline_from_db_flow(
            from_db=from_db,
            through=through,
            source_table=source_table,
            migrations_dir=migrations_dir,
            config=config,
            dry_run=dry_run,
        )
        if json_mode:
            emit(report)
        else:
            _print_from_db(report)
        return

    _refuse_duplicate_baseline(migrations_dir, json_mode=json_mode)
    assert through is not None  # _baseline_preconditions: --through or --from-db
    report = _mark_through(through, migrations_dir, config, dry_run=dry_run, json_mode=json_mode)
    if json_mode:
        emit(report)
    else:
        _print_marked(report)


def _baseline_preconditions(
    through: str | None, from_db: str | None, config: Path, migrations_dir: Path, *, json_mode: bool
) -> None:
    """One of --through / --from-db, a config file and a migrations directory — before any DB work."""
    if through is None and from_db is None:
        fail(
            ConfigurationError(
                "Missing required option. Pass either --through <version> or --from-db <DSN>.",
            ),
            json_mode=json_mode,
        )
    if not config.exists():
        fail(
            ConfigurationError(
                f"Config file not found: {config}",
                error_code="CONFIG_004",
                resolution_hint="Specify config with --config path/to/config.yaml.",
            ),
            json_mode=json_mode,
        )
    if not migrations_dir.exists():
        fail(
            ConfigurationError(
                f"Migrations directory not found: {migrations_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=json_mode,
        )


def _mark_through(
    through: str, migrations_dir: Path, config: Path, *, dry_run: bool, json_mode: bool
) -> dict[str, Any]:
    """Mark every migration up to and including *through* as applied; say what each became."""
    config_data = _core_connection.load_config(config)
    with open_connection(config_data) as conn:
        migrator = _core_migrator.Migrator(
            connection=conn, migration_table=_get_tracking_table(config_data)
        )
        migrator.initialize()
        all_migrations = migrator.find_migration_files(migrations_dir)
        to_mark = _migrations_through(all_migrations, through, json_mode=json_mode)
        applied_versions = set(migrator.get_applied_versions())

        migrations: list[dict[str, str]] = []
        for migration_file in to_mark:
            version, name = parse_migration_filename(migration_file.name)
            if version in applied_versions:
                status = "already_applied"
            elif dry_run:
                status = "would_mark"
            else:
                migrator.mark_applied(migration_file, reason="baseline")
                status = "marked"
            migrations.append({"version": version, "name": name, "status": status})

    skipped = sum(1 for m in migrations if m["status"] == "already_applied")
    return {
        "mode": "through",
        "through": through,
        "dry_run": dry_run,
        "migrations": migrations,
        "marked_count": len(migrations) - skipped,
        "skipped_count": skipped,
    }


def _migrations_through(all_migrations: list[Path], through: str, *, json_mode: bool) -> list[Path]:
    """The files up to and including *through*; none when there are none; else MIGR_100."""
    if not all_migrations:
        return []
    for index, migration_file in enumerate(all_migrations):
        if parse_migration_filename(migration_file.name)[0] == through:
            return all_migrations[: index + 1]
    if not json_mode:
        console.print("[yellow]Available versions:[/yellow]")
        for mf in all_migrations[:10]:
            console.print(f"  • {parse_migration_filename(mf.name)[0]}")
        if len(all_migrations) > 10:
            console.print(f"  ... and {len(all_migrations) - 10} more")
    fail(
        MigrationError(
            f"Migration version '{through}' not found",
            version=through,
            error_code="MIGR_100",
        ),
        json_mode=json_mode,
    )


_MARKS = {
    "already_applied": "[dim]⏭️  {version} {name} (already applied)[/dim]",
    "would_mark": "[cyan]📝 {version} {name} (would mark as applied)[/cyan]",
    "marked": "[green]✅ {version} {name} (marked as applied)[/green]",
}


def _print_marked(report: dict[str, Any]) -> None:
    if not report["migrations"]:
        console.print("[yellow]No migrations found.[/yellow]")
        return
    console.print(f"\n[cyan]📋 Baseline: marking migrations through {report['through']}[/cyan]\n")
    if report["dry_run"]:
        console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")
    for migration in report["migrations"]:
        console.print(f"  {_MARKS[migration['status']].format(**migration)}")

    console.print()
    marked, skipped = report["marked_count"], report["skipped_count"]
    if report["dry_run"]:
        console.print(
            f"[cyan]📊 Would mark {marked} migration(s), skip {skipped} already applied[/cyan]"
        )
        console.print("\n[yellow]Run without --dry-run to apply changes[/yellow]")
    else:
        console.print(
            f"[green]✅ Marked {marked} migration(s) as applied, "
            f"skipped {skipped} already applied[/green]"
        )


def _refuse_duplicate_baseline(migrations_dir: Path, *, json_mode: bool) -> None:
    """Duplicate migration versions are a hard block (no DB needed)."""

    duplicates = _baseline_find(migrations_dir)
    if not duplicates:
        return
    if not json_mode:
        console.print("[red]❌ Duplicate migration versions detected — refusing to proceed[/red]")
        console.print("[red]Multiple migration files share the same version number:[/red]\n")
        for version, files in sorted(duplicates.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f.name}")
        console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
        console.print("[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]")
    fail(
        MigrationError(
            "Duplicate migration versions detected — refusing to proceed.",
            error_code="MIGR_106",
        ),
        json_mode=json_mode,
    )
