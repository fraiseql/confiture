"""Dry-run mode helpers for CLI integration.

This module provides helper functions for dry-run analysis integration with the CLI.
"""

import json
import logging
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


def save_text_report(report_text: str, filepath: Path) -> None:
    """Save text report to file.

    Args:
        report_text: Formatted text report
        filepath: Path to save report to

    Raises:
        IOError: If file write fails
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(report_text)


def save_json_report(report_data: dict, filepath: Path) -> None:
    """Save JSON report to file.

    Args:
        report_data: Report dictionary to save
        filepath: Path to save report to

    Raises:
        IOError: If file write fails
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w") as f:
        json.dump(report_data, f, indent=2)


def print_json_report(report_data: dict) -> None:
    """Print JSON report to console.

    Args:
        report_data: Report dictionary to print
    """
    console.print_json(data=report_data)


def show_report_summary(report: Any) -> None:
    """Show a brief summary of the report status.

    Args:
        report: Report object with has_unsafe_statements, unsafe_count,
                total_estimated_time_ms, and total_estimated_disk_mb attributes
    """
    if not report.has_unsafe_statements:
        console.print("[green]✓ SAFE[/green]", end=" ")
    else:
        unsafe_msg = f"[red]❌ UNSAFE ({report.unsafe_count} statements)[/red]"
        console.print(unsafe_msg, end=" ")

    time_str = report.total_estimated_time_ms
    disk_str = report.total_estimated_disk_mb
    console.print(f"| Time: {time_str}ms | Disk: {disk_str:.1f}MB")


def ask_dry_run_execute_confirmation() -> bool:
    """Ask user to confirm real execution after dry-run-execute test.

    Returns:
        True if user confirms, False otherwise
    """
    import typer

    return typer.confirm("\n🔄 Proceed with real execution?", default=False)


def extract_sql_statements_from_migration(migration_class) -> list[str]:
    """Extract SQL statements from a migration's up() method.

    This is a helper that attempts to extract SQL statements from migration
    code by inspecting the migration object. This is limited and approximate
    since migrations use self.execute() calls.

    Args:
        migration_class: Migration class (not instance)

    Returns:
        List of SQL statement strings (may be approximate/incomplete)
    """
    # SQL extraction from migration classes requires a mock connection
    # that intercepts self.execute() calls to capture statements.
    # Not yet implemented - returns empty list.
    return []


def display_dry_run_header(mode: str) -> None:
    """Display header for dry-run analysis.

    Args:
        mode: Either "analysis" for --dry-run or "testing" for --dry-run-execute
    """
    if mode == "testing":
        msg = "[cyan]🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...[/cyan]"
        console.print(msg + "\n")
    else:
        msg = "[cyan]🔍 Analyzing migrations without execution...[/cyan]"
        console.print(msg + "\n")
