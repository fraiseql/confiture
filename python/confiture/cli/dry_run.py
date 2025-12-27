"""Dry-run mode helpers for CLI integration.

This module provides helper functions for dry-run analysis integration with the CLI.
"""

import json
from pathlib import Path

from rich.console import Console

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


def show_report_summary(report) -> None:
    """Show a brief summary of the report status.

    Args:
        report: DryRunReport object
    """
    if not report.has_unsafe_statements:
        console.print("[green]✓ SAFE[/green]", end=" ")
    else:
        console.print(f"[red]❌ UNSAFE ({report.unsafe_count} statements)[/red]", end=" ")

    console.print(f"| Time: {report.total_estimated_time_ms}ms | Disk: {report.total_estimated_disk_mb:.1f}MB")


def ask_dry_run_execute_confirmation() -> bool:
    """Ask user to confirm real execution after dry-run-execute test.

    Returns:
        True if user confirms, False otherwise
    """
    import typer

    return typer.confirm("\n🔄 Proceed with real execution?", default=False)
