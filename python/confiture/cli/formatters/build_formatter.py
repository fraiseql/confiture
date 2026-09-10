"""Formatter for build command output.

Handles text, JSON, and CSV formatting for build results.
"""

from pathlib import Path

from rich.console import Console

from confiture.cli.formatters.common import handle_output
from confiture.core.builder import PatternDiagnostic, SelectionReport
from confiture.core.linting.inventory import label_for
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
                ["artifact_path", result.artifact_path or ""],
                ["artifact_hash", result.artifact_hash or ""],
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
        if result.artifact_path:
            console.print(f"📦 Artifact: {result.artifact_path}")
        if result.execution_time_ms > 0:
            console.print(f"⏱️ Time: {result.execution_time_ms}ms")
        format_warnings(result, console)
        if result.duplicates:
            console.print(
                f"\n[yellow]Duplicate definitions: {len(result.duplicates)} (see above)[/yellow]"
            )
    else:
        console.print(f"[red]❌ Build failed: {result.error}[/red]")
        format_warnings(result, console)


def format_warnings(result: BuildResult, console: Console) -> None:
    """Print the build's own diagnostics — the only place a `BuildWarning` is rendered.

    A build that stopped is exactly when its warnings are worth reading, so a
    failed result prints them too.

    Args:
        result: The build result whose ``warnings`` to print.
        console: Rich console for output.
    """
    if not result.warnings:
        return
    console.print("\n[yellow]Warnings:[/yellow]")
    for warning in result.warnings:
        style = "yellow" if warning.severity == "warning" else "dim"
        console.print(f"  [{style}]{warning.code} {warning.message}[/{style}]", soft_wrap=True)


def selection_payload(report: SelectionReport, project_dir: Path | None) -> dict:
    """The ``--list-files`` payload: the selection, named the way a finding names a file.

    Args:
        report: What the build would read.
        project_dir: Project root; paths under it are named relative to it.

    Returns:
        ``{env, files: [{path, entry, order, pattern}], total}``.
    """
    return {
        "env": report.env,
        "files": [
            {
                "path": label_for(selected.path, project_dir),
                "entry": label_for(selected.entry, project_dir),
                "order": selected.order,
                "pattern": selected.pattern,
            }
            for selected in report.files
        ],
        "total": len(report.files),
    }


def format_selection_report(
    report: SelectionReport,
    format_type: str,
    project_dir: Path | None,
    console: Console,
) -> None:
    """Print what the build would read; nothing is built.

    Args:
        report: What the build would read.
        format_type: Output format ('text', 'json', or 'csv').
        project_dir: Project root, for naming files relative to it.
        console: Rich console for output.
    """
    payload = selection_payload(report, project_dir)
    if format_type == "text":
        console.print(
            f"{payload['total']} file(s) selected for env '{payload['env']}' — nothing was built",
            soft_wrap=True,
        )
        for entry in payload["files"]:
            console.print(
                f"  {entry['path']}  ← {entry['entry']} · "
                f"order {entry['order']} · {entry['pattern']}",
                soft_wrap=True,
            )
        return

    csv_data = (
        ["path", "entry", "order", "pattern"],
        [
            [entry["path"], entry["entry"], str(entry["order"]), entry["pattern"]]
            for entry in payload["files"]
        ],
    )
    handle_output(format_type, payload, csv_data, None, console)


def format_pattern_notes(
    notes: list[PatternDiagnostic], project_dir: Path | None, console: Console
) -> None:
    """Say which configured patterns select a different set of files than they did.

    Args:
        notes: The diagnostics `SchemaBuilder.pattern_diagnostics()` returned.
        project_dir: Project root, for naming the entry relative to it.
        console: Rich console for output.
    """
    for note in notes:
        style = "yellow" if note.code == "CONFIG_013" else "dim"
        console.print(
            f"[{style}]{note.code} {label_for(note.entry, project_dir)}: {note.message}[/{style}]",
            soft_wrap=True,
        )
