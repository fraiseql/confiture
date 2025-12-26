"""Output formatting for linting results.

This module provides functions to format LintReport results in various
output formats (table, JSON, CSV) for the lint CLI command.
"""

import json
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table

from confiture.models.lint import LintReport, LintSeverity


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

    if not report.violations:
        console.print("[green]✅ No violations found![/green]\n")
        return

    # Violations table
    table = Table(title="Violations")
    table.add_column("Severity", style="bold")
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
        # Color severity
        if violation.severity == LintSeverity.ERROR:
            severity_str = "[red]ERROR[/red]"
        elif violation.severity == LintSeverity.WARNING:
            severity_str = "[yellow]WARNING[/yellow]"
        else:
            severity_str = "[blue]INFO[/blue]"

        table.add_row(
            severity_str,
            violation.rule_name,
            violation.location,
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


def format_json(report: LintReport) -> str:
    """Format LintReport as JSON.

    Args:
        report: LintReport to format

    Returns:
        JSON string representation
    """
    data = {
        "schema_name": report.schema_name,
        "tables_checked": report.tables_checked,
        "columns_checked": report.columns_checked,
        "execution_time_ms": report.execution_time_ms,
        "violations": {
            "total": len(report.violations),
            "errors": report.errors_count,
            "warnings": report.warnings_count,
            "info": report.info_count,
            "items": [
                {
                    "rule": v.rule_name,
                    "severity": v.severity.value,
                    "location": v.location,
                    "message": v.message,
                    "suggested_fix": v.suggested_fix,
                }
                for v in report.violations
            ],
        },
    }
    return json.dumps(data, indent=2)


def format_csv(report: LintReport) -> str:
    """Format LintReport as CSV.

    Args:
        report: LintReport to format

    Returns:
        CSV string representation
    """
    lines = [
        "rule_name,severity,location,message,suggested_fix",
    ]

    for violation in report.violations:
        # Escape quotes in fields
        rule = violation.rule_name.replace('"', '""')
        severity = violation.severity.value
        location = violation.location.replace('"', '""')
        message = violation.message.replace('"', '""')
        fix = (violation.suggested_fix or "").replace('"', '""')

        # Quote fields that contain commas
        rule = f'"{rule}"' if "," in rule else rule
        location = f'"{location}"' if "," in location else location
        message = f'"{message}"' if "," in message else message
        fix = f'"{fix}"' if "," in fix else fix

        lines.append(f"{rule},{severity},{location},{message},{fix}")

    return "\n".join(lines)


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
    content = (
        format_json(report)
        if format_type == "json"
        else format_csv(report)
    )
    output_path.write_text(content)
