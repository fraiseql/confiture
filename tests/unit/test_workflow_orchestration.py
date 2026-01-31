"""Tests for workflow orchestration."""

import pytest

from confiture.workflows.orchestrator import Workflow, WorkflowResult


class TestWorkflowExecution:
    """Test workflow execution."""

    def test_workflow_succeeds(self) -> None:
        """Test successful workflow execution."""
        executed = []

        workflow = Workflow(
            name="test",
            steps=[
                ("step1", lambda: executed.append(1)),
                ("step2", lambda: executed.append(2)),
            ],
        )

        result = workflow.execute()

        assert result.success
        assert result.completed_steps == ["step1", "step2"]
        assert executed == [1, 2]

    def test_workflow_fails_at_step(self) -> None:
        """Test workflow failure."""

        def failing_step():
            raise ValueError("step failed")

        workflow = Workflow(
            name="test",
            steps=[
                ("step1", lambda: None),
                ("step2", failing_step),
                ("step3", lambda: None),
            ],
        )

        result = workflow.execute()

        assert not result.success
        assert result.failed_step == "step2"
        assert result.completed_steps == ["step1"]
        assert isinstance(result.error, ValueError)
