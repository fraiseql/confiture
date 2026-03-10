"""Data models for CTE step-through debugging."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class CTEStepResult:
    """Result of executing a single CTE step."""

    cte_name: str
    row_count: int
    columns: list[str]
    rows: list[tuple[Any, ...]]
    execution_time_ms: float
    error: str | None = None

    @property
    def success(self) -> bool:
        """Whether this step executed without error."""
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "cte_name": self.cte_name,
            "row_count": self.row_count,
            "columns": self.columns,
            "rows": [list(r) for r in self.rows],
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


@dataclasses.dataclass
class CTEDebugSession:
    """A complete CTE debug session with all step results."""

    original_query: str
    steps: list[CTEStepResult]
    total_ctes: int

    @property
    def failed_at(self) -> str | None:
        """Name of the first CTE that failed, or None if all succeeded."""
        for step in self.steps:
            if not step.success:
                return step.cte_name
        return None

    @property
    def all_succeeded(self) -> bool:
        """Whether all CTE steps executed successfully."""
        return all(s.success for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "total_ctes": self.total_ctes,
            "all_succeeded": self.all_succeeded,
            "failed_at": self.failed_at,
            "steps": [s.to_dict() for s in self.steps],
        }
