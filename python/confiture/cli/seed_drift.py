"""``confiture seed drift``: compare the seeded rows of a seed-built database with a live one (#743)."""

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.formatters.seed_drift_formatter import print_report
from confiture.cli.helpers import console, emit, is_json
from confiture.cli.options import env_option, format_option, output_option, scratch_url_option
from confiture.core.seed.drift import SeedDriftReport, run, scope_for
from confiture.error_codes import FINDINGS, NOT_RUN, SUCCESS


def exit_code(report: SeedDriftReport) -> int:
    """2 when a table in scope was not compared, else 1 for drift, else 0.

    ``NOT_RUN`` wins over ``FINDINGS``, as the registry says: an incomplete
    comparison is not a clean one, whatever it found.
    """
    if not report.complete:
        return NOT_RUN
    return FINDINGS if report.has_drift else SUCCESS


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
    output_file: Path | None = output_option(
        help="Write the JSON report to this file (whatever --format prints)"
    ),
) -> None:
    """Compare the reference rows the seed tree writes with what a live database holds.

    A rebuilt environment gets its reference rows from the seed tree; a
    migrate-only one gets only the rows a migration inserts. Every table the seed
    tree writes is compared, matched by a key the seed itself writes: rows only
    the seed side holds, rows only the live side holds, and rows whose columns
    differ. Exit 0: no difference nothing explains; 1: drift, or a seed_drift entry
    that matches nothing; 2: a table could not be compared (this wins over 1); 3: a
    database did not answer; 5: configuration (no scratch server for --build, an
    unknown environment). Guide: docs/guides/seed-drift.md.
    """
    if list_scope:
        report = scope_for(env, seeds_dir=seeds_dir, build=build)
    elif against is None:
        raise typer.BadParameter(
            "the live database to compare with: an environment name or a PostgreSQL URL "
            "(or --list-scope, to see what would be compared without a database)",
            param_hint="--against",
        )
    else:
        report = run(env, against, seeds_dir=seeds_dir, build=build, scratch_url=scratch_url)
    if output_file is not None:
        emit(report.to_dict(), output_file)
    if is_json(format_output):
        if output_file is None:
            emit(report.to_dict())
    else:
        print_report(report, console)
    raise typer.Exit(exit_code(report))
