"""`confiture migrate rebuild`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

import json as json_module
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.migrate_formatter import format_rebuild_result
from confiture.cli.helpers import console, is_json
from confiture.cli.options import format_option
from confiture.core import migrator as _core_migrator
from confiture.core.migrator import find_duplicate_migration_versions
from confiture.exceptions import ConfigurationError, MigrationError

ConfigOpt = Annotated[
    Path,
    typer.Option("--config", "-c", help="Configuration file (default: db/environments/local.yaml)"),
]
MigrationsDirOpt = Annotated[
    Path, typer.Option("--migrations-dir", help="Migrations directory (default: db/migrations)")
]
DropSchemasOpt = Annotated[
    bool, typer.Option("--drop-schemas", help="Drop all user schemas before rebuild")
]
SeedOpt = Annotated[bool, typer.Option("--seed", help="Apply seed files after DDL rebuild")]
BackupTrackingOpt = Annotated[
    bool, typer.Option("--backup-tracking", help="Dump tracking table to JSON before clearing")
]
VerifyOpt = Annotated[
    bool, typer.Option("--verify", help="Run status check after rebuild to confirm 0 pending")
]
DryRunOpt = Annotated[
    bool, typer.Option("--dry-run", help="Show what would happen without making changes")
]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")]


def _rebuild_preconditions(
    config: Path, migrations_dir: Path, find_duplicates: Any, json_mode: bool
) -> None:
    """Config file, migrations directory and unique versions — checked before any DB work."""
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

    duplicates = find_duplicates(migrations_dir)
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


def _write_tracking_backup(rows: Any, tracking_table: str, format_output: str) -> None:
    """Dump the ledger rows next to the cwd, named after the table they came from (#190)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # A file called tb_confiture_backup_*.json containing audit.tb_migrations
    # rows is actively misleading during a restore. "." is not portable in a
    # filename component, so a qualified name is flattened.
    ledger_name = tracking_table.replace(".", "_")
    backup_path = Path(f"{ledger_name}_backup_{timestamp}.json")
    backup_path.write_text(json_module.dumps(rows, indent=2, default=str))
    if format_output == "text":
        console.print(f"[cyan]📦 Tracking table backed up to {backup_path}[/cyan]\n")


@cli_boundary
def migrate_rebuild(
    config: ConfigOpt = Path("db/environments/local.yaml"),
    migrations_dir: MigrationsDirOpt = Path("db/migrations"),
    drop_schemas: DropSchemasOpt = False,
    seed: SeedOpt = False,
    backup_tracking: BackupTrackingOpt = False,
    verify: VerifyOpt = False,
    dry_run: DryRunOpt = False,
    yes: YesOpt = False,
    format_output: str = format_option("text", "json"),
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

    json_mode = is_json(format_output)

    _rebuild_preconditions(config, migrations_dir, find_duplicate_migration_versions, json_mode)

    try:
        with _core_migrator.Migrator.from_config(config, migrations_dir=migrations_dir) as m:
            # Backup tracking table before rebuild if requested
            tracking_backup_data = None
            tracking_backup_table = "tb_confiture"
            if backup_tracking and not dry_run:
                migrator = m.migrator
                tracking_backup_data = migrator.backup_tracking_table()
                # Captured here, where the resolved name is in hand (#190).
                tracking_backup_table = migrator.migration_table

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

            if tracking_backup_data is not None:
                _write_tracking_backup(tracking_backup_data, tracking_backup_table, format_output)

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
    # Reason: documented: rebuild failures of any kind stay in the migrate family at exit 3
    except Exception as e:
        # Rebuild fatal errors (connection, build, DDL) stay in the migrate
        # family at exit 3; in --format json the unified envelope is emitted.
        fail(
            MigrationError(f"Rebuild failed: {e}", error_code="MIGR_001"),
            json_mode=json_mode,
        )
