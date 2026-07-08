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

from rich.markup import escape

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
                    _violation_dict(v) for v in (report.errors + report.warnings + report.info)
                ],
                "hints": [],
            },
            output_file,
            console,
        )
    elif report.has_errors:
        console.print(f"[red]❌ ACL coverage check failed: {len(report.errors)} violation(s)[/red]")
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
                "violations": [_violation_dict(v, include_line=True) for v in report.violations],
            },
            output_file,
            console,
        )
    elif report.violations:
        console.print(
            f"[red]❌ Ownership coverage check failed: {len(report.violations)} violation(s)[/red]"
        )
        for v in report.violations:
            color = "red" if v.severity == RuleSeverity.ERROR else "yellow"
            mark = "✗" if v.severity == RuleSeverity.ERROR else "⚠"
            console.print(
                f"  [{color}]{mark}[/{color}] \\[{v.rule_id}] {v.object_name}: {v.message}"
            )
    else:
        console.print("[green]✅ All migrations have ownership coverage[/green]")


def render_function_uniqueness(report: Any, *, json_mode: bool, output_file: Path | None) -> None:
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
            f"[red]❌ Function uniqueness check failed: {len(report.violations)} violation(s)[/red]"
        )
        for v in report.violations:
            console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
    else:
        console.print("[green]✅ All callables have unique signatures[/green]")


