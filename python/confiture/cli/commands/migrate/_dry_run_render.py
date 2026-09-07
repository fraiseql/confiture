"""Shared rendering of `--dry-run` summaries for `migrate up` / `migrate down`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from confiture.cli.helpers import (
    console,
    error_console,
)


def _render_dry_run_analysis(
    pending: list[tuple[str, str]],
    *,
    migrations_dir: Path,
    migration_id: str,
    execute: bool,
    format_output: str,
    output_file: Path | None,
    estimate_rows: Any = None,
    rollback: bool = False,
) -> None:
    """The dry-run summary of ``migrate up --dry-run`` / ``migrate down --dry-run``."""
    from confiture.cli.dry_run import print_json_report, save_json_report, save_text_report
    from confiture.cli.dry_run_summary import build_dry_run_summary, render_dry_run_text

    summary = build_dry_run_summary(
        pending,
        migrations_dir=migrations_dir,
        migration_id=migration_id,
        mode="execute_and_analyze" if execute else "analysis",
        estimate_rows=estimate_rows,
    )
    if format_output == "json":
        if output_file:
            save_json_report(summary, output_file)
            error_console.print(f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]")
        else:
            print_json_report(summary)
        return

    text = render_dry_run_text(summary, rollback=rollback)
    if not rollback:
        console.print(f"[cyan]📦 Found {len(pending)} pending migration(s)[/cyan]\n")
    console.print(text, end="", highlight=False, markup=False)
    if output_file:
        title = (
            "DRY-RUN ROLLBACK ANALYSIS REPORT" if rollback else "DRY-RUN MIGRATION ANALYSIS REPORT"
        )
        save_text_report(title + "\n" + "=" * 80 + "\n\n" + text, output_file)
        console.print(f"[green]✅ Report saved to: {output_file.absolute()}[/green]")


def _row_estimator(connection: Any) -> Any:
    from confiture.cli.dry_run_summary import row_estimator

    return row_estimator(connection)
