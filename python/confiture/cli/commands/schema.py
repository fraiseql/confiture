"""``confiture schema``: the schema model itself, as confiture reads it.

``schema dump-model`` writes ``SchemaModel.to_json()`` — from DDL, from a project's
build or from a live database — in the envelope every command's JSON carries. It is
the model's one wire form: the same model is the same bytes, so a second
implementation (the Rust port, a parity fixture) is checked against it byte for
byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import console, emit
from confiture.cli.options import (
    ProjectDirOpt,
    database_url_option,
    env_option,
    format_option,
    output_option,
)
from confiture.core.schema_model import SchemaModel
from confiture.core.schema_sources import introspect, parse_schema

schema_app = typer.Typer(help="The schema model, as confiture reads it", no_args_is_help=True)


def _model(
    paths: list[Path],
    env: str | None,
    project_dir: Path,
    database_url: str | None,
    schemas: str | None,
) -> SchemaModel:
    given = [
        name
        for name, value in (("PATHS", paths), ("--env", env), ("--database-url", database_url))
        if value
    ]
    if len(given) != 1:
        raise typer.BadParameter(
            f"read exactly one source: PATHS, --env or --database-url (given: {', '.join(given) or 'none'})"
        )
    if database_url:
        wanted = [s.strip() for s in schemas.split(",") if s.strip()] if schemas else None
        return introspect(database_url, schemas=wanted)
    if env:
        return parse_schema(env=env, project_dir=project_dir)
    return parse_schema(paths)


def _summary(model: SchemaModel) -> list[str]:
    counts = (
        (len(model.tables), "table"),
        (len(model.enum_types), "enum type"),
        (len(model.sequences), "sequence"),
        (len(model.all_routines()), "routine"),
        (len(model.views), "view"),
        (len(model.triggers), "trigger"),
    )
    return [f"{count} {noun}{'' if count == 1 else 's'}" for count, noun in counts]


@schema_app.command("dump-model")
@cli_boundary
def dump_model(
    paths: list[Path] = typer.Argument(
        None,
        help="DDL files or directories, read in the order given (a directory as the build reads one)",
    ),
    env: str | None = env_option(
        None, help="Read what `confiture build --env <name> --schema-only` builds"
    ),
    project_dir: ProjectDirOpt = Path(),
    database_url: str | None = database_url_option(
        help="Read a live database's catalog instead of DDL"
    ),
    schemas: str | None = typer.Option(
        None,
        "--schemas",
        help="With --database-url: comma-separated schemas to read (default: every user schema)",
    ),
    format_type: str = format_option("json", "text"),
    output_file: Path | None = output_option(),
) -> None:
    """Write the schema model: tables, types, sequences, routines, views and triggers.

    One source: DDL PATHS, a project's build (--env), or a database (--database-url).
    The JSON is `SchemaModel.to_json()` under `model`, keys sorted, in the envelope
    (`ok`, `command`, `parser`); the same model is the same bytes on every run.

    EXAMPLES:
      confiture schema dump-model --env local
        ↳ The model of what `confiture build --env local` builds

      confiture schema dump-model db/schema/10_tables db/schema/20_views
        ↳ Two directories, read in that order

      confiture schema dump-model --database-url $DATABASE_URL --schemas app,catalog
        ↳ The model a live database holds
    """
    model = _model(paths or [], env, project_dir, database_url, schemas)
    if format_type == "json":
        emit({"model": json.loads(model.to_json())}, output_file, console)
        return
    console.print(", ".join(_summary(model)))
