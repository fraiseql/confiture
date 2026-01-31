"""Workflow orchestration engine for multi-step operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    name: str
    func: Callable[..., Any]
    on_error: str = "abort"  # abort, retry, skip


@dataclass
class WorkflowResult:
    """Result of workflow execution."""

    success: bool
    completed_steps: list[str]
    failed_step: str | None = None
    error: Exception | None = None


class Workflow:
    """Orchestrate multi-step operations with error handling."""

    def __init__(self, name: str, steps: list[tuple[str, Callable[..., Any]]]) -> None:
        """Initialize workflow.

        Args:
            name: Workflow name
            steps: List of (name, function) tuples
        """
        self.name = name
        self.steps = [WorkflowStep(name, func) for name, func in steps]

    def execute(self) -> WorkflowResult:
        """Execute workflow steps in order.

        Returns:
            WorkflowResult with execution status
        """
        completed = []

        for step in self.steps:
            try:
                step.func()
                completed.append(step.name)
            except Exception as e:
                return WorkflowResult(
                    success=False,
                    completed_steps=completed,
                    failed_step=step.name,
                    error=e,
                )

        return WorkflowResult(success=True, completed_steps=completed)
