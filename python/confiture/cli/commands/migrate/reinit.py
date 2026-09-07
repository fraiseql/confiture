"""`confiture migrate reinit`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console
from confiture.core import migrator as _core_migrator
from confiture.core.migrator import find_duplicate_migration_versions, parse_migration_filename
from confiture.exceptions import ConfigurationError, MigrationError


def _reinit_preconditions(config: Path, migrations_dir: Path, find_duplicates: Any) -> None:
    """Config file, migrations directory and unique versions — all checked before any DB work."""
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

    duplicates = find_duplicates(migrations_dir)
    if duplicates:
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


def _migrations_through(all_migrations: list[Path], through: str | None) -> list[Path]:
    """The files to re-mark: everything, or up to and including ``through`` (else exit 1)."""
    if through is None:
        return list(all_migrations)
    migrations_to_mark: list[Path] = []
    for migration_file in all_migrations:
        version = parse_migration_filename(migration_file.name)[0]
        migrations_to_mark.append(migration_file)
        if version == through:
            return migrations_to_mark
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
    return migrations_to_mark  # unreachable: fail() exits


def _print_reinit_plan(
    migrations_to_mark: list[Path], *, through: str | None, current_count: int
) -> None:
    target_desc = f"through {through}" if through else "all files on disk"
    console.print(
        f"\n[cyan]📋 Reinit: resetting tracking table and re-marking {target_desc}[/cyan]\n"
    )
    console.print(f"  Tracking entries to delete: [bold]{current_count}[/bold]")
    console.print(f"  Migrations to re-mark:     [bold]{len(migrations_to_mark)}[/bold]\n")

    for migration_file in migrations_to_mark:
        version, name = parse_migration_filename(migration_file.name)
        console.print(f"  [dim]•[/dim] {version} {name}")

    console.print()


@cli_boundary
def migrate_reinit(
    through: str = typer.Option(
        None,
        "--through",
        "-t",
        help="Mark migrations as applied through this version (default: all files on disk)",
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
        help="Show what would happen without making changes (default: off)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Reset tracking table and re-baseline from migration files on disk.

    PROCESS:
      Deletes all entries from tb_confiture, then re-marks migration files
      as applied. Used after consolidating migration files to establish a
      clean tracking state that matches the files on disk.

    EXAMPLES:
      confiture migrate reinit --through 003
        ↳ Clear tracking table and re-mark migrations 001-003

      confiture migrate reinit
        ↳ Clear tracking table and re-mark ALL migration files on disk

      confiture migrate reinit --through 005 --dry-run
        ↳ Preview what would happen without making changes

      confiture migrate reinit -t 003 -y
        ↳ Skip confirmation prompt

    RELATED:
      confiture migrate baseline  - Mark migrations as applied (without clearing)
      confiture migrate up        - Apply migrations normally
      confiture migrate status    - View migration history
    """

    _reinit_preconditions(config, migrations_dir, find_duplicate_migration_versions)

    with _core_migrator.Migrator.from_config(config, migrations_dir=migrations_dir) as m:
        migrator = m.migrator
        migrator.initialize()

        all_migrations = migrator.find_migration_files(migrations_dir)
        if not all_migrations:
            console.print("[yellow]No migrations found.[/yellow]")
            return

        migrations_to_mark = _migrations_through(all_migrations, through)
        current_count = len(migrator.get_applied_versions())
        _print_reinit_plan(migrations_to_mark, through=through, current_count=current_count)

        if dry_run:
            console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

        if not yes and not dry_run:
            # The resolved name, not the default (#190). This is a
            # destructive confirmation: naming the wrong table here is the
            # one place a wrong name could get an operator to approve the
            # wrong action.
            confirmed = typer.confirm(
                f"Will delete {current_count} entries from {migrator.migration_table} "
                f"and re-mark {len(migrations_to_mark)} migrations. Continue?"
            )
            if not confirmed:
                console.print("[dim]Aborted.[/dim]")
                return

        result = m.reinit(through=through, dry_run=dry_run)

        if dry_run:
            console.print(
                f"[cyan]📊 Would delete {result.deleted_count} tracking entries "
                f"and re-mark {len(result.migrations_marked)} migration(s)[/cyan]"
            )
            console.print("\n[yellow]Run without --dry-run to apply changes[/yellow]")
        else:
            console.print(
                f"[green]✅ Reinit complete: deleted {result.deleted_count} entries, "
                f"re-marked {len(result.migrations_marked)} migration(s)[/green]"
            )
