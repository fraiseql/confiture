"""Integration tests for Phase 3 workflows.

Tests complete workflow pipelines with Phase 1-3 integration.
"""

import pytest

from confiture.workflows.retry import RetryPolicy, with_retry
from confiture.workflows.recovery import get_recovery_handler
from confiture.workflows.orchestrator import Workflow
from confiture.workflows.decisions import DecisionTree
from confiture.exceptions import ConfigurationError, MigrationError


class TestPhase3Integration:
    """Test Phase 3 workflows integrated with Phases 1-2."""

    def test_retry_with_recovery_handler(self) -> None:
        """Test retry logic with recovery handler."""
        attempts = [0]

        @with_retry(RetryPolicy(max_attempts=3, initial_delay=0.01))
        def fails_twice():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("transient error")
            return "success"

        result = fails_twice()
        assert result == "success"
        assert attempts[0] == 3

    def test_error_recovery_workflow(self) -> None:
        """Test complete error recovery workflow."""
        error = ConfigurationError("Missing config", error_code="CONFIG_001")
        handler = get_recovery_handler(error)

        assert handler is not None
        action = handler.decide()
        # CONFIG should need manual intervention
        assert action.value in ["manual", "retry"]

    def test_workflow_with_decision_tree(self) -> None:
        """Test workflow with decision tree."""
        tree = DecisionTree()

        # Test error classification
        assert tree.classify_error("ROLLBACK_602") == "critical"
        assert tree.classify_error("CONFIG_001") == "error"

        # Test escalation
        assert tree.should_escalate("ROLLBACK_602")

    def test_complete_workflow_pipeline(self) -> None:
        """Test complete Phase 1-3 pipeline."""
        executed = []

        # Define workflow
        workflow = Workflow(
            name="test_pipeline",
            steps=[
                ("phase1_validate", lambda: executed.append("validate")),
                ("phase2_log", lambda: executed.append("log")),
                ("phase3_execute", lambda: executed.append("execute")),
            ],
        )

        # Execute
        result = workflow.execute()

        assert result.success
        assert executed == ["validate", "log", "execute"]
