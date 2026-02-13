"""Formatter for migrate command output.

Handles text, JSON, and CSV formatting for migration results.
"""

from pathlib import Path

from rich.console import Console

from confiture.cli.formatters.common import handle_output
from confiture.models.results import MigrateDownResult, MigrateUpResult


def format_migrate_up_result(
    result: MigrateUpResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate up result in requested format.

    Args:
        result: MigrateUpResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        # Text output to console
        format_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["version", "name", "execution_time_ms", "rows_affected"],
            [
                [m.version, m.name, str(m.execution_time_ms), str(m.rows_affected)]
                for m in result.migrations_applied
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_text(result: MigrateUpResult, console: Console) -> None:
    """Format migrate up result as rich text for console output.

    Args:
        result: MigrateUpResult to format
        console: Rich console for output
    """
    if result.success:
        if result.dry_run:
            console.print("[cyan]🔍 Dry-run analysis:[/cyan]")
        else:
            console.print("[green]✅ Successfully applied migrations![/green]")

        if result.migrations_applied:
            console.print(f"\nMigrations: {len(result.migrations_applied)}")
            for migration in result.migrations_applied:
                console.print(
                    f"  • {migration.version}_{migration.name} ({migration.execution_time_ms}ms)"
                )
        else:
            console.print("\n[yellow]No migrations applied[/yellow]")

        if result.total_execution_time_ms > 0:
            console.print(f"\n⏱️ Total time: {result.total_execution_time_ms}ms")

        if result.checksums_verified:
            console.print("[cyan]🔐 Checksums verified[/cyan]")

        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠️ {warning}")
    else:
        console.print(f"[red]❌ Migration failed: {result.error}[/red]")
        if result.migrations_applied:
            console.print(
                f"\n[yellow]⚠️ {len(result.migrations_applied)} migration(s) were applied before failure[/yellow]"
            )


def format_migrate_down_result(
    result: MigrateDownResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate down result in requested format.

    Args:
        result: MigrateDownResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        # Text output to console
        format_down_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["version", "name", "execution_time_ms", "rows_affected"],
            [
                [m.version, m.name, str(m.execution_time_ms), str(m.rows_affected)]
                for m in result.migrations_rolled_back
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_down_text(result: MigrateDownResult, console: Console) -> None:
    """Format migrate down result as rich text for console output.

    Args:
        result: MigrateDownResult to format
        console: Rich console for output
    """
    if result.success:
        console.print("[green]✅ Successfully rolled back migrations![/green]")

        if result.migrations_rolled_back:
            console.print(f"\nMigrations: {len(result.migrations_rolled_back)}")
            for migration in result.migrations_rolled_back:
                console.print(
                    f"  • {migration.version}_{migration.name} ({migration.execution_time_ms}ms)"
                )
        else:
            console.print("\n[yellow]No migrations rolled back[/yellow]")

        if result.total_execution_time_ms > 0:
            console.print(f"\n⏱️ Total time: {result.total_execution_time_ms}ms")

        if result.checksums_verified:
            console.print("[cyan]🔐 Checksums verified[/cyan]")

        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠️ {warning}")
    else:
        console.print(f"[red]❌ Rollback failed: {result.error}[/red]")
        if result.migrations_rolled_back:
            console.print(
                f"\n[yellow]⚠️ {len(result.migrations_rolled_back)} migration(s) were rolled back before failure[/yellow]"
            )
