"""Formatter for seed apply command output.

Handles text, JSON, and CSV formatting for seed application results.
"""

from pathlib import Path

from rich.console import Console

from confiture.cli.formatters.common import handle_output
from confiture.core.seed_applier import ApplyResult


def format_apply_result(
    result: ApplyResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format seed apply result in requested format.

    Args:
        result: ApplyResult to format
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
                ["total", str(result.total)],
                ["succeeded", str(result.succeeded)],
                ["failed", str(result.failed)],
                ["success", str(result.failed == 0)],
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_text(result: ApplyResult, console: Console) -> None:
    """Format seed apply result as rich text for console output.

    Args:
        result: ApplyResult to format
        console: Rich console for output
    """
    console.print("\n" + "=" * 50)
    console.print(f"Applied {result.succeeded}/{result.total} seed files")

    if result.failed > 0:
        console.print(f"[yellow]⚠️  {result.failed} files failed[/yellow]")
        for failed_file in result.failed_files:
            console.print(f"  - {failed_file}")
    elif result.total > 0:
        console.print("[green]✅ All seed files applied successfully[/green]")
    else:
        console.print("[yellow]No seed files to apply[/yellow]")

    console.print("=" * 50)
