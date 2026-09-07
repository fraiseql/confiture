"""`confiture migrate estimate`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import (
    console,
    error_console,
    open_connection,
)
from confiture.cli.options import format_option
from confiture.core import connection as _core_connection
from confiture.core import large_tables as _core_large_tables


@cli_boundary
def migrate_estimate(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    tables: list[str] = typer.Option(
        [],
        "--table",
        "-t",
        help="Tables to estimate (default: all tables)",
    ),
    format_output: str = format_option("table", "json"),
) -> None:
    """Estimate row counts for tables to decide if --batched is needed.

    Uses pg_class statistics (fast, no COUNT(*)) to show which tables
    are large enough to benefit from --batched mode.

    EXAMPLES:
      confiture migrate estimate
        ↳ Show row count estimates for all tables

      confiture migrate estimate --table users --table orders
        ↳ Estimate specific tables only

    RELATED:
      confiture migrate up --batched - Apply migrations in batch mode
    """

    try:
        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)

        config_data = _core_connection.load_config(config)
        with open_connection(config_data) as conn:
            estimator = _core_large_tables.TableSizeEstimator(conn)

        # If no tables specified, estimate all in public schema
        if not tables:
            tables = estimator.all_tables()

        if not tables:
            console.print("[yellow]No tables found.[/yellow]")
            return

        rows_data: list[dict[str, Any]] = []
        for table in tables:
            estimate = estimator.get_row_count_estimate(table)
            should_batch = estimator.should_use_batched_operation(table)
            rows_data.append(
                {
                    "table": table,
                    "estimated_rows": estimate,
                    "recommendation": "Use --batched" if should_batch else "Standard migration OK",
                }
            )

        if format_output == "json":
            print(json.dumps(rows_data, indent=2))
        else:
            tbl = Table(title="Table Row Count Estimates")
            tbl.add_column("Table", style="cyan")
            tbl.add_column("Estimated Rows", justify="right")
            tbl.add_column("Recommendation")
            for row in rows_data:
                style = "yellow" if row["recommendation"].startswith("Use") else "green"
                tbl.add_row(
                    row["table"],
                    f"{row['estimated_rows']:,}",
                    f"[{style}]{row['recommendation']}[/{style}]",
                )
            console.print(tbl)

    except typer.Exit:
        raise
    # Reason: legacy text-only command: every failure is printed and exits 1
    except Exception as e:
        error_console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e
