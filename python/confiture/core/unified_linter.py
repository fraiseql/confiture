"""Unified SQL linter orchestrating Squawk, SQLFluff, and other tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from confiture.core.builder import files_under
from confiture.models.lint import LintSeverity
from confiture.models.unified_lint import SkippedCheck, UnifiedLintIssue, UnifiedLintResult

#: squawk's ``level`` → the unified severity; anything else is a warning.
_SQUAWK_LEVELS = {"Error": LintSeverity.ERROR, "Warning": LintSeverity.WARNING}


class SquawkRunner:
    """Runs Squawk for PostgreSQL migration safety checks."""

    @property
    def available(self) -> bool:
        """Whether squawk is installed and on PATH."""
        return shutil.which("squawk") is not None

    def run(self, files: list[Path]) -> list[UnifiedLintIssue]:
        """Run squawk on the given SQL files."""
        if not self.available or not files:
            return []
        result = subprocess.run(
            ["squawk", "--reporter=json", "--", *[str(f) for f in files]],
            capture_output=True,
            text=True,
            check=False,
        )
        return self._parse(result.stdout)

    def _parse(self, output: str) -> list[UnifiedLintIssue]:
        """Parse ``squawk --reporter=json`` (2.x): a flat list of findings.

        Each is ``{file, line, rule_name, message, level, …}``, with ``line``
        counted from **0** — the recordings in ``tests/fixtures/unified_lint/``
        are what this is tested on, never a shape written by hand.
        """
        if not output.strip():
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []
        return [
            UnifiedLintIssue(
                tool="squawk",
                file=item.get("file", ""),
                line=item["line"] + 1 if isinstance(item.get("line"), int) else None,
                message=item.get("message", ""),
                severity=_SQUAWK_LEVELS.get(item.get("level", ""), LintSeverity.WARNING),
                rule=item.get("rule_name"),
            )
            for item in data
            if isinstance(item, dict)
        ]


class SQLFluffRunner:
    """Runs SQLFluff for SQL style and formatting checks.

    ``failures`` holds, after :meth:`run`, each file sqlfluff raised on and why:
    a file it could not lint is not a file with no findings.
    """

    def __init__(self) -> None:
        self.failures: list[tuple[str, str]] = []

    @property
    def available(self) -> bool:
        """Whether sqlfluff is installed."""
        try:
            # Reason: optional dependency — extra 'sqlfluff (undeclared, best-effort)'; imported where used so the core never requires it
            import sqlfluff  # noqa: F401  # ty: ignore[unresolved-import]

            return True
        except ImportError:
            return False

    def run(self, files: list[Path], dialect: str = "postgres") -> list[UnifiedLintIssue]:
        """Run sqlfluff on the given SQL files."""
        if not self.available or not files:
            return []
        # Reason: optional dependency — extra 'sqlfluff (undeclared, best-effort)'; imported where used so the core never requires it
        from sqlfluff.api import simple  # ty: ignore[unresolved-import]

        issues = []
        self.failures = []
        for f in files:
            try:
                issues.extend(self.parse(str(f), simple.lint(f.read_text(), dialect=dialect)))
            # Reason: sqlfluff is an optional third-party linter; a file it fails on is reported, never fatal
            except Exception as e:
                self.failures.append((str(f), str(e)))
        return issues

    @staticmethod
    def parse(file: str, violations: list[dict]) -> list[UnifiedLintIssue]:
        """``simple.lint``'s findings for *file*; the line is ``start_line_no`` (4.x) or ``line_no``."""
        return [
            UnifiedLintIssue(
                tool="sqlfluff",
                file=file,
                line=violation.get("start_line_no", violation.get("line_no")),
                message=violation.get("description", ""),
                severity=LintSeverity.WARNING,
                rule=violation.get("code"),
            )
            for violation in violations
        ]


class UnifiedLinter:
    """Orchestrates multiple SQL linting tools."""

    def __init__(
        self,
        squawk: SquawkRunner | None = None,
        sqlfluff: SQLFluffRunner | None = None,
    ) -> None:
        self._squawk = squawk or SquawkRunner()
        self._sqlfluff = sqlfluff or SQLFluffRunner()

    def _get_changed_sql_files(self) -> list[Path]:
        """Get SQL files changed in git diff."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AM", "--"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [
            Path(f) for f in result.stdout.splitlines() if f.endswith(".sql") and Path(f).exists()
        ]

    def run(
        self,
        files: list[Path] | None = None,
        checks: list[str] | None = None,
        git_diff: bool = False,
    ) -> UnifiedLintResult:
        """Run all configured linting tools and return aggregated results."""
        if git_diff:
            target_files = self._get_changed_sql_files()
        elif files is not None:
            target_files = files
        else:
            target_files = []

        # Expand directories
        expanded: list[Path] = []
        for f in target_files:
            if f.is_dir():
                expanded.extend(files_under(f))
            else:
                expanded.append(f)
        target_files = expanded

        all_issues: list[UnifiedLintIssue] = []
        skipped: list[SkippedCheck] = []

        run_squawk = checks is None or "safety" in checks
        run_sqlfluff = checks is None or "format" in checks

        if run_squawk:
            if self._squawk.available:
                all_issues.extend(self._squawk.run(target_files))
            else:
                skipped.append(SkippedCheck("safety", "squawk", "squawk is not installed on PATH"))
        if run_sqlfluff:
            if self._sqlfluff.available:
                all_issues.extend(self._sqlfluff.run(target_files))
                skipped.extend(
                    SkippedCheck("format", "sqlfluff", f"{file}: {reason}")
                    for file, reason in self._sqlfluff.failures
                )
            else:
                skipped.append(SkippedCheck("format", "sqlfluff", "sqlfluff is not installed"))

        return UnifiedLintResult(issues=all_issues, skipped=skipped)
