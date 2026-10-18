"""``confiture seed drift``: compare the seeded rows of a seed-built database with a live one (#743)."""

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.formatters.seed_drift_formatter import print_report
from confiture.cli.helpers import console, emit, is_json
from confiture.cli.options import env_option, format_option, output_option, scratch_url_option
from confiture.core.seed.drift import SeedDriftReport, run, scope_for
from confiture.error_codes import FINDINGS, NOT_RUN, SUCCESS
from confiture.exceptions import ConfigurationError


def exit_code(report: SeedDriftReport) -> int:
    """1 for a difference nothing explains, else 2 when a table was not compared, else 0."""
    if report.has_drift:
        return FINDINGS
    return SUCCESS if report.complete else NOT_RUN


@cli_boundary
def drift(
    env: str = env_option(
        help="The seed-built environment: its schema tree, its seed files and its "
        "seed_drift settings (default: local)"
    ),
    against: str | None = typer.Option(
        None,
        "--against",
        help="The live database to compare with: an environment name (its ssh_tunnel is "
        "used) or a PostgreSQL URL. Read in a read-only transaction; nothing is written",
    ),
    build: bool = typer.Option(
        False,
        "--build",
        help="Build the seed side from the tree and its seeds on a scratch server instead "
        "of reading --env's database, so the comparison is the tree's, not that "
        "database's history",
    ),
    scratch_url: str | None = scratch_url_option(
        help="With --build: the writable server the seed side is built on (default: the "
        "environment's scratch_url; never its database_url)"
    ),
    seeds_dir: Path | None = typer.Option(
        None,
        "--seeds-dir",
        help="A directory `confiture seed apply` applies: its files count as seeds, after the "
        "seed files in the environment's include_dirs",
    ),
    list_scope: bool = typer.Option(
        False,
        "--list-scope",
        help="Print what would be compared (tables, keys, columns) and stop; reads no database",
    ),
    format_output: str = format_option("table", "json"),
    output_file: Path | None = output_option(help="Write the JSON report to this file"),
) -> None:
    """Compare the reference rows the seed tree writes with what a live database holds.

    A rebuilt environment gets its reference rows from the seed tree; a
    migrate-only one gets only the rows a migration inserts. Every table the seed
    tree writes is compared, matched by a key the seed itself writes: rows only
    the seed side holds, rows only the live side holds, and rows whose columns
    differ. Exit 0: no difference nothing explains; 1: drift; 2: a table could not
    be compared; 3: a database did not answer.
    """
    if list_scope:
        report = scope_for(env, seeds_dir=seeds_dir, build=build)
    elif against is None:
        raise ConfigurationError(
            "seed drift needs --against: the live database to compare with",
            error_code="CONFIG_001",
            resolution_hint="Pass --against <environment or URL>, or --list-scope",
        )
    else:
        report = run(env, against, seeds_dir=seeds_dir, build=build, scratch_url=scratch_url)
    if is_json(format_output):
        emit(report.to_dict(), output_file)
    else:
        print_report(report, console)
    raise typer.Exit(exit_code(report))
