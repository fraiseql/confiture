"""Formatter for dry-run command output.

Handles text, JSON formatting for dry-run results.
"""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from confiture.cli.formatters.common import handle_output
from confiture.core.dry_run import DryRunResult


def format_dry_run_result(
    result: DryRunResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format dry-run result in requested format.

    Args:
        result: DryRunResult to format
        format_type: Output format ('text', 'json')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        format_text(result, console)
    else:
        # JSON output
        handle_output(format_type, result.__dict__, None, output_path, console)


def format_text(result: DryRunResult, console: Console) -> None:
    """Format dry-run result as text output.

    Args:
        result: DryRunResult to format
        console: Rich console for output
    """
    # Header
    status = "[green]✓ SUCCESS[/green]" if result.success else "[red]❌ FAILED[/red]"

    console.print(f"Dry-run: {status}")
    console.print(f"Migration: {result.migration_name}")
    console.print(f"Total time: {result.total_time_ms:.1f}ms")
    console.print(f"Confidence: {result.confidence_pct}%")

    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")

    # Statement details
    if result.statements:
        console.print("\n[bold]Statement Details:[/bold]")

        table = Table(show_header=True, header_style="bold")
        table.add_column("SQL", style="dim", max_width=60)
        table.add_column("Status", justify="center")
        table.add_column("Time (ms)", justify="right")
        table.add_column("Rows", justify="right")

        for stmt in result.statements:
            status = "[green]✓[/green]" if stmt.success else "[red]❌[/red]"
            sql_preview = stmt.sql[:57] + "..." if len(stmt.sql) > 60 else stmt.sql
            table.add_row(sql_preview, status, ".1f", str(stmt.rows_affected))

        console.print(table)

    console.print(f"\nTotal rows affected: {result.rows_affected}")

    if result.failed_statements:
        console.print(f"[red]Failed statements: {len(result.failed_statements)}[/red]")
