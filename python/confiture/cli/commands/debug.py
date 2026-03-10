"""Debug commands for CTE step-through analysis."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from confiture.cli.helpers import console, error_console

debug_app = typer.Typer(
    help="Debug SQL queries step by step.",
    no_args_is_help=True,
)


@debug_app.command("cte")
def debug_cte(
    database_url: str = typer.Option(
        ..., "--database-url", "-d", help="PostgreSQL connection URL"
    ),
    sql: str | None = typer.Option(None, "--sql", "-s", help="SQL query to debug"),
    file: Path | None = typer.Option(None, "--file", "-f", help="SQL file to debug"),
    max_rows: int = typer.Option(
        20, "--max-rows", "-n", help="Max rows per CTE step (default: 20)"
    ),
    format_type: str = typer.Option(
        "table", "--format", help="Output format: table, json (default: table)"
    ),
    stop_on_error: bool = typer.Option(
        True, "--stop-on-error/--continue-on-error", help="Stop at first failing CTE"
    ),
) -> None:
    """Debug a SQL query with CTEs by executing each CTE in isolation.

    Shows intermediate results for each CTE step to pinpoint failures.

    EXAMPLES:
      confiture debug cte -d $DATABASE_URL --file query.sql
        Step through all CTEs in query.sql

      confiture debug cte -d $DATABASE_URL --sql "WITH a AS (SELECT 1) SELECT * FROM a"
        Debug an inline query

      confiture debug cte -d $DATABASE_URL --file query.sql --format json
        Output results as JSON
    """
    import psycopg

    from confiture.core.cte_debugger import CTEDebugger

    if sql is None and file is None:
        error_console.print("[red]Provide --sql or --file[/red]")
        raise typer.Exit(1)

    if file is not None:
        if not file.exists():
            error_console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)
        query = file.read_text()
    else:
        query = sql  # type: ignore[assignment]

    try:
        conn = psycopg.connect(database_url)
    except Exception as e:
        error_console.print(f"[red]Connection failed: {e}[/red]")
        raise typer.Exit(1) from e

    try:
        debugger = CTEDebugger(conn)
        session = debugger.debug(query, max_rows=max_rows)
    finally:
        conn.close()

    if format_type == "json":
        console.print(json.dumps(session.to_dict(), indent=2, default=str))
        if not session.all_succeeded:
            raise typer.Exit(1)
        return

    # Table output
    console.print(f"[bold]CTE Debug Session[/bold]  ({session.total_ctes} CTE(s))")
    console.print("")

    for step in session.steps:
        if step.success:
            console.print(
                f"[green]✓[/green] [bold]{step.cte_name}[/bold]  "
                f"{step.row_count} row(s)  {step.execution_time_ms:.1f}ms"
            )
            if step.columns and step.rows:
                from rich.table import Table

                tbl = Table(show_header=True, header_style="bold cyan")
                for col in step.columns:
                    tbl.add_column(col)
                for row in step.rows[:max_rows]:
                    tbl.add_row(*[str(v) for v in row])
                console.print(tbl)
        else:
            console.print(f"[red]✗[/red] [bold]{step.cte_name}[/bold]  ERROR")
            console.print(f"  [red]{step.error}[/red]")
            if stop_on_error:
                break

    console.print("")
    if session.all_succeeded:
        console.print("[green]All CTE steps succeeded.[/green]")
    else:
        console.print(f"[red]Failed at CTE: {session.failed_at}[/red]")
        raise typer.Exit(1)
