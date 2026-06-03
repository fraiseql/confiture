"""Top-level diff command: compare two SQL schema files."""

import json
from pathlib import Path

import typer

from confiture.cli.error_json import fail
from confiture.cli.formatters.diff_formatter import print_diff_text
from confiture.cli.helpers import console, is_json
from confiture.core.differ import SchemaDiffer
from confiture.exceptions import DifferError, SchemaError
from confiture.models.results import DiffResult


def schema_diff(
    from_file: Path = typer.Option(..., "--from", help="Old schema SQL file"),
    to_file: Path = typer.Option(..., "--to", help="New schema SQL file"),
    format_type: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
) -> None:
    """Compare two SQL schema files and report differences.

    EXAMPLES:

      confiture diff --from old.sql --to new.sql

      confiture diff --from old.sql --to new.sql --format json

    Exit codes: 0 = no changes, 1 = changes detected, 4 = input file not
    found (SCHEMA_201), 5 = schema parse error (DIFFER_400). In ``--format
    json`` mode, failures emit the ``{ok: false, error: {...}}`` envelope on
    stdout; exit 2 is never used here (it is reserved for "tracking table
    absent").
    """
    json_mode = is_json(format_type)

    for path, label in [(from_file, "--from"), (to_file, "--to")]:
        if not path.exists():
            fail(
                SchemaError(
                    f"{label} file not found: {path}",
                    error_code="SCHEMA_201",
                    resolution_hint=f"Check the path passed to {label}.",
                ),
                json_mode=json_mode,
            )

    old_sql = from_file.read_text()
    new_sql = to_file.read_text()

    try:
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)
    except Exception as exc:  # noqa: BLE001
        fail(
            DifferError(
                f"Cannot parse schema: {exc}",
                error_code="DIFFER_400",
                resolution_hint="Fix the SQL syntax in the schema files being compared.",
            ),
            json_mode=json_mode,
        )

    result = DiffResult.from_schema_diff(diff)

    if format_type == "json":
        print(json.dumps(result.to_dict(), indent=2))  # noqa: T201
    else:
        print_diff_text(result, console)

    raise typer.Exit(1 if result.has_changes else 0)
