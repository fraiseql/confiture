"""``confiture introspect``: a live database's tables and relationships."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console as _Console

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _output_yaml,
    connect,
    emit,
    is_json,
)
from confiture.cli.options import (
    format_option,
    output_option,
)
from confiture.core.connection import DatabaseError
from confiture.core.introspection.tables import SchemaIntrospector
from confiture.exceptions import ConfigurationError, ConfiturError


@cli_boundary
def introspect(
    db: str = typer.Option(
        ...,
        "--db",
        help="PostgreSQL connection URL (e.g. postgresql://user:pass@host/dbname)",
    ),
    schema: str = typer.Option(
        "public",
        "--schema",
        help="Schema to introspect (default: public)",
    ),
    format_type: str = format_option("json", "yaml"),
    all_tables: bool = typer.Option(
        False,
        "--all-tables",
        help="Include all tables, not just tb_* (default: off)",
    ),
    hints: bool = typer.Option(
        True,
        "--hints/--no-hints",
        help="Include naming-convention hints block (default: on)",
    ),
    output: Path | None = output_option(),
) -> None:
    """Introspect a PostgreSQL database and export its schema as structured JSON.

    Connects to an existing database and exports tables, columns, PostgreSQL
    types, primary keys, and the full FK relationship graph.  Designed for
    brownfield adoption and agentic workflows where an agent needs accurate,
    structured facts about a schema it cannot see.

    By default only tables whose names start with ``tb_`` are included.
    Use ``--all-tables`` to include every base table in the schema.

    The ``hints`` block surfaces surrogate-PK / natural-ID naming patterns as
    non-prescriptive signals.  Use ``--no-hints`` to omit it.

    Examples:

      confiture introspect --db $DATABASE_URL

      confiture introspect --db $DATABASE_URL --schema myschema

      confiture introspect --db $DATABASE_URL --format yaml --output schema.yaml

      confiture introspect --db $DATABASE_URL --all-tables --no-hints
    """

    # Status/error messages go to stderr so stdout stays pipe-friendly.
    _console = _Console(stderr=True)

    # introspect emits json or yaml; the unified error envelope is JSON, so we
    # route failures through fail() in JSON mode only when the requested format
    # is json (yaml failures fall back to the human path).
    json_mode = is_json(format_type)

    try:
        conn = connect(db)
    except (ConfiturError, DatabaseError) as e:
        fail(
            ConfigurationError(
                f"Connection failed: {e}",
                error_code="CONFIG_006",
            ),
            json_mode=json_mode,
            output_file=output,
        )

    with conn:
        introspector = SchemaIntrospector(conn)
        result = introspector.introspect(
            schema=schema,
            all_tables=all_tables,
            include_hints=hints,
        )

    data = result.to_dict()

    if format_type == "yaml":
        _output_yaml(data, output, _console)
    else:
        emit(data, output, _console)
