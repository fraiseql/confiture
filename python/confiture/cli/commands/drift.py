"""Drift command: compare live database schema against expected DDL."""

import json
from pathlib import Path

import typer

from confiture.cli.formatters.common import display_drift_report
from confiture.cli.helpers import console, error_console
from confiture.core.connection import create_connection, load_config
from confiture.core.drift import SchemaDriftDetector


def drift(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: confiture.yaml)",
    ),
    schema: Path | None = typer.Option(
        None,
        "--schema",
        help="Schema SQL file to compare against (required)",
    ),
    format_output: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with code 1 on warnings as well as critical drift (default: off)",
    ),
) -> None:
    """Compare live database schema against expected DDL for drift.

    PROCESS:
      Connects to the database, introspects the live schema, and compares it
      against the provided schema SQL file. Reports missing/extra tables and
      columns, type mismatches, and index differences.

    EXAMPLES:
      confiture drift --config confiture.yaml --schema db/generated/schema.sql
        ↳ Check live database for schema drift against a generated schema file

      confiture drift --config confiture.yaml --schema db/schema.sql --format json
        ↳ Output drift report as JSON for CI/CD pipelines

      confiture drift --config confiture.yaml --schema db/schema.sql --fail-on-warning
        ↳ Exit 1 on any drift (including warnings)

    EXIT CODES:
      0 - No drift detected
      1 - Drift detected (critical, or warning when --fail-on-warning)
      2 - Connection or configuration error

    RELATED:
      confiture migrate validate --check-live-drift - Validate within migrate workflow
      confiture migrate diff                        - Compare two schema files
    """
    try:
        if format_output not in ("table", "json"):
            error_console.print(
                f"[red]❌ Invalid format: {format_output}. Use 'table' or 'json'[/red]"
            )
            raise typer.Exit(1)

        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)

        if schema is None:
            error_console.print(
                "[red]❌ --schema is required. Provide a schema SQL file to compare against.[/red]"
            )
            raise typer.Exit(2)

        config_data = load_config(config)
        conn = create_connection(config_data)

        try:
            detector = SchemaDriftDetector(conn)
            drift_report = detector.compare_with_schema_file(str(schema))
        finally:
            conn.close()

        if format_output == "json":
            print(json.dumps(drift_report.to_dict(), indent=2, default=str))
        else:
            display_drift_report(drift_report, console)

        if drift_report.has_critical_drift:
            raise typer.Exit(1)

        if fail_on_warning and drift_report.has_drift:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except FileNotFoundError as e:
        error_console.print(f"[red]❌ {e}[/red]")
        raise typer.Exit(2) from e
    except Exception as e:
        error_console.print(f"[red]❌ Connection or configuration error: {e}[/red]")
        raise typer.Exit(2) from e
