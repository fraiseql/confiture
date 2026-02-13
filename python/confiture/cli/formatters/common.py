"""Common formatting utilities for structured output.

Provides reusable functions for JSON and CSV output handling
across all CLI commands that support structured output.
"""

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console


def save_json(data: dict[str, Any], output_path: Path) -> None:
    """Save data as formatted JSON file.

    Args:
        data: Dictionary to serialize as JSON
        output_path: Path to write JSON file to
    """
    output_path.write_text(json.dumps(data, indent=2, default=str))


def print_json(data: dict[str, Any], console: Console) -> None:
    """Print JSON to console using standard print to avoid Rich formatting.

    Args:
        data: Dictionary to display as JSON
        console: Rich console for output (ignored for JSON to avoid formatting)
    """
    # Print raw JSON without Rich formatting
    import sys

    json_text = json.dumps(data, indent=2, default=str)
    print(json_text, file=sys.stdout)


def save_csv(headers: list[str], rows: list[list[Any]], output_path: Path) -> None:
    """Save data as CSV file with proper escaping.

    Args:
        headers: Column headers for CSV
        rows: List of rows (each row is a list of values)
        output_path: Path to write CSV file to
    """
    csv_output = StringIO()
    writer = csv.writer(csv_output)
    writer.writerow(headers)
    writer.writerows(rows)
    output_path.write_text(csv_output.getvalue())


def print_csv(headers: list[str], rows: list[list[Any]], console: Console) -> None:
    """Print CSV to console.

    Args:
        headers: Column headers for CSV
        rows: List of rows (each row is a list of values)
        console: Rich console for output
    """
    csv_output = StringIO()
    writer = csv.writer(csv_output)
    writer.writerow(headers)
    writer.writerows(rows)
    console.print(csv_output.getvalue())


def handle_output(
    format_type: str,
    data_dict: dict[str, Any],
    csv_data: tuple[list[str], list[list[Any]]] | None,
    output_path: Path | None,
    console: Console,
) -> None:
    """Handle output in requested format.

    Routes output to appropriate handler (JSON/CSV/text) and either
    saves to file or prints to console.

    Args:
        format_type: "text", "json", or "csv"
        data_dict: Data for JSON output
        csv_data: (headers, rows) tuple for CSV output, or None if CSV not supported
        output_path: Optional file to save to
        console: Rich console for printing
    """
    if format_type == "json":
        if output_path:
            save_json(data_dict, output_path)
            console.print(f"[green]✓ JSON report saved to {output_path.absolute()}[/green]")
        else:
            print_json(data_dict, console)

    elif format_type == "csv":
        if csv_data is None:
            console.print("[yellow]⚠ CSV output not supported for this command[/yellow]")
            return

        headers, rows = csv_data
        if output_path:
            save_csv(headers, rows, output_path)
            console.print(f"[green]✓ CSV report saved to {output_path.absolute()}[/green]")
        else:
            print_csv(headers, rows, console)
