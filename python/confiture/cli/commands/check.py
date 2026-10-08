"""``confiture check``: questions a live database answers about its data.

``check translations`` (#657) counts, per translation table ``db/project.yaml``
declares and per required locale, the entity rows with no translation.
"""

from pathlib import Path
from typing import Annotated

import typer

from confiture.cli.dsn import config_is_explicit, resolve_database_url
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console, emit, error_console, is_json, open_connection
from confiture.cli.options import (
    ProjectDirOpt,
    database_url_option,
    env_option,
    format_option,
    output_option,
)
from confiture.config.project import load_project_config
from confiture.core.builder import SchemaBuilder
from confiture.core.connection import load_config
from confiture.core.linting.inventory import label_for
from confiture.core.sql_lexer import parse_file
from confiture.core.translations import Coverage, translation_coverage
from confiture.error_codes import FINDINGS, NOT_RUN, SUCCESS
from confiture.exceptions import ConfigurationError

check_app = typer.Typer(help="Check what a live database holds: its data, not its schema")

SampleOpt = Annotated[
    int,
    typer.Option("--sample", min=0, help="How many missing entity keys to name per locale"),
]


@check_app.command("translations")
@cli_boundary
def check_translations(
    ctx: typer.Context,
    env: str = env_option("local"),
    database_url: str | None = database_url_option(help="The database whose rows are counted"),
    project_dir: ProjectDirOpt = Path(),
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help="missing: exit 1 when a required locale misses a row, 2 when a translation "
            "table could not be counted; never: report only (default)",
        ),
    ] = "never",
    sample: SampleOpt = 3,
    format_output: str = format_option("text", "json"),
    output_file: Path | None = output_option(),
) -> None:
    """Count the entity rows each required locale has no translation for.

    PROCESS:
      Reads the translation tables db/project.yaml declares (translations:) from
      the schema tree, as i18n_001 judges them, then counts on the database, per
      table and required locale, the live entity rows with no live translation,
      naming the first few keys. A table i18n_001 refuses is named, not counted.

    EXIT CODES:
      0 covered, or gaps found without --fail-on missing
      1 a required locale misses a row (--fail-on missing)
      2 no translations: block, or a table not counted (--fail-on missing)
      3 the database cannot be reached

    EXAMPLES:
      confiture check translations --env staging
        ↳ tl_category: en-US 0 missing, fr-FR 3 missing (e.g. 3, 4, 5)

      confiture check translations --env staging --fail-on missing --format json
        ↳ Gate a release on the locales it promises
    """
    if fail_on not in ("missing", "never"):
        raise typer.BadParameter("--fail-on takes missing or never", param_hint="--fail-on")
    project = load_project_config(project_dir)
    if project.translations is None:
        error_console.print(
            t"[yellow]No translations: block in db/project.yaml: nothing to check.[/yellow]"
        )
        raise typer.Exit(NOT_RUN)
    env_file = project_dir / "db" / "environments" / f"{env}.yaml"
    override = resolve_database_url(database_url, env_file, config_explicit=config_is_explicit(ctx))
    if override is None and not env_file.is_file():
        fail(
            ConfigurationError(
                f"Environment file not found: {env_file}",
                error_code="CONFIG_004",
                resolution_hint="Pass --env <name> for db/environments/<name>.yaml, "
                "or --database-url.",
            ),
            json_mode=is_json(format_output),
        )
    files = [
        parse_file(path.read_text(encoding="utf-8"), label_for(path, project_dir))
        for path in SchemaBuilder(env=env, project_dir=project_dir).find_sql_files()
    ]
    with open_connection(
        {"database_url": override} if override is not None else load_config(env_file)
    ) as conn:
        coverage = translation_coverage(conn, files, project, sample)
    if is_json(format_output):
        emit(coverage.to_dict(), output_file)
    else:
        _print(coverage)
    raise typer.Exit(_exit_code(coverage, fail_on))


def _exit_code(coverage: Coverage, fail_on: str) -> int:
    if fail_on != "missing":
        return SUCCESS
    if coverage.missing:
        return FINDINGS
    return NOT_RUN if coverage.not_counted else SUCCESS


def _print(coverage: Coverage) -> None:
    for table in coverage.tables:
        console.print(t"{table.line()}")
    for locale in coverage.unknown_locales:
        console.print(t"[yellow]{locale} is not in the locale table[/yellow]")
    for message in coverage.not_counted:
        console.print(t"[yellow]not counted: {message}[/yellow]")
    if not coverage.tables and not coverage.not_counted:
        console.print(t"[yellow]translations.tables matches no table[/yellow]")
