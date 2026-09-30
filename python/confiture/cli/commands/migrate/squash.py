"""`confiture migrate squash` and `confiture migrate squash-ledger`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import _get_tracking_table, console, emit, is_json
from confiture.cli.markup import verbatim
from confiture.cli.options import config_option, format_option, migrations_dir_option
from confiture.config.environment import Environment
from confiture.core import connection as _core_connection
from confiture.core import migrator as _core_migrator
from confiture.core.builder import SchemaBuilder
from confiture.core.squash import (
    EnvironmentCheck,
    SquashPlan,
    SquashResult,
    check_environments,
    execute_squash,
    plan_squash,
    squashed_versions,
)
from confiture.exceptions import ConfigurationError

ThroughOpt = Annotated[
    str,
    typer.Option("--through", "-t", help="The last migration version to squash."),
]
FromBuildOpt = Annotated[
    bool,
    typer.Option(
        "--from-build",
        help="Write the tree `confiture build` produces instead of a dump, once a drift "
        "check shows it is the schema the squashed migrations build (default: off).",
    ),
]
VersionOpt = Annotated[
    str | None,
    typer.Option(
        "--version",
        help="The baseline's version, when the one after --through is taken. It must sort "
        "after --through and before every later migration.",
    ),
]
DeleteOpt = Annotated[
    bool,
    typer.Option(
        "--delete",
        help="Delete the squashed files instead of moving them to <migrations-dir>/archive/.",
    ),
]
DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Show the plan and write nothing (default: off)."),
]


@cli_boundary
def migrate_squash(
    through: ThroughOpt,
    from_build: FromBuildOpt = False,
    version: VersionOpt = None,
    delete: DeleteOpt = False,
    migrations_dir: Path = migrations_dir_option(),
    config: Path = config_option(),
    dry_run: DryRunOpt = False,
    format_output: str = format_option("text", "json"),
) -> None:
    """Replace every migration through a version with one baseline.

    PROCESS:
      Run it in the repository, with a local --config: its database_url's server
      holds the scratch database, and --from-build builds its environment.
      First it asks every db/environments/*.yaml: each must have applied every
      squashed migration, the cut at least squash.min_age_days ago (db/project.yaml,
      default 90), and finished any online migration up to it (VALID_009).
      squash.skip_environments lists those it cannot reach.
      Replays the migrations up to --through into a scratch database and dumps
      its schema (without confiture's own tables) as one migration, the
      baseline, whose SQL is embedded. The squashed files move to
      <migrations-dir>/archive/. Each database then meets the baseline in
      `migrate up`: a fresh one applies it; one that applied every squashed
      migration records it without running it, and keeps their ledger rows,
      marked archived_into; any other is refused (VALID_008).

    EXAMPLES:
      confiture migrate squash --through 20260101000000 --dry-run
        ↳ Show what would be archived and the baseline's SQL source

      confiture migrate squash --through 20260101000000 --from-build
        ↳ Use the tree as the baseline, once it is proven to be that schema

    RELATED:
      confiture migrate squash-ledger  - Record a baseline without applying anything else
      confiture migrate up             - Applies, or records, the baseline
    """
    json_mode = is_json(format_output)
    if not config.exists():
        fail(
            ConfigurationError(f"Config file not found: {config}", error_code="CONFIG_004"),
            json_mode=json_mode,
        )
    config_data = _core_connection.load_config(config)
    checked = check_environments(Path(), squashed_versions(migrations_dir, through), through)
    build_sql = (
        SchemaBuilder(env=Environment.model_validate(config_data)).build(schema_only=True)
        if from_build
        else None
    )
    plan = plan_squash(
        migrations_dir,
        through,
        server_url=_core_connection.dsn_from_config(config_data),
        version=version,
        build_sql=build_sql,
        migration_table=_get_tracking_table(config_data),
    )
    result = None if dry_run else execute_squash(plan, migrations_dir, delete=delete)
    if json_mode:
        emit(_squash_payload(plan, result, migrations_dir, checked, delete=delete))
    else:
        _print_squash(plan, result, migrations_dir, checked, delete=delete)


def _squash_payload(
    plan: SquashPlan,
    result: SquashResult | None,
    migrations_dir: Path,
    checked: list[EnvironmentCheck],
    *,
    delete: bool,
) -> dict[str, Any]:
    return {
        "environments": [{"name": c.name, "skipped": c.skipped} for c in checked],
        "through": plan.through,
        "versions": list(plan.versions),
        "baseline": str(migrations_dir / plan.baseline_name),
        "version": plan.version,
        "source": plan.source,
        "digest": plan.digest,
        "archived": [str(path) for path in plan.archived],
        "deleted": delete,
        "dry_run": result is None,
    }


def _print_squash(
    plan: SquashPlan,
    result: SquashResult | None,
    migrations_dir: Path,
    checked: list[EnvironmentCheck],
    *,
    delete: bool,
) -> None:
    dry = result is None
    for check in checked:
        state = "skipped (squash.skip_environments)" if check.skipped else "ready"
        console.print(f"[dim]environment {verbatim(check.name)}: {verbatim(state)}[/dim]")
    verb = "Would squash" if dry else "Squashed"
    console.print(
        f"[cyan]📚 {verbatim(verb)} {len(plan.versions)} migration(s) through {verbatim(plan.through)} "
        f"into {verbatim(migrations_dir / plan.baseline_name)} "
        f"(from the {verbatim(plan.source)})[/cyan]"
    )
    fate = ("would be " if dry else "") + ("deleted" if delete else "moved to archive/")
    for path in plan.archived:
        console.print(f"  [dim]{verbatim(path.name)}: {verbatim(fate)}[/dim]")
    if dry:
        console.print("[yellow]Dry run: nothing was written.[/yellow]")
    else:
        console.print(
            "[green]✅ Run `confiture migrate up` (or `migrate squash-ledger`) on each "
            "database: one that applied these migrations records the baseline without "
            "running it.[/green]"
        )


@cli_boundary
def migrate_squash_ledger(
    migrations_dir: Path = migrations_dir_option(),
    config: Path = config_option(),
    dry_run: DryRunOpt = False,
    format_output: str = format_option("text", "json"),
) -> None:
    """Record a pending squashed baseline on a database that applied what it squashed.

    PROCESS:
      What `migrate up` does first, run alone: a pending baseline whose squashed
      migrations this database's ledger holds, with the checksums the baseline
      was made from, is recorded without running, and their rows are marked
      archived_into. Nothing else is applied. A database that holds part of the
      history is refused (VALID_008).

    EXAMPLES:
      confiture migrate squash-ledger --config db/environments/production.yaml
    """
    json_mode = is_json(format_output)
    if not config.exists():
        fail(
            ConfigurationError(f"Config file not found: {config}", error_code="CONFIG_004"),
            json_mode=json_mode,
        )
    config_data = _core_connection.load_config(config)
    with _core_migrator.MigratorSession(
        None,
        migrations_dir,
        database_url_override=_core_connection.dsn_from_config(config_data),
        migration_table_override=_get_tracking_table(config_data),
        command="confiture migrate squash-ledger",
    ) as session:
        recorded = session.record_squashed_baselines(dry_run=dry_run)
    if json_mode:
        emit({"recorded": recorded, "dry_run": dry_run})
        return
    if not recorded:
        console.print("[green]✅ No squashed baseline to record[/green]")
    for version in recorded:
        verb = "Would record" if dry_run else "Recorded"
        console.print(f"[green]📚 {verbatim(verb)} {verbatim(version)} without running it[/green]")
