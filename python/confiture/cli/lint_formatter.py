"""Output formatting for linting results.

This module provides functions to format LintReport results in various
output formats (table, JSON, CSV) for the lint CLI command.
"""

import csv
import io
import json
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table

from confiture.core.parser_info import parser_stamp
from confiture.models.lint import LintReport, LintSeverity, Violation


def format_lint_report(
    report: LintReport,
    format_type: Literal["table", "json", "csv"] = "table",
    console: Console | None = None,
) -> str:
    """Format a LintReport in the specified format.

    Args:
        report: LintReport to format
        format_type: Output format (table, json, or csv)
        console: Rich Console instance for table rendering

    Returns:
        Formatted report as string
    """
    if format_type == "json":
        return format_json(report)
    elif format_type == "csv":
        return format_csv(report)
    else:  # table
        if console is None:
            console = Console()
        format_table(report, console)
        return ""


def _severity_string(severity: LintSeverity) -> str:
    """Format severity level with color.

    Args:
        severity: Severity level to format

    Returns:
        Colored severity string for Rich output
    """
    if severity == LintSeverity.ERROR:
        return "[red]ERROR[/red]"
    elif severity == LintSeverity.WARNING:
        return "[yellow]WARNING[/yellow]"
    return "[blue]INFO[/blue]"


def _location_cell(violation: Violation) -> str:
    """The object, and under it the file and line — the answer to "where?".

    A finding with no file shows the object alone; a line without a file is not
    a location and is never rendered on its own.
    """
    if not violation.file:
        return violation.location
    where = f"{violation.file}:{violation.line}" if violation.line else violation.file
    return f"{violation.location}\n[dim]{where}[/dim]"


def format_table(report: LintReport, console: Console) -> None:
    """Display LintReport as a rich table.

    Args:
        report: LintReport to display
        console: Rich Console instance for rendering
    """
    # Summary section
    console.print(f"\n[bold]Schema Linting Results[/bold] - {report.schema_name}")
    console.print(f"Tables: {report.tables_checked} checked")
    console.print(f"Columns: {report.columns_checked} checked")
    console.print(f"Time: {report.execution_time_ms}ms\n")

    _print_statuses(report, console)

    if not report.violations:
        console.print("[green]✅ No violations found![/green]\n")
        return

    # Violations table
    table = Table(title="Violations")
    table.add_column("Severity", style="bold")
    # The code, not just the prose name: it is what --select / --ignore take.
    table.add_column("Code", style="cyan")
    table.add_column("Rule", style="cyan")
    table.add_column("Location", style="yellow")
    table.add_column("Message", style="white")

    for violation in sorted(
        report.violations,
        key=lambda v: (
            v.severity == LintSeverity.ERROR,
            v.severity == LintSeverity.WARNING,
        ),
        reverse=True,
    ):
        table.add_row(
            _severity_string(violation.severity),
            violation.rule_id,
            violation.rule_name,
            _location_cell(violation),
            violation.message,
        )

    console.print(table)

    # Summary counts
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  {report.errors_count} errors")
    console.print(f"  {report.warnings_count} warnings")
    console.print(f"  {report.info_count} info")

    # Suggested fixes (if any)
    fixes = [v for v in report.violations if v.suggested_fix]
    if fixes:
        console.print("\n[bold]Suggested Fixes:[/bold]")
        for violation in fixes:
            console.print(f"  {violation.location}: {violation.suggested_fix}")


#: How each status reads on the summary: "<code> <verb> <reason>".
_STATE_VERB = {
    "skipped": "did not run",
    "degraded": "ran without the live tier",
}


def _print_statuses(report: LintReport, console: Console) -> None:
    """Say which rules did not run, and which ran short of a tier.

    Printed above the findings, because it changes how the findings should be
    read — a degraded rule over-reports, and a skipped one reports nothing at
    all. ``markup=False``: a reason carries a rule code and a driver's error
    text, and Rich would read ``[build_003]`` as a style tag and render it as
    nothing.
    """
    for status in (*report.skipped, *report.degraded):
        verb = _STATE_VERB.get(status["state"], status["state"])
        console.print(f"{status['code']} {verb}: {status['reason']}\n", markup=False)


def format_json(report: LintReport) -> str:
    """Format LintReport as JSON.

    Args:
        report: LintReport to format

    Returns:
        JSON string representation
    """
    data = report.to_dict()
    data["parser"] = parser_stamp()
    return json.dumps(data, indent=2)


def format_csv(report: LintReport) -> str:
    """Format LintReport as CSV.

    Args:
        report: LintReport to format

    Returns:
        CSV string representation
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["rule_name", "severity", "location", "file", "line", "message", "suggested_fix"]
    )
    for violation in report.violations:
        writer.writerow(
            [
                violation.rule_name,
                violation.severity.value,
                violation.location,
                violation.file or "",
                "" if violation.line is None else violation.line,
                violation.message,
                violation.suggested_fix or "",
            ]
        )
    return buffer.getvalue().rstrip("\n")


def save_report(
    report: LintReport,
    output_path: Path,
    format_type: Literal["json", "csv"] = "json",
) -> None:
    """Save LintReport to a file.

    Args:
        report: LintReport to save
        output_path: Path to save to
        format_type: Output format (json or csv)
    """
    content = format_json(report) if format_type == "json" else format_csv(report)
    output_path.write_text(content)
