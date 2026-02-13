"""Formatter for build command output.

Handles text, JSON, and CSV formatting for build results.
"""

from pathlib import Path

from rich.console import Console

from confiture.cli.formatters.common import handle_output
from confiture.models.results import BuildResult


def format_build_result(
    result: BuildResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format build result in requested format.

    Args:
        result: BuildResult to format
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
            ["metric", "value"],
            [
                ["success", str(result.success)],
                ["files_processed", str(result.files_processed)],
                ["schema_size_bytes", str(result.schema_size_bytes)],
                ["output_path", result.output_path],
                ["hash", result.hash or ""],
                ["execution_time_ms", str(result.execution_time_ms)],
                ["seed_files_applied", str(result.seed_files_applied)],
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_text(result: BuildResult, console: Console) -> None:
    """Format build result as rich text for console output.

    Args:
        result: BuildResult to format
        console: Rich console for output
    """
    if result.success:
        console.print("[green]✅ Schema built successfully![/green]")
        console.print(f"\n📁 Output: {result.output_path}")
        console.print(f"📏 Size: {result.schema_size_bytes:,} bytes")
        console.print(f"📊 Files: {result.files_processed}")
        if result.hash:
            console.print(f"🔐 Hash: {result.hash}")
        if result.seed_files_applied > 0:
            console.print(f"🌱 Seeds: {result.seed_files_applied} files applied")
        if result.execution_time_ms > 0:
            console.print(f"⏱️ Time: {result.execution_time_ms}ms")
        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠️ {warning}")
    else:
        console.print(f"[red]❌ Build failed: {result.error}[/red]")
