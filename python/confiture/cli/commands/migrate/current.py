"""`confiture migrate current`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.dsn import (
    DATABASE_URL_OPTION_HELP,
    NO_CONFIG_OPTION_HELP,
    config_is_explicit,
    resolve_database_url,
)
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import _get_tracking_table, _output_json, console, error_console, is_json
from confiture.cli.options import format_option
from confiture.core.error_handler import handle_cli_error, print_error_to_console


@cli_boundary
def migrate_current(
    ctx: typer.Context,
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    output_format: str = format_option("text", "json"),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Print the current (latest applied) migration revision.

    Reads the tracking table and reports the most-recently-applied migration.
    A narrow, stable contract for tooling — no need to parse `migrate status`.

    OUTPUT:
      text  — the bare revision string (empty line if none applied)
      json  — {revision, name, applied_at, checksum}; revision is null when
              the tracking table exists but is empty.

    EXIT CODES:
      0  Current revision printed (or null when the table is empty).
      2  Tracking table absent — confiture not initialized on this database.
      3  Database connection failed.

    EXAMPLES:
      confiture migrate current -c db/environments/prod.yaml
      confiture migrate current --database-url "$DATABASE_URL" --format json
    """
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator
    from confiture.exceptions import DatabaseNotInitializedError
    from confiture.models.results import CurrentRevision

    try:
        override = resolve_database_url(
            database_url,
            config,
            config_explicit=config_is_explicit(ctx),
            no_config=no_config,
        )
        config_data = {"database_url": override} if override is not None else load_config(config)
        conn = create_connection(config_data)
        try:
            migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))
            # Probe first: the row query raises on an absent table (≠ empty).
            if not migrator.tracking_table_exists():
                raise DatabaseNotInitializedError(
                    "Database not initialized (tracking table absent)"
                )
            row = migrator.get_current_revision_row()
        finally:
            conn.close()
    except typer.Exit:
        raise
    except Exception as e:
        if is_json(output_format):
            fail(e, json_mode=True, output_file=output_file)
        print_error_to_console(e, error_console)
        raise typer.Exit(handle_cli_error(e)) from e

    cur = (
        None
        if row is None
        else CurrentRevision(
            version=row["version"],
            name=row["name"],
            applied_at=row["applied_at"],
            checksum=row.get("checksum"),
        )
    )

    if is_json(output_format):
        payload = (
            {"revision": None, "name": None, "applied_at": None, "checksum": None}
            if cur is None
            else cur.to_dict()
        )
        _output_json(payload, output_file, console)
    else:
        # Bare revision on stdout (plain print avoids Rich markup interpretation).
        print(cur.version if cur is not None else "")
