"""Unified SQL linter orchestrating Squawk, SQLFluff, and other tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from confiture.models.lint import LintSeverity
from confiture.models.unified_lint import UnifiedLintIssue, UnifiedLintResult


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
            ["squawk", "--reporter=json", *[str(f) for f in files]],
            capture_output=True,
            text=True,
            check=False,
        )
        return self._parse(result.stdout)

    def _parse(self, output: str) -> list[UnifiedLintIssue]:
        """Parse squawk JSON output into UnifiedLintIssue objects."""
        if not output.strip():
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []
        issues = []
        for item in data:
            for violation in item.get("violations", []):
                issues.append(
                    UnifiedLintIssue(
                        tool="squawk",
                        file=item.get("filename", ""),
                        line=violation.get("line"),
                        message=violation.get("message", ""),
                        severity=LintSeverity.WARNING,
                        rule=violation.get("rule"),
                    )
                )
        return issues


class SQLFluffRunner:
    """Runs SQLFluff for SQL style and formatting checks."""

    @property
    def available(self) -> bool:
        """Whether sqlfluff is installed."""
        try:
            import sqlfluff  # noqa: F401, PLC0415

            return True
        except ImportError:
            return False

    def run(self, files: list[Path], dialect: str = "postgres") -> list[UnifiedLintIssue]:
        """Run sqlfluff on the given SQL files."""
        if not self.available or not files:
            return []
        from sqlfluff.api import simple  # noqa: PLC0415

        issues = []
        for f in files:
            try:
                result = simple.lint(f.read_text(), dialect=dialect)
                for violation in result:
                    issues.append(
                        UnifiedLintIssue(
                            tool="sqlfluff",
                            file=str(f),
                            line=violation.get("line_no"),
                            message=violation.get("description", ""),
                            severity=LintSeverity.WARNING,
                            rule=violation.get("code"),
                        )
                    )
            except Exception:  # noqa: BLE001
                pass
        return issues


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
            ["git", "diff", "--name-only", "--diff-filter=AM"],
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
                expanded.extend(sorted(f.rglob("*.sql")))
            else:
                expanded.append(f)
        target_files = expanded

        all_issues: list[UnifiedLintIssue] = []

        run_squawk = checks is None or "safety" in checks
        run_sqlfluff = checks is None or "format" in checks

        if run_squawk:
            all_issues.extend(self._squawk.run(target_files))
        if run_sqlfluff:
            all_issues.extend(self._sqlfluff.run(target_files))

        return UnifiedLintResult(issues=all_issues)
