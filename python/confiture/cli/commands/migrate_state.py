"""Migration state commands: migrate baseline, reinit, rebuild."""

from pathlib import Path

import typer

from confiture.cli.helpers import console, error_console


def migrate_baseline(
    through: str = typer.Option(
        ...,
        "--through",
        "-t",
        help="Mark all migrations through this version as applied (required)",
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

    EXAMPLES:
      confiture migrate baseline --through 002
        ↳ Mark migrations 001-002 as applied

      confiture migrate baseline --through 005 --dry-run
        ↳ Preview what would be marked, without making changes

      confiture migrate baseline -t 003 -c db/environments/production.yaml
        ↳ Mark through version 003 in production database

      confiture migrate baseline -t 010 --force
        ↳ Force marking without state checks

    RELATED:
      confiture migrate up       - Apply migrations normally
      confiture migrate status   - View migration history
      confiture migrate diff     - Compare schema versions
    """
    from confiture.cli.helpers import _get_tracking_table
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator

    try:
        if not config.exists():
            console.print(f"[red]❌ Config file not found: {config}[/red]")
            console.print(
                "[yellow]💡 Tip: Specify config with --config path/to/config.yaml[/yellow]"
            )
            raise typer.Exit(1)

        if not migrations_dir.exists():
            console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
            raise typer.Exit(1)

        # Check for duplicate migration versions (hard block, no DB needed)
        from confiture.core.migrator import find_duplicate_migration_versions as _baseline_find

        _baseline_duplicates = _baseline_find(migrations_dir)
        if _baseline_duplicates:
            console.print(
                "[red]❌ Duplicate migration versions detected — refusing to proceed[/red]"
            )
            console.print("[red]Multiple migration files share the same version number:[/red]\n")
            for version, files in sorted(_baseline_duplicates.items()):
                console.print(f"  Version {version}:")
                for f in files:
                    console.print(f"    • {f.name}")
            console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
            console.print(
                "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
            )
            raise typer.Exit(3)

        # Load config and create connection
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Initialize migrator
        migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))
        migrator.initialize()

        # Find all migration files
        all_migrations = migrator.find_migration_files(migrations_dir)

        if not all_migrations:
            console.print("[yellow]No migrations found.[/yellow]")
            conn.close()
            return

        # Filter migrations up to and including the target version
        migrations_to_mark: list[Path] = []
        for migration_file in all_migrations:
            version = migrator._version_from_filename(migration_file.name)
            migrations_to_mark.append(migration_file)
            if version == through:
                break
        else:
            # Target version not found
            console.print(f"[red]❌ Migration version '{through}' not found[/red]")
            console.print("[yellow]Available versions:[/yellow]")
            for mf in all_migrations[:10]:
                v = migrator._version_from_filename(mf.name)
                console.print(f"  • {v}")
            if len(all_migrations) > 10:
                console.print(f"  ... and {len(all_migrations) - 10} more")
            conn.close()
            raise typer.Exit(1)

        # Get already applied versions
        applied_versions = set(migrator.get_applied_versions())

        # Show what will be done
        console.print(f"\n[cyan]📋 Baseline: marking migrations through {through}[/cyan]\n")

        if dry_run:
            console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

        marked_count = 0
        skipped_count = 0

        for migration_file in migrations_to_mark:
            version = migrator._version_from_filename(migration_file.name)
            # Extract name
            base_name = migration_file.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]
            parts = base_name.split("_", 1)
            name = parts[1] if len(parts) > 1 else base_name

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

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


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
    from confiture.core.migrator import Migrator, find_duplicate_migration_versions

    # Pre-flight validations (no DB needed)
    if not config.exists():
        console.print(f"[red]❌ Config file not found: {config}[/red]")
        console.print("[yellow]💡 Tip: Specify config with --config path/to/config.yaml[/yellow]")
        raise typer.Exit(1)

    if not migrations_dir.exists():
        console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
        raise typer.Exit(1)

    duplicates = find_duplicate_migration_versions(migrations_dir)
    if duplicates:
        console.print("[red]❌ Duplicate migration versions detected — refusing to proceed[/red]")
        console.print("[red]Multiple migration files share the same version number:[/red]\n")
        for version, files in sorted(duplicates.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f.name}")
        console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
        console.print("[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]")
        raise typer.Exit(3)

    try:
        with Migrator.from_config(config, migrations_dir=migrations_dir) as m:
            migrator = m._migrator
            assert migrator is not None
            migrator.initialize()

            all_migrations = migrator.find_migration_files(migrations_dir)
            if not all_migrations:
                console.print("[yellow]No migrations found.[/yellow]")
                return

            # Determine which migrations will be marked
            if through is not None:
                migrations_to_mark: list[Path] = []
                for migration_file in all_migrations:
                    version = migrator._version_from_filename(migration_file.name)
                    migrations_to_mark.append(migration_file)
                    if version == through:
                        break
                else:
                    console.print(f"[red]❌ Migration version '{through}' not found[/red]")
                    console.print("[yellow]Available versions:[/yellow]")
                    for mf in all_migrations[:10]:
                        v = migrator._version_from_filename(mf.name)
                        console.print(f"  • {v}")
                    if len(all_migrations) > 10:
                        console.print(f"  ... and {len(all_migrations) - 10} more")
                    raise typer.Exit(1)
            else:
                migrations_to_mark = list(all_migrations)

            current_count = len(migrator.get_applied_versions())
            target_desc = f"through {through}" if through else "all files on disk"
            console.print(
                f"\n[cyan]📋 Reinit: resetting tracking table and re-marking {target_desc}[/cyan]\n"
            )
            console.print(f"  Tracking entries to delete: [bold]{current_count}[/bold]")
            console.print(f"  Migrations to re-mark:     [bold]{len(migrations_to_mark)}[/bold]\n")

            for migration_file in migrations_to_mark:
                version = migrator._version_from_filename(migration_file.name)
                base_name = migration_file.stem
                if base_name.endswith(".up"):
                    base_name = base_name[:-3]
                parts = base_name.split("_", 1)
                name = parts[1] if len(parts) > 1 else base_name
                console.print(f"  [dim]•[/dim] {version} {name}")

            console.print()

            if dry_run:
                console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

            if not yes and not dry_run:
                confirmed = typer.confirm(
                    f"Will delete {current_count} entries from tb_confiture "
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

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def migrate_rebuild(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    drop_schemas: bool = typer.Option(
        False,
        "--drop-schemas",
        help="Drop all user schemas before rebuild",
    ),
    seed: bool = typer.Option(
        False,
        "--seed",
        help="Apply seed files after DDL rebuild",
    ),
    backup_tracking: bool = typer.Option(
        False,
        "--backup-tracking",
        help="Dump tracking table to JSON before clearing",
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Run status check after rebuild to confirm 0 pending",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would happen without making changes",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
) -> None:
    """Rebuild database from DDL schema and bootstrap tracking table.

    PROCESS:
      Drops all user schemas (if --drop-schemas), applies DDL from
      db/schema/ via SchemaBuilder, creates tracking table, and marks
      all migration files as applied. Optionally applies seeds.

    USE CASE:
      When staging/QA environments restored from production backups have
      large migration gaps (10+ pending), migrate up often fails due to
      lock exhaustion or cumulative DDL complexity. Rebuild automates the
      manual workaround of: build DDL → psql -f → hand-insert tracking rows.

    EXAMPLES:
      confiture migrate rebuild --drop-schemas --yes
        ↳ Drop all schemas, rebuild from DDL, bootstrap tracking

      confiture migrate rebuild --dry-run
        ↳ Preview what would happen without making changes

      confiture migrate rebuild --drop-schemas --seed --verify --yes
        ↳ Full rebuild with seeds and post-rebuild verification

      confiture migrate rebuild --backup-tracking --drop-schemas --yes
        ↳ Dump tracking table before rebuild (creates JSON backup file)

    RELATED:
      confiture migrate reinit  - Reset tracking table without rebuilding schema
      confiture migrate up      - Apply migrations incrementally
      confiture migrate status  - View migration history
    """
    import json as json_module
    from datetime import datetime

    from confiture.cli.formatters.migrate_formatter import format_rebuild_result
    from confiture.core.migrator import Migrator, find_duplicate_migration_versions

    fatal_error_exit = False

    # Pre-flight: validate config
    if not config.exists():
        console.print(f"[red]❌ Config file not found: {config}[/red]")
        console.print("[yellow]💡 Tip: Specify config with --config path/to/config.yaml[/yellow]")
        raise typer.Exit(1)

    # Pre-flight: validate migrations dir
    if not migrations_dir.exists():
        console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
        raise typer.Exit(1)

    # Pre-flight: validate format
    if format_output not in ("text", "json"):
        error_console.print(
            f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
        )
        raise typer.Exit(1)

    # Pre-flight: check for duplicate versions
    duplicates = find_duplicate_migration_versions(migrations_dir)
    if duplicates:
        console.print("[red]❌ Duplicate migration versions detected — refusing to proceed[/red]")
        for version, files in sorted(duplicates.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f.name}")
        raise typer.Exit(3)

    try:
        with Migrator.from_config(config, migrations_dir=migrations_dir) as m:
            # Backup tracking table before rebuild if requested
            tracking_backup_data = None
            if backup_tracking and not dry_run:
                migrator = m._migrator
                assert migrator is not None
                tracking_backup_data = migrator._backup_tracking_table()

            # Confirmation prompt
            if not yes and not dry_run:
                action = "DROP all user schemas and rebuild" if drop_schemas else "Rebuild"
                confirmed = typer.confirm(
                    f"{action} database from DDL schema? This will reset the tracking table."
                )
                if not confirmed:
                    console.print("[dim]Aborted.[/dim]")
                    return

            if dry_run and format_output == "text":
                console.print("[yellow]🔍 DRY RUN — no changes will be made[/yellow]\n")

            # Execute rebuild
            result = m.rebuild(
                drop_schemas=drop_schemas,
                dry_run=dry_run,
                apply_seeds=seed,
                backup_tracking=False,  # already handled above
            )

            # Write tracking backup to file
            if tracking_backup_data is not None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = Path(f"tb_confiture_backup_{timestamp}.json")
                backup_path.write_text(
                    json_module.dumps(tracking_backup_data, indent=2, default=str)
                )
                if format_output == "text":
                    console.print(f"[cyan]📦 Tracking table backed up to {backup_path}[/cyan]\n")

            # Post-rebuild verification
            if verify and not dry_run:
                status = m.status()
                result.verified = not status.has_pending
                if status.has_pending and format_output == "text":
                    console.print(
                        f"[yellow]⚠️  Verification: {len(status.pending)} pending migration(s) found[/yellow]"
                    )

            # Output result
            format_rebuild_result(result, format_output, None, console)

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "text":
            error_console.print(f"[red]❌ Fatal error: {e}[/red]")
        fatal_error_exit = True

    if fatal_error_exit:
        raise typer.Exit(3)
