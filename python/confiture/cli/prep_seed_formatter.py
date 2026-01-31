"""Formatter for prep-seed validation reports.

Handles output formatting in text/JSON/CSV formats with rich tables and
severity-based grouping.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.table import Table

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedReport,
    ViolationSeverity,
)


def format_prep_seed_report(
    report: PrepSeedReport,
    format_type: str,
    output: Path | None,
    console: Console,
) -> None:
    """Format and output prep-seed validation report.

    Args:
        report: Validation report to format
        format_type: Output format ('text', 'json', or 'csv')
        output: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "json":
        output_json(report, output, console)
    elif format_type == "csv":
        output_csv(report, output, console)
    else:
        # Default to text format
        output_table(report, output, console)


def output_table(
    report: PrepSeedReport,
    output: Path | None,
    console: Console,
) -> None:
    """Format report as rich table grouped by severity.

    Args:
        report: Validation report
        output: Optional file path (ignored for table format)
        console: Rich console for output
    """
    console.print("\nPrep-Seed Validation Report")
    console.print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    console.print(f"Files scanned: {len(report.scanned_files)}")
    console.print(f"Violations found: {report.violation_count}")

    if report.has_violations:
        console.print("\n[red]Issues found:[/red]")

        # Group by severity
        violations_by_severity = report.violations_by_severity()

        # Order: CRITICAL, ERROR, WARNING, INFO
        severity_order = [
            ViolationSeverity.CRITICAL,
            ViolationSeverity.ERROR,
            ViolationSeverity.WARNING,
            ViolationSeverity.INFO,
        ]

        for severity in severity_order:
            violations = violations_by_severity.get(severity, [])
            if not violations:
                continue

            # Create severity-specific table
            severity_color = {
                ViolationSeverity.CRITICAL: "red",
                ViolationSeverity.ERROR: "yellow",
                ViolationSeverity.WARNING: "yellow",
                ViolationSeverity.INFO: "blue",
            }.get(severity, "white")

            console.print(
                f"\n[{severity_color}]{severity.name}[/{severity_color}] "
                f"({len(violations)} found)"
            )

            table = Table(show_header=True, header_style="bold")
            table.add_column("File", style="cyan")
            table.add_column("Line", style="magenta")
            table.add_column("Pattern", style="yellow")
            table.add_column("Message", style="white")

            # Mark fixable violations
            for violation in sorted(
                violations, key=lambda v: (v.file_path, v.line_number)
            ):
                pattern_text = violation.pattern.name
                if violation.fix_available:
                    pattern_text += " ✓"

                table.add_row(
                    violation.file_path,
                    str(violation.line_number),
                    pattern_text,
                    violation.message,
                )

            console.print(table)
    else:
        console.print("[green]✓ All prep-seed validations passed![/green]")


def output_json(
    report: PrepSeedReport,
    output: Path | None,
    console: Console,
) -> None:
    """Format report as JSON.

    Args:
        report: Validation report
        output: Optional file path to write JSON
        console: Rich console for output
    """
    report_dict = report.to_dict()
    json_output = json.dumps(report_dict, indent=2)

    if output:
        output.write_text(json_output)
        console.print(f"[green]✓ Report saved to {output}[/green]")
    else:
        # Use console.print with no_color to output raw JSON
        # without ANSI codes
        console.print(json_output, soft_wrap=False)


def output_csv(
    report: PrepSeedReport,
    output: Path | None,
    console: Console,
) -> None:
    """Format report as CSV.

    Args:
        report: Validation report
        output: Optional file path to write CSV
        console: Rich console for output
    """
    # Create CSV content
    csv_output = StringIO()
    writer = csv.writer(csv_output)

    # Write header
    writer.writerow(
        [
            "File",
            "Line",
            "Severity",
            "Pattern",
            "Message",
            "Fix Available",
            "Suggestion",
        ]
    )

    # Write violations
    for violation in sorted(
        report.violations, key=lambda v: (v.severity.name, v.file_path, v.line_number)
    ):
        writer.writerow(
            [
                violation.file_path,
                violation.line_number,
                violation.severity.name,
                violation.pattern.name,
                violation.message,
                "Yes" if violation.fix_available else "No",
                violation.suggestion or "",
            ]
        )

    csv_content = csv_output.getvalue()

    if output:
        output.write_text(csv_content)
        console.print(f"[green]✓ Report saved to {output}[/green]")
    else:
        console.print(csv_content)
