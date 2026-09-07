"""`confiture migrate baseline`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console, open_connection
from confiture.core.migrator import parse_migration_filename
from confiture.exceptions import ConfigurationError, MigrationError


def _baseline_from_db_flow(
    *,
    from_db: str,
    through: str | None,
    source_table: str | None,
    migrations_dir: Path,
    config: Path,
    dry_run: bool,
) -> None:
    """Drive the ``--from-db`` copy path.

    Connects to the target database via the standard config flow,
    delegates to :meth:`Migrator.baseline_from_db`, and renders the
    resulting report to the operator.  Issue #119.
    """
    from confiture.cli.helpers import _get_tracking_table
    from confiture.core.connection import load_config
    from confiture.core.migrator import Migrator

    config_data = load_config(config)
    with open_connection(config_data) as conn:
        migrator = Migrator(
            connection=conn,
            migration_table=_get_tracking_table(config_data),
        )
        migrator.initialize()

        if through is not None:
            console.print(
                "[yellow]⚠️  --through with --from-db caps the copy at "
                f"version {through!r}; source rows above the cap will be "
                "skipped.[/yellow]"
            )

        report = migrator.baseline_from_db(
            source_dsn=from_db,
            migrations_dir=migrations_dir,
            through=through,
            dry_run=dry_run,
            source_table=source_table,
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
            console.print(f"\n[cyan]📋 Baseline from {from_db}[/cyan]\n")
            for row in copied:
                marker = "would copy" if dry_run else "copied"
                console.print(f"  [green]✅ {row['version']} {row['name']} ({marker})[/green]")
            for version in skipped:
                console.print(f"  [dim]⏭️  {version} (already applied on target)[/dim]")

        if dry_run:
            console.print(
                f"\n[cyan]📊 Would copy {len(copied)} row(s); "
                f"{len(skipped)} already applied.[/cyan]"
            )
            console.print("[yellow]Run without --dry-run to apply changes.[/yellow]")
        else:
            console.print(
                f"\n[green]✅ Copied {len(copied)} row(s); {len(skipped)} already applied.[/green]"
            )


@cli_boundary
def migrate_baseline(
    through: str = typer.Option(
        None,
        "--through",
        "-t",
        help=(
            "Mark all migrations through this version as applied.  Required "
            "unless --from-db is given."
        ),
    ),
    from_db: str = typer.Option(
        None,
        "--from-db",
        help=(
            "Source DSN to copy tb_confiture rows from.  When set, history "
            "is copied from another database rather than marked manually.  "
            "Combined with --through, the copy is capped at the named version."
        ),
    ),
    source_table: str = typer.Option(
        None,
        "--source-table",
        help=(
            "Override the source DB's tracking table name when it differs "
            "from the target (default: same as target)."
        ),
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be marked without making changes (default: off)",
    ),
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
    from confiture.cli.helpers import _get_tracking_table
    from confiture.core.connection import load_config
    from confiture.core.migrator import Migrator

    if through is None and from_db is None:
        fail(
            ConfigurationError(
                "Missing required option. Pass either --through <version> or --from-db <DSN>.",
            ),
            json_mode=False,
        )

    if not config.exists():
        fail(
            ConfigurationError(
                f"Config file not found: {config}",
                error_code="CONFIG_004",
                resolution_hint="Specify config with --config path/to/config.yaml.",
            ),
            json_mode=False,
        )

    if not migrations_dir.exists():
        fail(
            ConfigurationError(
                f"Migrations directory not found: {migrations_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=False,
        )

    if from_db is not None:
        _baseline_from_db_flow(
            from_db=from_db,
            through=through,
            source_table=source_table,
            migrations_dir=migrations_dir,
            config=config,
            dry_run=dry_run,
        )
        return

    _refuse_duplicate_baseline(migrations_dir)

    # Load config and create connection
    config_data = load_config(config)
    with open_connection(config_data) as conn:
        migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))
        migrator.initialize()

        # Find all migration files
        all_migrations = migrator.find_migration_files(migrations_dir)

        if not all_migrations:
            console.print("[yellow]No migrations found.[/yellow]")
            return

        # Filter migrations up to and including the target version
        migrations_to_mark: list[Path] = []
        for migration_file in all_migrations:
            version = parse_migration_filename(migration_file.name)[0]
            migrations_to_mark.append(migration_file)
            if version == through:
                break
        else:
            # Target version not found
            console.print("[yellow]Available versions:[/yellow]")
            for mf in all_migrations[:10]:
                v = parse_migration_filename(mf.name)[0]
                console.print(f"  • {v}")
            if len(all_migrations) > 10:
                console.print(f"  ... and {len(all_migrations) - 10} more")
            fail(
                MigrationError(
                    f"Migration version '{through}' not found",
                    version=through,
                    error_code="MIGR_100",
                ),
                json_mode=False,
            )

        # Get already applied versions
        applied_versions = set(migrator.get_applied_versions())

        # Show what will be done
        console.print(f"\n[cyan]📋 Baseline: marking migrations through {through}[/cyan]\n")

        if dry_run:
            console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

        marked_count = 0
        skipped_count = 0

        for migration_file in migrations_to_mark:
            version = parse_migration_filename(migration_file.name)[0]
            # Extract name
            _, name = parse_migration_filename(migration_file.name)

            if version in applied_versions:
                console.print(f"  [dim]⏭️  {version} {name} (already applied)[/dim]")
                skipped_count += 1
            else:
                if dry_run:
                    console.print(f"  [cyan]📝 {version} {name} (would mark as applied)[/cyan]")
                else:
                    migrator.mark_applied(migration_file, reason="baseline")
                    console.print(f"  [green]✅ {version} {name} (marked as applied)[/green]")
                marked_count += 1

        # Summary
        console.print()
        if dry_run:
            console.print(
                f"[cyan]📊 Would mark {marked_count} migration(s), "
                f"skip {skipped_count} already applied[/cyan]"
            )
            console.print("\n[yellow]Run without --dry-run to apply changes[/yellow]")
        else:
            console.print(
                f"[green]✅ Marked {marked_count} migration(s) as applied, "
                f"skipped {skipped_count} already applied[/green]"
            )


def _refuse_duplicate_baseline(migrations_dir: Path) -> None:
    """Duplicate migration versions are a hard block (no DB needed)."""
    from confiture.core.migrator import find_duplicate_migration_versions as _baseline_find

    duplicates = _baseline_find(migrations_dir)
    if not duplicates:
        return
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
        json_mode=False,
    )