def render_security_definer(report: Any, *, json_mode: bool, output_file: Path | None) -> None:
    """Render the ``--check-security-definer`` result."""
    from confiture.core.linting.schema_linter import RuleSeverity

    if json_mode:
        _output_json(
            {
                "check": "security_definer",
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
            f"[yellow]⚠[/yellow] Security-definer check: {len(report.violations)} violation(s)"
        )
        for v in report.violations:
            color = "red" if v.severity == RuleSeverity.ERROR else "yellow"
            mark = "✗" if v.severity == RuleSeverity.ERROR else "⚠"
            loc = f" ({v.file_path}:{v.line_number})" if v.line_number else ""
            console.print(
                f"  [{color}]{mark}[/{color}] \\[{v.rule_id}] {v.object_name}{loc}: {v.message}"
            )
    else:
        console.print("[green]✅ No unpinned SECURITY DEFINER functions found[/green]")


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


def _print_unified_diff(unified_diff: str) -> None:
    """Print a unified diff with rich-highlighted +/- lines, indented."""
    for line in unified_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            color = "green"
        elif line.startswith("-") and not line.startswith("---"):
            color = "red"
        elif line.startswith("@@"):
            color = "cyan"
        else:
            color = "dim"
        # Escape any Rich markup in the SQL so brackets aren't parsed as tags.
        console.print(f"      [{color}]{escape(line)}[/{color}]")


def _display_body_drift_report(report: Any, *, show_diff: bool = False) -> None:
    """Print a FunctionBodyDriftReport to the console in human-readable form."""
    if not report.has_drift:
        console.print(
            f"[green]✓[/green] 0 function body drift(s) detected "
            f"({report.functions_checked} checked, "
            f"{report.detection_time_ms:.1f}ms)"
        )
        return

    console.print(
        f"[yellow]⚠[/yellow]  {len(report.body_drifts)} function body "
        f"drift(s) detected ({report.functions_checked} checked)"
    )
    for drift in report.body_drifts:
        console.print(f"\n  [bold]{drift.signature_key}[/bold]")
        console.print(f"    Source hash:   [cyan]{drift.source_hash}[/cyan]")
        console.print(f"    Database hash: [red]{drift.db_hash}[/red]")
        if show_diff and drift.unified_diff:
            console.print("    [dim]Unified diff (expected → live, normalised):[/dim]")
            _print_unified_diff(drift.unified_diff)
        console.print(
            "    Hint: function body differs — run "
            "[bold]fix-signatures --apply[/bold] to re-apply from source"
        )


def render_signature_drift(
    drift_report: Any,
    body_report: Any,
    *,
    json_mode: bool,
    output_file: Path | None,
    show_diff: bool = False,
) -> None:
    """Render the ``--check-signatures`` (+ ``--check-body``) result.

    ``show_diff`` (from ``--show-diff``) surfaces each drifted function's bodies
    and unified diff; when ``False`` the output stays hash-only for both JSON and
    text — the historical, terse shape.
    """
    from confiture.cli.formatters.common import display_signature_drift_report

    if json_mode:
        payload: dict[str, Any] = {
            "check": "function_signature_drift",
            **drift_report.to_dict(),
        }
        if body_report is not None:
            payload["body_drift"] = body_report.to_dict(include_bodies=show_diff)
        _output_json(payload, output_file, console)
    else:
        display_signature_drift_report(drift_report, console)
        if body_report is not None:
            _display_body_drift_report(body_report, show_diff=show_diff)


def render_replay_drift(
    body_report: Any,
    *,
    json_mode: bool,
    output_file: Path | None,
    show_diff: bool = False,
) -> None:
    """Render the ``--check-body-replay`` FunctionBodyDriftReport.

    Reuses the function-body report shape (Phase 3) but frames drifts as
    out-of-band hot-patches — definitions live has but a clean migration replay
    does not produce. ``show_diff`` surfaces the expected/live bodies + diff.
    """
    if json_mode:
        _output_json(
            {"check": "replay_body_drift", **body_report.to_dict(include_bodies=show_diff)},
            output_file,
            console,
        )
        return

    if not body_report.has_drift:
        console.print(
            f"[green]✓[/green] 0 out-of-band hot-patch(es) detected "
            f"({body_report.functions_checked} checked, {body_report.detection_time_ms:.1f}ms)"
        )
        return

    console.print(
        f"[yellow]⚠[/yellow]  {len(body_report.body_drifts)} out-of-band hot-patch(es) "
        f"detected ({body_report.functions_checked} checked) — live differs from a clean "
        f"migration replay"
    )
    for drift in body_report.body_drifts:
        console.print(f"\n  [bold]{drift.signature_key}[/bold]")
        console.print(f"    Replayed hash: [cyan]{drift.source_hash}[/cyan]")
        console.print(f"    Database hash: [red]{drift.db_hash}[/red]")
        if show_diff and drift.unified_diff:
            console.print("    [dim]Unified diff (replayed → live, normalised):[/dim]")
            _print_unified_diff(drift.unified_diff)
        console.print(
            "    Hint: no migration produced this body — capture the live change in a "
            "migration, or re-apply the migration-produced definition"
        )


_RELKIND_LABEL = {"v": "view", "m": "materialized view"}


def render_view_drift(
    view_report: Any,
    *,
    json_mode: bool,
    output_file: Path | None,
    show_diff: bool = False,
) -> None:
    """Render the ``--check-body-views`` ViewBodyDriftReport.

    ``show_diff`` (from ``--show-diff``) surfaces each drifted view's expected
    and live definitions plus a unified diff; otherwise output stays hash-only.
    """
    if json_mode:
        _output_json(
            {"check": "view_body_drift", **view_report.to_dict(include_defs=show_diff)},
            output_file,
            console,
        )
        return

    if not view_report.has_drift:
        console.print(
            f"[green]✓[/green] 0 view definition drift(s) detected "
            f"({view_report.views_checked} checked, {view_report.detection_time_ms:.1f}ms)"
        )
        return

    console.print(
        f"[yellow]⚠[/yellow]  {len(view_report.body_drifts)} view definition "
        f"drift(s) detected ({view_report.views_checked} checked)"
    )
    for drift in view_report.body_drifts:
        label = _RELKIND_LABEL.get(drift.relkind, drift.relkind)
        console.print(f"\n  [bold]{drift.schema}.{drift.name}[/bold] [dim]({label})[/dim]")
        console.print(f"    Source hash:   [cyan]{drift.source_hash}[/cyan]")
        console.print(f"    Database hash: [red]{drift.db_hash}[/red]")
        if show_diff and drift.unified_diff:
            console.print("    [dim]Unified diff (expected → live, deparsed):[/dim]")
            _print_unified_diff(drift.unified_diff)
        console.print(
            "    Hint: view definition differs from source — re-apply the committed "
            "DDL or capture the live change in a migration"
        )
