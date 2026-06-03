"""Rendering for ``confiture migrate validate`` modes.

Each ``render_*`` function takes a typed result (produced by a
``confiture.core.validation`` handler) and writes the human-readable or JSON
form. Collapsing the per-mode ``if format_output == "json"`` branches here keeps
the ``migrate_validate`` dispatcher thin and the output shapes in one place.

These functions never decide exit codes — the dispatcher raises the
success-signal ``typer.Exit(1)`` on findings; genuine failures travel as
``ConfiturError`` to the ``fail()`` boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from confiture.cli.helpers import _output_json, console

if TYPE_CHECKING:
    from pathlib import Path


def _violation_dict(
    violation: Any,
    *,
    include_object_type: bool = False,
    include_line: bool = False,
) -> dict[str, Any]:
    """Serialize one lint violation, matching each check's historical JSON shape."""
    payload: dict[str, Any] = {
        "rule_id": violation.rule_id,
        "severity": violation.severity.value,
        "object_name": violation.object_name,
    }
    if include_object_type:
        payload["object_type"] = violation.object_type
    payload["message"] = violation.message
    payload["file_path"] = violation.file_path
    if include_line:
        payload["line_number"] = violation.line_number
    return payload


def render_acl_coverage(report: Any, *, json_mode: bool, output_file: Path | None) -> None:
    """Render the ``--check-acls`` LintReport."""
    if json_mode:
        _output_json(
            {
                "check": "acl_coverage",
                "violations": [
                    _violation_dict(v)
                    for v in (report.errors + report.warnings + report.info)
                ],
                "hints": [],
            },
            output_file,
            console,
        )
    elif report.has_errors:
        console.print(
            f"[red]❌ ACL coverage check failed: {len(report.errors)} violation(s)[/red]"
        )
        for v in report.errors:
            # Escape the rule_id brackets so Rich doesn't read them as markup.
            console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
    else:
        console.print("[green]✅ All migrations have ACL coverage[/green]")


def render_ownership_coverage(report: Any, *, json_mode: bool, output_file: Path | None) -> None:
    """Render the ``--check-ownership-coverage`` result."""
    from confiture.core.linting.schema_linter import RuleSeverity

    if json_mode:
        _output_json(
            {
                "check": "ownership_coverage",
                "violations": [
                    _violation_dict(v, include_line=True) for v in report.violations
                ],
            },
            output_file,
            console,
        )
    elif report.violations:
        console.print(
            f"[red]❌ Ownership coverage check failed: "
            f"{len(report.violations)} violation(s)[/red]"
        )
        for v in report.violations:
            color = "red" if v.severity == RuleSeverity.ERROR else "yellow"
            mark = "✗" if v.severity == RuleSeverity.ERROR else "⚠"
            console.print(
                f"  [{color}]{mark}[/{color}] \\[{v.rule_id}] {v.object_name}: {v.message}"
            )
    else:
        console.print("[green]✅ All migrations have ownership coverage[/green]")


def render_function_uniqueness(
    report: Any, *, json_mode: bool, output_file: Path | None
) -> None:
    """Render the ``--check-function-uniqueness`` result."""
    if json_mode:
        _output_json(
            {
                "check": "function_uniqueness",
                "violations": [
                    _violation_dict(v, include_object_type=True, include_line=True)
                    for v in report.violations
                ],
            },
            output_file,
            console,
        )
    elif report.violations:
        console.print(
            f"[red]❌ Function uniqueness check failed: "
            f"{len(report.violations)} violation(s)[/red]"
        )
        for v in report.violations:
            console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
    else:
        console.print("[green]✅ All callables have unique signatures[/green]")


def render_import_check(result: Any, *, json_mode: bool, output_file: Path | None) -> None:
    """Render the ``--check-imports`` ImportCheckResult."""
    from pathlib import Path as _Path

    if json_mode:
        _output_json({"check": "imports", **result.to_dict()}, output_file, console)
    elif result.success:
        console.print(
            f"[green]✅ All {result.checked} Python migration(s) passed import check[/green]"
        )
        if result.skipped_sql:
            console.print(f"  [dim]({result.skipped_sql} SQL migration(s) skipped)[/dim]")
    else:
        console.print(
            f"[red]❌ Import check failed: {result.failed}/{result.checked} "
            f"file(s) have issues[/red]"
        )
        for v in result.violations:
            console.print(f"  [red]✗[/red] [{v.rule}] {_Path(v.file_path).name}: {v.message}")


def render_live_drift(report: Any, *, json_mode: bool, output_file: Path | None) -> None:
    """Render the ``--check-live-drift`` DriftReport."""
    from confiture.cli.formatters.common import display_drift_report

    if json_mode:
        _output_json({"check": "live_drift", **report.to_dict()}, output_file, console)
    else:
        display_drift_report(report, console)
