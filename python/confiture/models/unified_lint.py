"""Models for unified SQL linting results."""

from __future__ import annotations

import dataclasses
from typing import Any

from confiture.models.lint import LintSeverity


@dataclasses.dataclass
class UnifiedLintIssue:
    """A single linting issue from any tool."""

    tool: str
    file: str
    line: int | None
    message: str
    severity: LintSeverity
    rule: str | None = None


@dataclasses.dataclass
class UnifiedLintResult:
    """Aggregated results from all linting tools."""

    issues: list[UnifiedLintIssue]

    @property
    def has_errors(self) -> bool:
        """Whether any ERROR-level issues exist."""
        return any(i.severity == LintSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Whether any WARNING-level issues exist."""
        return any(i.severity == LintSeverity.WARNING for i in self.issues)

    @property
    def by_tool(self) -> dict[str, list[UnifiedLintIssue]]:
        """Group issues by tool name."""
        result: dict[str, list[UnifiedLintIssue]] = {}
        for issue in self.issues:
            result.setdefault(issue.tool, []).append(issue)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary for JSON output."""
        errors = sum(1 for i in self.issues if i.severity == LintSeverity.ERROR)
        warnings = sum(1 for i in self.issues if i.severity == LintSeverity.WARNING)
        info = sum(1 for i in self.issues if i.severity == LintSeverity.INFO)
        return {
            "summary": {
                "total": len(self.issues),
                "errors": errors,
                "warnings": warnings,
                "info": info,
            },
            "issues": [dataclasses.asdict(i) for i in self.issues],
        }
