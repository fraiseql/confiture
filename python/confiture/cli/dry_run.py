"""Dry-run mode helpers for CLI integration.

This module provides helper functions for dry-run analysis integration with the CLI.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from confiture.core.migration.dry_run.dry_run_mode import DryRunReport

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


def show_report_summary(report: "DryRunReport") -> None:
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
    # This is a placeholder - in Day 2 implementation, we would:
    # 1. Create a migration instance with a mock connection
    # 2. Track calls to self.execute()
    # 3. Extract the SQL statements
    # For now, return empty list - actual implementation in Day 2
    return []


def display_dry_run_header(mode: str) -> None:
    """Display header for dry-run analysis.

    Args:
        mode: Either "analysis" for --dry-run or "testing" for --dry-run-execute
    """
    if mode == "testing":
        console.print("[cyan]🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...[/cyan]\n")
    else:
        console.print("[cyan]🔍 Analyzing migrations without execution...[/cyan]\n")


def display_dry_run_results(report: "DryRunReport", verbose: bool = False) -> None:
    """Display dry-run analysis results.

    Args:
        report: DryRunReport object
        verbose: Show detailed analysis
    """
    from confiture.core.migration.dry_run.report import DryRunReportGenerator

    generator = DryRunReportGenerator(use_colors=True, verbose=verbose)
    text_report = generator.generate_text_report(report)
    console.print(text_report)
