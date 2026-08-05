"""Rendering for ``confiture migrate validate`` modes.

Each ``render_*`` function takes a typed result (produced by a
``confiture.core.validation`` handler) and either prints the human-readable form
or **returns** the JSON payload. Collapsing the per-mode ``if format_output ==
"json"`` branches here keeps the ``migrate_validate`` dispatcher thin and the
output shapes in one place.

Renderers return their payload rather than writing it (0.40.0, #187): checks
compose now, so a run can produce several payloads and only the runner knows
whether they go out verbatim or wrapped. Emitting from here would produce two
JSON documents on one stdout.

These functions never decide exit codes — the runner aggregates outcomes;
genuine failures travel as ``ConfiturError`` to the ``fail()`` boundary.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape

from confiture.cli.helpers import console


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


def render_acl_coverage(report: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-acls`` LintReport."""
    if json_mode:
        return {
            "check": "acl_coverage",
            "violations": [
                _violation_dict(v) for v in (report.errors + report.warnings + report.info)
            ],
            "hints": [],
        }
    if report.has_errors:
        console.print(f"[red]❌ ACL coverage check failed: {len(report.errors)} violation(s)[/red]")
        for v in report.errors:
            # Escape the rule_id brackets so Rich doesn't read them as markup.
            console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
    else:
        console.print("[green]✅ All migrations have ACL coverage[/green]")
    return None


