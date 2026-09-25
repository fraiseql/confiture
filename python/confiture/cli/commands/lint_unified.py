"""``confiture lint-unified``: Squawk, SQLFluff, the schema linter and the tree rules in one report."""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import (
    console,
    emit,
)
from confiture.cli.markup import verbatim
from confiture.cli.options import (
    env_option,
    format_option,
)
from confiture.core import linting as _core_linting
from confiture.core.builder import files_under
from confiture.core.linting.libraries.generate import tree_violations
from confiture.core.linting.schema_linter import (
    LintConfig as LinterConfig,
)
from confiture.core.linting.schema_linter import (
    LintViolation,
)
from confiture.core.linting.selection import (
    env_ddl_files,
    project_relative,
)
from confiture.core.unified_linter import UnifiedLinter
from confiture.error_codes import FINDINGS, NOT_RUN
from confiture.models.lint import LintSeverity
from confiture.models.unified_lint import SkippedCheck, UnifiedLintIssue, UnifiedLintResult


def _violation_to_unified_issue(v, tool: str):
    """Convert a LintViolation to a UnifiedLintIssue, at the file and line it names."""

    return UnifiedLintIssue(
        tool=tool,
        file=v.file_path or v.object_name,
        line=v.line_number,
        message=v.message,
        severity=LintSeverity(v.severity.value),
        rule=v.rule_id if tool == "tree" else v.rule_name,
    )


def _unified_tree_findings(
    env: str, schema_dir: Path | None, overrides_dir: Path | None
) -> list[LintViolation]:
    """``lint-unified --check tree``'s findings, resolved the way ``lint`` resolves them.

    ``--schema-dir`` names a tree explicitly; without it the environment's own
    include configuration decides, which is what the flag's help has always
    claimed and what ``confiture lint --select tree`` does. Two commands, one
    answer to "which files is this rule about".
    """
    if schema_dir is not None:
        files = files_under(schema_dir) if schema_dir.is_dir() else []
        roots = [schema_dir]
    else:
        files, roots = env_ddl_files(env, Path())
    return [
        project_relative(v, Path())
        for v in tree_violations(files, schema_dirs=roots, overrides_dir=overrides_dir)
    ]


@cli_boundary
def lint_unified(
    files: list[Path] = typer.Argument(
        default=None,
        help="SQL files or directories to lint (default: the schema files --env builds from)",
    ),
    check: list[str] = typer.Option(
        None,
        "--check",
        "-c",
        help="Which checks to run: safety (squawk), format (sqlfluff), schema (SchemaLinter), tree (tree_001–tree_004 file-numbering). "
        "Default: all.",
    ),
    git_diff: bool = typer.Option(
        False,
        "--git-diff",
        help="Only lint files changed in the current git diff (default: off)",
    ),
    env: str = env_option(),
    schema_dir: Path | None = typer.Option(
        None,
        "--schema-dir",
        help="Root of the DDL file tree for --check tree (default: the directories --env's "
        "include_dirs builds from, minus what it excludes).",
    ),
    overrides_dir: Path | None = typer.Option(
        None,
        "--overrides-dir",
        help="Overrides mirror directory for the tree_004 orphan check (optional).",
    ),
    format_type: str = format_option("table", "json"),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found (default: on)",
    ),
) -> None:
    """Run unified SQL lint checks (Squawk, SQLFluff, SchemaLinter, and/or tree numbering).

    Squawk and SQLFluff are not installed with confiture. A check whose tool is
    missing, or which fails, does not run and is not reported clean: it is named
    as skipped, in text and under ``skipped`` in JSON, and the run exits 2 even
    when another check found an error — the report is incomplete. Ask only for
    the checks this environment can run (``--check schema --check tree``).

    EXAMPLES:
      confiture lint-unified db/migrations/
        Lint all SQL files in migrations directory with all available tools.

      confiture lint-unified --check safety
        Run only Squawk safety checks.

      confiture lint-unified --check schema --env local
        Run only SchemaLinter checks on the local environment.

      confiture lint-unified --check tree --schema-dir db/schema/
        Check DDL file-tree numbering rules (tree_001–tree_004): duplicate prefixes,
        verb suffixes, sequence gaps, and orphaned overrides. Without --schema-dir
        the tree is the one --env builds from.

      confiture lint-unified --git-diff
        Lint only SQL files changed in the current git diff.
    """

    checks = list(check) if check else None

    # Handle schema checks separately (uses SchemaLinter)
    run_schema = checks is None or "schema" in (checks or [])
    run_tree = checks is None or "tree" in (checks or [])
    run_tool_checks = checks is None or any(c in (checks or []) for c in ("safety", "format"))

    all_issues: list = []
    skipped: list[SkippedCheck] = []

    if run_tool_checks:
        # No FILES: the schema files the environment builds from, as --help says.
        targets = list(files) if files else (None if git_diff else env_ddl_files(env, Path())[0])
        result = UnifiedLinter().run(files=targets, checks=checks, git_diff=git_diff)
        all_issues.extend(result.issues)
        skipped.extend(result.skipped)

    if run_schema:
        schema_config = LinterConfig(enabled=True, fail_on_error=fail_on_error)
        schema_linter = _core_linting.SchemaLinter(env=env, config=schema_config)
        try:
            linter_report = schema_linter.lint()
            all_issues.extend(
                _violation_to_unified_issue(project_relative(v, Path()), "schema")
                for v in linter_report.errors + linter_report.warnings + linter_report.info
            )
        # Reason: lint-unified skips a linter that fails for any reason and says so
        except Exception as e:
            skipped.append(SkippedCheck("schema", "schema", str(e)))

    if run_tree:
        try:
            all_issues.extend(
                _violation_to_unified_issue(v, "tree")
                for v in _unified_tree_findings(env, schema_dir, overrides_dir)
            )
        # Reason: lint-unified skips a linter that fails for any reason and says so
        except Exception as e:
            skipped.append(SkippedCheck("tree", "tree", str(e)))

    unified_result = UnifiedLintResult(issues=all_issues, skipped=skipped)

    if format_type == "json":
        emit(unified_result.to_dict())
        _exit_on_errors(unified_result, fail_on_error=fail_on_error)
        return
    for skip in unified_result.skipped:
        console.print(
            f"Skipped {skip.check} ({skip.tool}): {skip.reason}", markup=False, style="yellow"
        )
    if not unified_result.issues:
        if unified_result.skipped:
            console.print("No issues found by the checks that ran.", style="yellow")
        else:
            console.print("[green]No issues found.[/green]")
    else:
        for tool, tool_issues in unified_result.by_tool.items():
            console.print(f"\n[bold]{verbatim(tool)}[/bold] ({len(tool_issues)} issue(s)):")
            for issue in tool_issues:
                sev = issue.severity.value.upper()
                loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
                rule = f" [{issue.rule}]" if issue.rule else ""
                # markup=False: every field is data. Rich reads `[tree_001]` as a
                # style tag and prints nothing where the rule id should be — the
                # uppercase codes only survived because they are not style names.
                console.print(f"  [{sev}]{rule} {loc}: {issue.message}", markup=False)

    _exit_on_errors(unified_result, fail_on_error=fail_on_error)


def _exit_on_errors(result: UnifiedLintResult, *, fail_on_error: bool) -> None:
    if result.skipped:
        raise typer.Exit(NOT_RUN)
    if fail_on_error and result.has_errors:
        raise typer.Exit(FINDINGS)  # success-signal: lint found errors
