"""``migrate validate --idempotent`` / ``migrate fix --idempotent``: scoping, reporting and fixing."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from confiture.cli.helpers import _emit_hint, _output_json, console
from confiture.core.idempotency.python_migration_extractor import (
    is_migration_file as _is_migration_file,
)
from confiture.core.url_redaction import redact_url as redact_url  # re-export (layering)
from confiture.exceptions import ConfigurationError


def _repo_root_for(path: Path) -> Path:
    """Resolve the project root that owns ``path``, for extractor boundaries.

    Delegates to the extractor's own anchor search so a staged ``.py``
    migration analyzed from a temp file gets the same ``execute_file``
    boundary it would have had on disk.
    """
    from confiture.core.sql_path import find_project_root

    return find_project_root(path)


def _collect_idempotency_report(
    sql_files: list[Path],
    py_files: list[Path],
    validator: Any,
    project_root: Path | None = None,
    staged_content: dict[Path, str] | None = None,
) -> Any:
    """Run the idempotency validator against .sql files and Python migrations.

    Returns a merged :class:`IdempotencyReport`. Python-origin violations
    carry the ``source_line`` of the originating ``self.execute()`` call;
    extractor warnings ride on the report's ``warnings`` list.

    ``project_root`` is forwarded to the extractor for ``execute_file``
    path-boundary checking; passing ``None`` lets the extractor auto-detect
    the root (the nearest ancestor with ``pyproject.toml``, ``.git``, or
    ``db/``).

    ``staged_content`` maps a path to its **staging-index** blob. When a path
    is present there, that content is analyzed instead of the working tree —
    the two differ when a file is staged and then edited further, and a
    pre-commit gate must judge what is about to be committed (#181). The
    blob is analyzed *as the file at that path*: ``Path(__file__)`` and
    migration-relative reads resolve where the migration lives, not in a
    temp directory (0.46.0).
    """
    from confiture.core.idempotency.models import IdempotencyReport
    from confiture.core.idempotency.python_migration_extractor import (
        ExtractionWarning,
        extract_sql_from_python_migration,
        extract_sql_from_python_source,
    )

    combined = IdempotencyReport()
    staged_content = staged_content or {}

    for sql_path in sorted(sql_files):
        if sql_path in staged_content:
            file_report = validator.validate_sql(staged_content[sql_path], file_path=str(sql_path))
        elif sql_path.is_file():
            file_report = validator.validate_file(sql_path)
        else:
            continue
        for scanned in file_report.scanned_files:
            combined.add_file_scanned(scanned)
        for violation in file_report.violations:
            combined.add_violation(violation)
        combined.warnings.extend(file_report.warnings)

    for py_path in sorted(py_files):
        if py_path in staged_content:
            extraction = extract_sql_from_python_source(
                staged_content[py_path],
                path=py_path,
                project_root=project_root or _repo_root_for(py_path),
            )
        else:
            extraction = extract_sql_from_python_migration(py_path, project_root=project_root)
        combined.add_file_scanned(str(py_path))
        combined.warnings.extend(extraction.warnings)
        for snippet in extraction.snippets:
            snippet_report = validator.validate_sql(snippet.sql, file_path=str(py_path))
            for violation in snippet_report.violations:
                violation.source_line = snippet.source_line
                combined.add_violation(violation)
            for warning in snippet_report.warnings:
                combined.warnings.append(
                    ExtractionWarning(
                        kind=warning.kind,
                        source_file=py_path,
                        source_line=snippet.source_line,
                        message=warning.message,
                        reason_code=warning.reason_code,
                        remedy=warning.remedy,
                    )
                )

    combined.scanned_files.sort()
    return combined


def _scope_files_to_git(
    candidates: list[Path],
    migrations_dir: Path,
    *,
    base_ref: str | None,
    staged: bool,
) -> tuple[list[Path], dict[str, Any]]:
    """Narrow ``candidates`` to the files changed on this branch or staged (#181).

    Intersects **glob ∩ diff** rather than iterating the diff, which makes
    deletions safe by construction: a deleted migration appears in the diff but
    not in the glob, so it is never handed to the analyzer.

    Args:
        candidates: The full globbed file set (already on disk).
        migrations_dir: The directory those files were globbed from.
        base_ref: Git ref to scope against, or None when ``staged``.
        staged: Scope to the staging index instead of a ref comparison.

    Returns:
        ``(selected_files, scope_meta)``.

    Raises:
        GitError: ``GIT_003`` when the base ref is unreachable in this
            checkout, or the diff cannot be computed.
        NotAGitRepositoryError: ``GIT_002`` when not in a git repository.
        ConfigurationError: When ``migrations_dir`` lies outside the repository,
            where the intersection could only ever be empty.
    """
    from confiture.core.git import GitRepository

    repo = GitRepository()
    if not repo.is_git_repo():
        from confiture.exceptions import NotAGitRepositoryError

        raise NotAGitRepositoryError(
            f"Not a git repository: {Path.cwd()}",
            resolution_hint=(
                "--base-ref/--since/--staged scope against git history. Run from "
                "inside a repository, or drop the flag to scan every migration."
            ),
        )

    # `git diff --name-only` reports paths relative to the repository ROOT
    # regardless of the directory git runs in, so they must be resolved against
    # the root — not against cwd. Getting this wrong yields an empty
    # intersection and a green gate that scanned nothing.
    repo_root = repo.get_repo_root().resolve()

    resolved_dir = migrations_dir.resolve()
    if not resolved_dir.is_relative_to(repo_root):
        raise ConfigurationError(
            f"Cannot scope by git: migrations directory {resolved_dir} is outside "
            f"the repository at {repo_root}",
            error_code="CONFIG_004",
            resolution_hint=(
                "Point --migrations-dir at a directory inside the repository, or "
                "drop --base-ref/--since/--staged to scan every migration."
            ),
        )

    scope_meta: dict[str, Any]
    if staged or base_ref is None:
        changed = repo.get_staged_files()
        scope_meta = {"mode": "staged"}
    else:
        # Preflight the ref so an unfetched origin/main names its own remedy
        # rather than surfacing git's wording.
        repo.require_ref(base_ref)
        # Merge-base + two-dot rather than three-dot: equivalent whenever a
        # merge base exists, and survives shallow clones, where three-dot fails
        # with "no merge base". get_merge_base already degrades to base_ref.
        anchor = repo.get_merge_base(base_ref, "HEAD") or base_ref
        changed = repo.get_changed_files_two_dot(anchor, "HEAD")
        scope_meta = {"mode": "base-ref", "base_ref": base_ref}

    changed_abs = {(repo_root / path).resolve() for path in changed}
    selected = [path for path in candidates if path.resolve() in changed_abs]

    scope_meta["files_selected"] = len(selected)
    scope_meta["files_skipped"] = len(candidates) - len(selected)
    return selected, scope_meta


def _idempotent_backend_banner(format_output: str) -> dict[str, Any]:
    """Report which idempotency backend is active.

    Text mode prints a one-line banner to ``console`` (stdout) — it's a
    status line, not an error. JSON / CSV / YAML modes print *nothing*:
    the backend is reported via ``payload["meta"]["backend"]`` so that
    pipe-able output stays valid.

    Returns:
        A ``meta`` dict the caller folds into its JSON payload. Always
        contains ``{"backend": "ast" | "regex"}``.
    """
    from confiture.core.idempotency.patterns import _force_regex

    # pglast is a dependency (D13): the regex backend runs only when forced.
    backend = "regex" if _force_regex() else "ast"
    if format_output == "text":
        if backend == "ast":
            console.print("[green]✓ AST backend (pglast)[/green]")
        else:
            console.print(
                "[yellow]⚠ Regex backend forced (CONFITURE_IDEMPOTENCY_FORCE_REGEX) — "
                "this escape hatch is removed with the backend[/yellow]"
            )
    return {"backend": backend}


def _read_staged_content(paths: list[Path]) -> dict[Path, str]:
    """Read each path's blob from the staging index (``git show :<path>``).

    The index blob is what is about to be committed; it differs from the
    working tree whenever a file was staged and then edited further. A
    pre-commit gate must judge the former.
    """
    from confiture.core.git import GitRepository

    repo = GitRepository()
    repo_root = repo.get_repo_root().resolve()

    content: dict[Path, str] = {}
    for path in paths:
        rel = path.resolve().relative_to(repo_root)
        blob = repo.get_staged_file_content(rel)
        if blob is not None:
            content[path] = blob
    return content


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
    console.print(f"[green]✅ {message}[/green]")
    return None


UNANALYZABLE_EXIT_CODE = 1


@dataclass(frozen=True)
class IdempotencyOutcome:
    """What one ``--idempotent`` run decided, for the check registry to compose.

    Attributes:
        passed: False when the gate should fail — a blocking violation, an
            info finding under ``--strict-cor``, or an unverified call under
            ``--fail-on-unanalyzable``.
        payload: The JSON document in JSON mode, else ``None``.
        exit_code: The code this run signals when it does not pass.
    """

    passed: bool
    payload: dict[str, Any] | None
    exit_code: int = 1


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
            :data:`UNANALYZABLE_EXIT_CODE` (default False — the verdict says
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
    from confiture.core.idempotency import IdempotencyValidator

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
        selected, scope_meta = _scope_files_to_git(
            candidates, migrations_dir, base_ref=base_ref, staged=staged
        )
        meta["scope"] = scope_meta
        selected_set = {p.resolve() for p in selected}
        sql_files = [p for p in sql_files if p.resolve() in selected_set]
        py_files = [p for p in py_files if p.resolve() in selected_set]

        if staged:
            staged_content = _read_staged_content(selected)

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
                f"[cyan]🔍 Scoped to {scope_meta['files_selected']} migration(s) "
                f"{where} ({scope_meta['files_skipped']} skipped)[/cyan]"
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

    combined_report = _collect_idempotency_report(
        sql_files, py_files, validator, staged_content=staged_content
    )
    violation_fail = (
        combined_report.has_violations if strict_cor else combined_report.has_blocking_violations
    )
    unverified_fail = fail_on_unanalyzable and not combined_report.analysis_complete
    fail = violation_fail or unverified_fail
    exit_code = UNANALYZABLE_EXIT_CODE if unverified_fail and not violation_fail else 1

    if format_output == "json":
        result = combined_report.to_dict()
        # Violations win; then "could not check" is its own answer, distinct
        # from "checked and clean" (#213). The flag changes the exit code,
        # never the status — the status says what was found.
        if combined_report.has_violations:
            result["status"] = "issues_found"
        elif combined_report.analysis_complete:
            result["status"] = "ok"
        else:
            result["status"] = "unverified"
        result["meta"] = meta
        result["hints"] = []
        return IdempotencyOutcome(not fail, result, exit_code)

    blocking = [v for v in combined_report.violations if v.severity == "error"]
    info = [v for v in combined_report.violations if v.severity == "info"]

    _render_idempotency_headline(combined_report, fail=fail, strict_cor=strict_cor)

    if blocking:
        _render_violations_by_file(blocking)

    if info:
        qualifier = (
            "blocking under --strict-cor" if strict_cor else "informational, do not fail the gate"
        )
        console.print(f"\n[yellow]ℹ️  {len(info)} heuristic note(s) ({qualifier})[/yellow]\n")
        _render_violations_by_file(info)
        if not strict_cor:
            console.print("[dim]Pass --strict-cor to treat these as blocking.[/dim]\n")

    _render_extractor_warnings(combined_report)

    if blocking:
        console.print("[cyan]To auto-fix .sql files, run:[/cyan]")
        console.print(
            f"[cyan]  confiture migrate fix --idempotent --migrations-dir {migrations_dir}[/cyan]"
        )
        console.print("[cyan]For .py migrations, edit them manually.[/cyan]")

    return IdempotencyOutcome(not fail, None, exit_code)


def _unverified_summary(report: Any) -> str:
    """The one sentence every renderer uses for calls the analyzer did not read."""
    return f"{report.unanalyzed_count} call(s) unverified — idempotency not established"


def _render_idempotency_headline(report: Any, *, fail: bool, strict_cor: bool) -> None:
    """Print the verdict line for an idempotency run — the only place that decides it.

    Precedence: blocking violations, then info findings promoted by
    ``--strict-cor``, then calls the analyzer could not read, then the green
    line. The green line is printed only when every call was read and nothing
    was found: "checked and clean" is a different answer from "could not
    check", and the two used to print the same headline (#213).

    Two sites rendered this independently before 0.46.0, which is how the
    info-only branch kept the contradiction after the clean branch was noticed.

    Args:
        report: The merged :class:`IdempotencyReport`.
        fail: What the caller decided the exit code is — computed once from
            severity, ``strict_cor`` and (from 0.46.0) ``--fail-on-unanalyzable``.
            The renderer never re-derives it.
        strict_cor: Whether info findings are blocking this run.
    """
    blocking = [v for v in report.violations if v.severity == "error"]
    info = [v for v in report.violations if v.severity == "info"]
    unverified = _unverified_summary(report)

    if blocking:
        console.print(f"[red]❌ Found {len(blocking)} idempotency violation(s)[/red]")
        if not report.analysis_complete:
            console.print(f"[yellow]   {unverified}[/yellow]")
        console.print()
        return

    if info and strict_cor:
        console.print(
            f"[red]❌ Found {len(info)} heuristic note(s) — blocking under --strict-cor[/red]"
        )
    elif not report.analysis_complete:
        style, icon = ("red", "❌") if fail else ("yellow", "⚠️ ")
        console.print(f"[{style}]{icon} {unverified}[/{style}]")
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
        console.print(f"[yellow]{file_name}[/yellow]")
        for v in group:
            location = (
                f"Line {v.source_line} (SQL line {v.line_number})"
                if v.source_line is not None
                else f"Line {v.line_number}"
            )
            console.print(f"  {location}: {v.pattern.value}")
            console.print(
                f"    [dim]{v.sql_snippet[:60]}...[/dim]"
                if len(v.sql_snippet) > 60
                else f"    [dim]{v.sql_snippet}[/dim]"
            )
            console.print(f"    💡 {v.suggestion}")
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
        console.print(f"  {source}:{warn.source_line} — {warn.kind.value}")
        console.print(f"    [dim]{warn.message}[/dim]")
        if getattr(warn, "remedy", ""):
            console.print(f"    [dim]→ {warn.remedy}[/dim]")
    console.print("    [dim]These calls were skipped. Idempotency cannot be guaranteed.[/dim]")
    console.print()


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
    from confiture.core.idempotency import IdempotencyFixer, IdempotencyValidator

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
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to fix[/green]")
        return

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

    # Surface .py violations without rewriting the source.
    manual_report = _collect_idempotency_report([], py_files, validator)
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
        _output_json(result, output_file, console)
        return

    if not files_changed and not manual_fix_required:
        if manual_report.analysis_complete:
            console.print("[green]✅ All migrations are already idempotent[/green]")
        else:
            console.print(f"[yellow]⚠️  {_unverified_summary(manual_report)}[/yellow]")
        _render_extractor_warnings(manual_report)
        return

    if files_changed:
        if dry_run:
            console.print("[cyan]📋 DRY-RUN: Would apply the following fixes:[/cyan]\n")
        else:
            console.print("[green]✅ Applied idempotency fixes:[/green]\n")

        for file_info in files_changed:
            console.print(f"[yellow]{file_info['file']}[/yellow]")
            for change in file_info["changes"]:
                console.print(f"  Line {change['line']}: {change['pattern']}")
                console.print(f"    - {change['original']}")
                console.print(f"    + {change['suggested_fix']}")
            console.print()

    if manual_fix_required:
        console.print(
            "[yellow]Python migrations cannot be auto-fixed; "
            "please edit the following files manually:[/yellow]"
        )
        for file_path in manual_fix_required:
            file_name = Path(file_path).name
            console.print(f"[yellow]  • {file_name}[/yellow]")
            for v in py_violations_by_file[file_path]:
                location = (
                    f"line {v.source_line}"
                    if v.source_line is not None
                    else f"line {v.line_number}"
                )
                console.print(f"    {location}: {v.pattern.value} — 💡 {v.suggestion}")
        console.print()

    _render_extractor_warnings(manual_report)

    if files_changed and dry_run:
        console.print(f"[cyan]Would fix {len(files_changed)} file(s)[/cyan]")
        console.print("[cyan]Run without --dry-run to apply changes[/cyan]")
    elif files_changed:
        console.print(f"[green]Fixed {len(files_changed)} file(s)[/green]")
