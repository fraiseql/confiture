"""``migrate validate --idempotent`` / ``migrate fix --idempotent``: scoping, reporting and fixing."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from confiture.cli.helpers import _emit_hint, console, emit
from confiture.cli.markup import verbatim
from confiture.core.idempotency import IdempotencyFixer, IdempotencyValidator
from confiture.core.idempotency.collect import collect_report
from confiture.core.idempotency.python_migration_extractor import (
    is_migration_file as _is_migration_file,
)
from confiture.core.idempotency.verdict import judge
from confiture.core.validation.scope import read_staged_content, scope_to_git
from confiture.error_codes import FINDINGS
from confiture.url_redaction import (
    redact_url as redact_url,  # noqa: PLC0414 — explicit re-export (layering)
)


def _idempotent_backend_banner(format_output: str) -> dict[str, Any]:
    """Report which idempotency backend is active.

    Text mode prints a one-line banner to ``console`` (stdout) — it's a
    status line, not an error. JSON / CSV / YAML modes print *nothing*:
    the backend is reported via ``payload["meta"]["backend"]`` so that
    pipe-able output stays valid.

    Returns:
        A ``meta`` dict the caller folds into its JSON payload: always
        ``{"backend": "ast"}``.
    """
    # One parser: the AST backend is the only backend. ``backend`` stays in
    # ``meta`` because the payload contract carries it.
    if format_output == "text":
        console.print("[green]✓ AST backend (pglast)[/green]")
    return {"backend": "ast"}


def _report_empty_scope(
    scope_meta: dict[str, Any],
    migrations_dir: Path,
    meta: dict[str, Any],
    format_output: str,
) -> dict[str, Any] | None:
    """Report "nothing in scope changed" — a real success, distinct from "no files".

    Deliberately *not* the empty-directory message: the remedies differ. An
    empty directory usually means ``--migrations-dir`` points somewhere wrong;
    an empty scope means the branch genuinely touched no migrations.

    Emits ``oneOf`` branch 2 of ``migrate-validate-idempotent.schema.json``
    verbatim (both top-level branches set ``additionalProperties: false``, and
    branch 2 forbids the scan counters), varying only the ``message`` string.
    """
    if scope_meta["mode"] == "staged":
        message = f"No staged migration files in `{migrations_dir}` — nothing to validate."
    else:
        message = (
            f"No migration files in `{migrations_dir}` changed since "
            f"{scope_meta['base_ref']} — nothing to validate. "
            f"({scope_meta['files_skipped']} unchanged file(s) skipped.)"
        )

    hints: list[dict[str, Any]] = []
    _emit_hint(message, hints_list=hints, format_=format_output)

    if format_output == "json":
        return {
            "status": "ok",
            "message": message,
            "violations": [],
            "analysis_complete": True,
            "unanalyzed_count": 0,
            "meta": meta,
            "hints": hints,
        }
    console.print(f"[green]✅ {verbatim(message)}[/green]")
    return None


@dataclass(frozen=True)
class IdempotencyOutcome:
    """What one ``--idempotent`` run decided, for the check registry to compose.

    Attributes:
        passed: False when the gate should fail — a blocking violation, an
            info finding under ``--strict-cor``, or an unverified call under
            ``--fail-on-unanalyzable``.
        payload: The JSON document in JSON mode, else ``None``.
        exit_code: The code this run signals when it does not pass: ``FINDINGS``,
            an unverified call under ``--fail-on-unanalyzable`` included. The exit
            table is frozen at 0–8 and shared with the fraisier adapters, so
            "completed, N unverified" has no code of its own (#213).
    """

    passed: bool
    payload: dict[str, Any] | None
    exit_code: int = FINDINGS


def _validate_idempotency(
    migrations_dir: Path,
    format_output: str,
    *,
    strict_cor: bool = False,
    fail_on_unanalyzable: bool = False,
    base_ref: str | None = None,
    staged: bool = False,
) -> IdempotencyOutcome:
    """Validate idempotency of SQL and Python migration files.

    Args:
        migrations_dir: Directory containing migration files
        format_output: Output format (text or json)
        strict_cor: If True, info-severity CREATE OR REPLACE findings flip
            the exit code to 1 (default False — info findings render but
            don't fail the gate).
        fail_on_unanalyzable: If True, a run that could not read every
            ``execute``/``execute_file`` call fails with
            ``FINDINGS`` (default False — the verdict says
            *unverified* but the exit code stays 0, #213).
        base_ref: Scope to migrations changed since this git ref. ``None``
            means scan everything — the caller must pass ``None`` unless the
            operator set ``--base-ref``/``--since`` *explicitly*, since the
            option's own default (``origin/main``) is truthy and would
            otherwise scope every run (#181).
        staged: Scope to staged migrations, reading the index blob rather than
            the working tree. Takes precedence over ``base_ref``.

    Returns:
        An :class:`IdempotencyOutcome`. Text-mode output is printed here; the
        JSON payload is returned rather than written, because ``migrate
        validate`` composes checks and emits one document for the whole run
        (#187).
    """

    validator = IdempotencyValidator()

    # Backend banner (text) + meta accumulator (json) — printed before
    # file enumeration so users see which detector is running. The flag is
    # recorded on every shape so a consumer can tell "unverified, exit 1"
    # from "unverified, exit 0" without knowing the command line.
    meta = _idempotent_backend_banner(format_output)
    meta["fail_on_unanalyzable"] = fail_on_unanalyzable

    sql_files = sorted(migrations_dir.glob("*.up.sql"))
    py_files = sorted(p for p in migrations_dir.glob("*.py") if _is_migration_file(p))

    scope_meta: dict[str, Any] | None = None
    staged_content: dict[Path, str] = {}
    if staged or base_ref is not None:
        candidates = sql_files + py_files
        selected, scope_meta = scope_to_git(
            candidates, migrations_dir, base_ref=base_ref, staged=staged
        )
        meta["scope"] = scope_meta
        selected_set = {p.resolve() for p in selected}
        sql_files = [p for p in sql_files if p.resolve() in selected_set]
        py_files = [p for p in py_files if p.resolve() in selected_set]

        if staged:
            staged_content = read_staged_content(selected)

        if not sql_files and not py_files:
            return IdempotencyOutcome(
                True, _report_empty_scope(scope_meta, migrations_dir, meta, format_output)
            )

        if format_output == "text":
            where = (
                "staged"
                if scope_meta["mode"] == "staged"
                else f"changed since {scope_meta['base_ref']}"
            )
            console.print(
                f"[cyan]🔍 Scoped to {verbatim(scope_meta['files_selected'])} migration(s) "
                f"{verbatim(where)} ({verbatim(scope_meta['files_skipped'])} skipped)[/cyan]"
            )

    if not sql_files and not py_files:
        # Quiet-success ambiguity: "no migrations" can mean the user
        # intentionally validated an empty directory, but more often
        # they pointed --migrations-dir at the wrong path. Emit a hint
        # to make the success state legible to agents.
        zero_files_hints: list[str] = []
        _emit_hint(
            f"Migration directory `{migrations_dir}` exists but contains no files. "
            "Did you mean to pass --migrations-dir <other>?",
            hints_list=zero_files_hints,
            format_=format_output,
        )
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "violations": [],
                "analysis_complete": True,
                "unanalyzed_count": 0,
                "meta": meta,
                "hints": zero_files_hints,
            }
            return IdempotencyOutcome(True, result)
        console.print("[green]✅ No migration files found to validate[/green]")
        return IdempotencyOutcome(True, None)

    combined_report = collect_report(sql_files, py_files, validator, staged_content=staged_content)
    verdict = judge(
        combined_report, strict_cor=strict_cor, fail_on_unanalyzable=fail_on_unanalyzable
    )
    fail = not verdict.passed

    if format_output == "json":
        result = combined_report.to_dict()
        result["status"] = verdict.status
        result["meta"] = meta
        result["hints"] = []
        return IdempotencyOutcome(verdict.passed, result, verdict.exit_code)

    blocking = [v for v in combined_report.violations if v.severity == "error"]
    info = [v for v in combined_report.violations if v.severity == "info"]

    _render_idempotency_headline(combined_report, fail=fail, strict_cor=strict_cor)

    if blocking:
        _render_violations_by_file(blocking)

    if info:
        qualifier = (
            "blocking under --strict-cor" if strict_cor else "informational, do not fail the gate"
        )
        console.print(
            f"\n[yellow]ℹ️  {len(info)} heuristic note(s) ({verbatim(qualifier)})[/yellow]\n"
        )
        _render_violations_by_file(info)
        if not strict_cor:
            console.print("[dim]Pass --strict-cor to treat these as blocking.[/dim]\n")

    _render_extractor_warnings(combined_report)

    if blocking:
        console.print("[cyan]To auto-fix .sql files, run:[/cyan]")
        console.print(
            f"[cyan]  confiture migrate fix --idempotent --migrations-dir {verbatim(migrations_dir)}[/cyan]"
        )
        console.print("[cyan]For .py migrations, edit them manually.[/cyan]")

    return IdempotencyOutcome(verdict.passed, None, verdict.exit_code)


def _unverified_summary(report: Any) -> str:
    """The one sentence every renderer uses for calls the analyzer did not read."""
    return f"{report.unanalyzed_count} call(s) unverified — idempotency not established"


def _render_idempotency_headline(report: Any, *, fail: bool, strict_cor: bool) -> None:
    """Print the verdict line for an idempotency run — the only place that decides it.

    Precedence: blocking violations, then info findings promoted by
    ``--strict-cor``, then calls the analyzer could not read, then the green
    line. The green line is printed only when every call was read and nothing
    was found: "checked and clean" is a different answer from "could not
    check", so the two never share a headline (#213). One renderer decides it,
    because two would disagree as soon as one branch changed.

    Args:
        report: The merged :class:`IdempotencyReport`.
        fail: What the caller decided the exit code is — computed once from
            severity, ``strict_cor`` and ``--fail-on-unanalyzable``.
            The renderer never re-derives it.
        strict_cor: Whether info findings are blocking this run.
    """
    blocking = [v for v in report.violations if v.severity == "error"]
    info = [v for v in report.violations if v.severity == "info"]
    unverified = _unverified_summary(report)

    if blocking:
        console.print(f"[red]❌ Found {len(blocking)} idempotency violation(s)[/red]")
        if not report.analysis_complete:
            console.print(f"[yellow]   {verbatim(unverified)}[/yellow]")
        console.print()
        return

    if info and strict_cor:
        console.print(
            f"[red]❌ Found {len(info)} heuristic note(s) — blocking under --strict-cor[/red]"
        )
    elif not report.analysis_complete:
        style, icon = ("red", "❌") if fail else ("yellow", "⚠️ ")
        console.print(f"[{style}]{verbatim(icon)} {verbatim(unverified)}[/{style}]")
    else:
        console.print("[green]✅ All migrations are idempotent[/green]")

    scanned = f"   Scanned {report.files_scanned} file(s)"
    if info and strict_cor and not report.analysis_complete:
        scanned += f" · {unverified}"
    console.print(scanned)


def _render_violations_by_file(violations: list[Any]) -> None:
    """Render violations grouped by file (shared by error + info sections)."""
    by_file: dict[str, list[Any]] = {}
    for violation in violations:
        by_file.setdefault(violation.file_path, []).append(violation)
    for file_path, group in by_file.items():
        file_name = Path(file_path).name
        console.print(f"[yellow]{verbatim(file_name)}[/yellow]")
        for v in group:
            location = (
                f"Line {v.source_line} (SQL line {v.line_number})"
                if v.source_line is not None
                else f"Line {v.line_number}"
            )
            console.print(f"  {verbatim(location)}: {verbatim(v.pattern.value)}")
            console.print(
                f"    [dim]{v.sql_snippet[:60]}...[/dim]"
                if len(v.sql_snippet) > 60
                else f"    [dim]{v.sql_snippet}[/dim]"
            )
            console.print(f"    💡 {verbatim(v.suggestion)}")
        console.print()


def _render_extractor_warnings(report: Any) -> None:
    """Render extractor warnings (dynamic SQL the validator couldn't reach)."""
    if not report.has_warnings:
        return
    console.print(
        f"[yellow]⚠️  {len(report.warnings)} dynamic SQL call(s) "
        "could not be statically analyzed:[/yellow]"
    )
    for warn in report.warnings:
        source = Path(str(warn.source_file)).name
        console.print(
            f"  {verbatim(source)}:{verbatim(warn.source_line)} — {verbatim(warn.kind.value)}"
        )
        console.print(f"    [dim]{verbatim(warn.message)}[/dim]")
        if getattr(warn, "remedy", ""):
            console.print(f"    [dim]→ {verbatim(warn.remedy)}[/dim]")
    console.print("    [dim]These calls were skipped. Idempotency cannot be guaranteed.[/dim]")
    console.print()


def _fix_sql_files(sql_files: list[Path], fixer: Any, *, dry_run: bool) -> list[dict[str, Any]]:
    """Rewrite each ``.up.sql`` the fixer changes (or only describe it under ``dry_run``)."""
    files_changed: list[dict[str, Any]] = []
    for sql_file in sql_files:
        original_content = sql_file.read_text()
        fixed_content = fixer.fix(original_content)

        if fixed_content != original_content:
            changes = fixer.dry_run(original_content)
            file_info: dict[str, Any] = {
                "file": sql_file.name,
                "changes": [
                    {
                        "pattern": c.pattern.value,
                        "original": c.original[:50] + "..." if len(c.original) > 50 else c.original,
                        "suggested_fix": c.suggested_fix[:50] + "..."
                        if len(c.suggested_fix) > 50
                        else c.suggested_fix,
                        "line": c.line_number,
                    }
                    for c in changes
                ],
            }
            files_changed.append(file_info)
            if not dry_run:
                sql_file.write_text(fixed_content)
    return files_changed


def _render_fix_text(
    files_changed: list[dict[str, Any]],
    manual_fix_required: list[str],
    py_violations_by_file: dict[str, list[Any]],
    manual_report: Any,
    *,
    dry_run: bool,
) -> None:
    """The text report of ``migrate fix --idempotent``: applied fixes, manual work, warnings."""
    if not files_changed and not manual_fix_required:
        if manual_report.analysis_complete:
            console.print("[green]✅ All migrations are already idempotent[/green]")
        else:
            console.print(f"[yellow]⚠️  {verbatim(_unverified_summary(manual_report))}[/yellow]")
        _render_extractor_warnings(manual_report)
        return

    if files_changed:
        if dry_run:
            console.print("[cyan]📋 DRY-RUN: Would apply the following fixes:[/cyan]\n")
        else:
            console.print("[green]✅ Applied idempotency fixes:[/green]\n")

        for file_info in files_changed:
            console.print(f"[yellow]{verbatim(file_info['file'])}[/yellow]")
            for change in file_info["changes"]:
                console.print(f"  Line {verbatim(change['line'])}: {verbatim(change['pattern'])}")
                console.print(f"    - {verbatim(change['original'])}")
                console.print(f"    + {verbatim(change['suggested_fix'])}")
            console.print()

    if manual_fix_required:
        console.print(
            "[yellow]Python migrations cannot be auto-fixed; "
            "please edit the following files manually:[/yellow]"
        )
        for file_path in manual_fix_required:
            file_name = Path(file_path).name
            console.print(f"[yellow]  • {verbatim(file_name)}[/yellow]")
            for v in py_violations_by_file[file_path]:
                location = (
                    f"line {v.source_line}"
                    if v.source_line is not None
                    else f"line {v.line_number}"
                )
                console.print(
                    f"    {verbatim(location)}: {verbatim(v.pattern.value)} — 💡 {verbatim(v.suggestion)}"
                )
        console.print()

    _render_extractor_warnings(manual_report)

    if files_changed and dry_run:
        console.print(f"[cyan]Would fix {len(files_changed)} file(s)[/cyan]")
        console.print("[cyan]Run without --dry-run to apply changes[/cyan]")
    elif files_changed:
        console.print(f"[green]Fixed {len(files_changed)} file(s)[/green]")


def _fix_idempotency(
    migrations_dir: Path,
    dry_run: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Fix idempotency issues in SQL migration files.

    Python migrations are never rewritten — unparsing the AST would lose
    comments and formatting. Any violations in ``.py`` files are surfaced
    under ``manual_fix_required`` so users know to edit them by hand.

    Args:
        migrations_dir: Directory containing migration files
        dry_run: If True, preview changes without modifying files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """

    fixer = IdempotencyFixer()
    validator = IdempotencyValidator()

    sql_files = sorted(migrations_dir.glob("*.up.sql"))
    py_files = sorted(p for p in migrations_dir.glob("*.py") if _is_migration_file(p))

    if not sql_files and not py_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "files": [],
                "hints": [],
            }
            emit(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to fix[/green]")
        return

    files_changed = _fix_sql_files(sql_files, fixer, dry_run=dry_run)

    # Surface .py violations without rewriting the source.
    manual_report = collect_report([], py_files, validator)
    py_violations_by_file: dict[str, list[Any]] = {}
    for violation in manual_report.violations:
        py_violations_by_file.setdefault(violation.file_path, []).append(violation)
    manual_fix_required = sorted(py_violations_by_file.keys())

    if format_output == "json":
        status = (
            "fixed"
            if not dry_run and (files_changed or manual_fix_required)
            else "preview"
            if dry_run
            else "ok"
        )
        result = {
            "status": status,
            "files": files_changed,
            "total_files_changed": len(files_changed),
            "manual_fix_required": manual_fix_required,
            "hints": [],
        }
        if manual_report.has_warnings:
            result["warnings"] = manual_report.to_dict()["warnings"]
        emit(result, output_file, console)
        return

    _render_fix_text(
        files_changed,
        manual_fix_required,
        py_violations_by_file,
        manual_report,
        dry_run=dry_run,
    )
