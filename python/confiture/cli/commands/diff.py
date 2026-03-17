"""Top-level diff command: compare two SQL schema files."""

import json
from pathlib import Path

import typer

from confiture.cli.formatters.diff_formatter import print_diff_text
from confiture.cli.helpers import console, error_console
from confiture.core.differ import SchemaDiffer
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

    Exit codes: 0 = no changes, 1 = changes detected, 2 = error.
    """
    for path, label in [(from_file, "--from"), (to_file, "--to")]:
        if not path.exists():
            error_console.print(f"[red]Error:[/red] {label} file not found: {path}")
            raise typer.Exit(2)

    old_sql = from_file.read_text()
    new_sql = to_file.read_text()

    try:
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)
    except Exception as exc:  # noqa: BLE001
        error_console.print(f"[red]Error parsing schema:[/red] {exc}")
        raise typer.Exit(2) from exc

    result = DiffResult.from_schema_diff(diff)

    if format_type == "json":
        print(json.dumps(result.to_dict(), indent=2))  # noqa: T201
    else:
        print_diff_text(result, console)

    raise typer.Exit(1 if result.has_changes else 0)
