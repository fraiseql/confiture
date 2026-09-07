"""``confiture migrate steps``: the online runner's checkpoints — list them, resume one."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import _get_tracking_table, _output_json, console, is_json
from confiture.cli.options import format_option
from confiture.config.environment import MigrationConfig
from confiture.core import connection as _core_connection
from confiture.core import migrator as _core_migrator
from confiture.core import step_runner
from confiture.core.backfill import BackfillSettings
from confiture.models.results import MigrateStepsResult

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to environment config file")]
MigrationsDirOpt = Annotated[
    Path, typer.Option("--migrations-dir", help="Directory containing migration files")
]
ResumeOpt = Annotated[
    str | None,
    typer.Option(
        "--resume",
        help="Continue the online migration with this version from its last checkpoint",
    ),
]
MaxLockMsOpt = Annotated[
    int | None,
    typer.Option(
        "--max-lock-ms",
        help="Pause this many ms between backfill batches while another session waits for a lock on the table (overrides migration.backfill.max_lock_ms)",
    ),
]
AllowDestructiveOpt = Annotated[
    bool,
    typer.Option(
        "--allow-destructive",
        help="Run a contract stage that drops the old column (data is lost)",
    ),
]


@cli_boundary
def migrate_steps(
    config: ConfigOpt = Path("db/environments/local.yaml"),
    migrations_dir: MigrationsDirOpt = Path("db/migrations"),
    resume: ResumeOpt = None,
    allow_destructive: AllowDestructiveOpt = False,
    max_lock_ms: MaxLockMsOpt = None,
    format_type: str = format_option("table", "json"),
    output_file: Path | None = typer.Option(None, "--output", "-o", help="Write output to file"),
) -> None:
    """List the online runner's checkpoints, or resume an online migration from them.

    An expand/contract migration records each stage in <tracking_table>_steps
    as it runs. A run that died between stages leaves its rows behind; this
    command shows them, and --resume <version> continues from the first stage
    that is not done, recording the migration in the ledger once its last
    contract stage has finished.
    """
    config_data = _core_connection.load_config(config)
    tracking = _get_tracking_table(config_data)
    with _core_migrator.MigratorSession(
        None,
        migrations_dir,
        database_url_override=_core_connection.dsn_from_config(config_data),
        migration_table_override=tracking,
        command="confiture migrate steps",
    ) as session:
        migrator = session.migrator
        store = step_runner.CheckpointStore(migrator.connection, step_runner.steps_table(tracking))
        store.ensure()
        if resume is not None:
            step_runner.resume(
                migrator,
                resume,
                migrations_dir=migrations_dir,
                allow_destructive=allow_destructive,
                settings=_backfill_settings(config_data, max_lock_ms),
            )
        result = MigrateStepsResult(
            steps=[r.to_dict() for r in store.records()],
            resumed=resume,
        )
    if is_json(format_type):
        _output_json(result.to_dict(), output_file, console)
        return
    if result.resumed:
        console.print(
            f"[green]✅ Resumed {result.resumed}: every stage done, recorded in the ledger[/green]"
        )
    if not result.steps:
        console.print("No online-migration checkpoints.")
        return
    for step in result.steps:
        console.print(
            f"  {step['migration']}  plan {step['plan_index']}  {step['stage']:<9} {step['state']:<8}"
            f"  rows {step['rows_done']}  {step['updated_at']}"
        )


def _backfill_settings(config_data: dict[str, Any], max_lock_ms: int | None) -> BackfillSettings:
    """``migration.backfill`` from the config, the flag winning for the lock-waiter guard."""
    backfill = MigrationConfig.model_validate(config_data.get("migration") or {}).backfill
    return BackfillSettings(
        batch_size=backfill.batch_size,
        max_lock_ms=max_lock_ms if max_lock_ms is not None else backfill.max_lock_ms,
    )
