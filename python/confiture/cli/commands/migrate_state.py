"""Migration state commands: migrate baseline, reinit, rebuild."""

from pathlib import Path

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import console, is_json
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
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator

    config_data = load_config(config)
    conn = create_connection(config_data)

    try:
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
    finally:
        conn.close()


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
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator

    try:
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
            fail(
                MigrationError(
                    "Duplicate migration versions detected — refusing to proceed.",
                    error_code="MIGR_106",
                ),
                json_mode=False,
            )

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
            console.print("[yellow]Available versions:[/yellow]")
            for mf in all_migrations[:10]:
                v = migrator._version_from_filename(mf.name)
                console.print(f"  • {v}")
            if len(all_migrations) > 10:
                console.print(f"  ... and {len(all_migrations) - 10} more")
            conn.close()
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
        fail(e, json_mode=False)


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

    duplicates = find_duplicate_migration_versions(migrations_dir)
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
                    console.print("[yellow]Available versions:[/yellow]")
                    for mf in all_migrations[:10]:
                        v = migrator._version_from_filename(mf.name)
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
        fail(e, json_mode=False)


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

    json_mode = is_json(format_output)

    # Pre-flight: validate config
    if not config.exists():
        fail(
            ConfigurationError(
                f"Config file not found: {config}",
                error_code="CONFIG_004",
                resolution_hint="Specify config with --config path/to/config.yaml.",
            ),
            json_mode=json_mode,
        )

    # Pre-flight: validate migrations dir
    if not migrations_dir.exists():
        fail(
            ConfigurationError(
                f"Migrations directory not found: {migrations_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=json_mode,
        )

    # Pre-flight: validate format
    if format_output not in ("text", "json"):
        fail(
            ConfigurationError(
                f"Invalid format '{format_output}'. Use 'text' or 'json'.",
                resolution_hint="Pass --format text or --format json.",
            ),
            json_mode=False,
        )

    # Pre-flight: check for duplicate versions
    duplicates = find_duplicate_migration_versions(migrations_dir)
    if duplicates:
        for version, files in sorted(duplicates.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f.name}")
        fail(
            MigrationError(
                "Duplicate migration versions detected — refusing to proceed.",
                error_code="MIGR_106",
            ),
            json_mode=json_mode,
        )

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
        # Rebuild fatal errors (connection, build, DDL) stay in the migrate
        # family at exit 3; in --format json the unified envelope is emitted.
        fail(
            MigrationError(f"Rebuild failed: {e}", error_code="MIGR_001"),
            json_mode=json_mode,
        )