def render_ownership_coverage(report: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-ownership-coverage`` result."""
    from confiture.core.linting.schema_linter import RuleSeverity

    if json_mode:
        return {
            "check": "ownership_coverage",
            "violations": [_violation_dict(v, include_line=True) for v in report.violations],
        }
    if report.violations:
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
    return None


def render_function_uniqueness(report: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-function-uniqueness`` result."""
    if json_mode:
        return {
            "check": "function_uniqueness",
            "violations": [
                _violation_dict(v, include_object_type=True, include_line=True)
                for v in report.violations
            ],
        }
    if report.violations:
        console.print(
            f"[red]❌ Function uniqueness check failed: {len(report.violations)} violation(s)[/red]"
        )
        for v in report.violations:
            console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
    else:
        console.print("[green]✅ All callables have unique signatures[/green]")
    return None


def render_security_definer(report: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-security-definer`` result."""
    from confiture.core.linting.schema_linter import RuleSeverity

    if json_mode:
        return {
            "check": "security_definer",
            "violations": [
                _violation_dict(v, include_object_type=True, include_line=True)
                for v in report.violations
            ],
        }
    if report.violations:
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
    return None


def render_import_check(result: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-imports`` ImportCheckResult."""
    from pathlib import Path as _Path

    if json_mode:
        return {"check": "imports", **result.to_dict()}
    if result.success:
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
    return None


def render_naming(
    *,
    duplicate_versions: dict[str, list[Any]],
    orphaned_files: list[Any],
    fixed: dict[str, Any] | None,
    json_mode: bool,
    dry_run: bool,
) -> dict[str, Any] | None:
    """Render ``migrate validate``'s default mode: duplicate versions + orphans.

    ``fixed`` is the ``fix_orphaned_sql_files`` result when ``--fix-naming`` ran,
    else ``None``. Duplicate versions are a hard error and pre-empt fixing;
    orphans alone are a warning that still exits 0.
    """
    if duplicate_versions:
        if json_mode:
            payload: dict[str, Any] = {
                "status": "issues_found",
                "duplicate_versions": {
                    v: [f.name for f in files] for v, files in duplicate_versions.items()
                },
            }
            if orphaned_files:
                payload["orphaned_files"] = [f.name for f in orphaned_files]
            return payload
        console.print("[red]❌ Duplicate migration versions detected[/red]")
        console.print("[red]Multiple migration files share the same version number:[/red]\n")
        for version, files in sorted(duplicate_versions.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f.name}")
        console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
        console.print(
            "[yellow]   Use 'confiture migrate generate' to auto-assign the next version.[/yellow]"
        )
        return None

    if not orphaned_files:
        if json_mode:
            return {
                "status": "ok",
                "message": "No orphaned migration files found",
                "fixed": [],
                "errors": [],
            }
        console.print("[green]✅ No orphaned migration files found[/green]")
        return None

    if fixed is not None:
        if json_mode:
            return {
                "status": "preview" if dry_run else "fixed",
                "fixed": fixed.get("renamed", []),
                "errors": fixed.get("errors", []),
            }
        if dry_run:
            console.print("[cyan]📋 DRY-RUN: Would fix the following orphaned files:[/cyan]")
        else:
            console.print("[green]✅ Fixed orphaned migration files:[/green]")
        for old_name, new_name in fixed.get("renamed", []):
            console.print(f"  • {old_name} → {new_name}")
        if fixed.get("errors"):
            console.print("[red]Errors:[/red]")
            for filename, error_msg in fixed.get("errors", []):
                console.print(f"  ❌ {filename}: {error_msg}")
        return None

    if json_mode:
        return {
            "status": "issues_found",
            "orphaned_files": [f.name for f in orphaned_files],
        }
    console.print("[yellow]⚠️  WARNING: Orphaned migration files detected[/yellow]")
    console.print("[yellow]These SQL files exist but won't be applied by Confiture:[/yellow]")
    for orphaned_file in orphaned_files:
        console.print(f"  • {orphaned_file.name} → rename to: {orphaned_file.stem}.up.sql")
    console.print()
    console.print("[cyan]To automatically fix these files, run:[/cyan]")
    console.print("[cyan]  confiture migrate validate --fix-naming[/cyan]")
    console.print()
    console.print("[cyan]Or preview the changes first with:[/cyan]")
    console.print("[cyan]  confiture migrate validate --fix-naming --dry-run[/cyan]")
    return None


def render_live_drift(report: Any, *, json_mode: bool) -> dict[str, Any] | None:
    """Render the ``--check-live-drift`` DriftReport."""
    from confiture.cli.formatters.common import display_drift_report

    if json_mode:
        return {"check": "live_drift", **report.to_dict()}
    display_drift_report(report, console)
    return None


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
    show_diff: bool = False,
) -> dict[str, Any] | None:
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
        return payload

    display_signature_drift_report(drift_report, console)
    if body_report is not None:
        _display_body_drift_report(body_report, show_diff=show_diff)
    return None


def render_replay_drift(
    body_report: Any,
    *,
    json_mode: bool,
    show_diff: bool = False,
) -> dict[str, Any] | None:
    """Render the ``--check-body-replay`` FunctionBodyDriftReport.

    Reuses the function-body report shape (Phase 3) but frames drifts as
    out-of-band hot-patches — definitions live has but a clean migration replay
    does not produce. ``show_diff`` surfaces the expected/live bodies + diff.
    """
    if json_mode:
        return {"check": "replay_body_drift", **body_report.to_dict(include_bodies=show_diff)}

    if not body_report.has_drift:
        console.print(
            f"[green]✓[/green] 0 out-of-band hot-patch(es) detected "
            f"({body_report.functions_checked} checked, {body_report.detection_time_ms:.1f}ms)"
        )
        return None

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
    return None


_RELKIND_LABEL = {"v": "view", "m": "materialized view"}


def render_view_drift(
    view_report: Any,
    *,
    json_mode: bool,
    show_diff: bool = False,
) -> dict[str, Any] | None:
    """Render the ``--check-body-views`` ViewBodyDriftReport.

    ``show_diff`` (from ``--show-diff``) surfaces each drifted view's expected
    and live definitions plus a unified diff; otherwise output stays hash-only.
    """
    if json_mode:
        return {"check": "view_body_drift", **view_report.to_dict(include_defs=show_diff)}

    if not view_report.has_drift:
        console.print(
            f"[green]✓[/green] 0 view definition drift(s) detected "
            f"({view_report.views_checked} checked, {view_report.detection_time_ms:.1f}ms)"
        )
        return None

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
    return None
