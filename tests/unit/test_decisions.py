"""Tests for error decision trees."""

import pytest

from confiture.workflows.decisions import DecisionTree


class TestDecisionTree:
    """Test error decision trees."""

    def test_classify_critical_error(self) -> None:
        """Test classification of critical errors."""
        tree = DecisionTree()

        severity = tree.classify_error("ROLLBACK_602")
        assert severity == "critical"

    def test_classify_warning(self) -> None:
        """Test classification of warnings."""
        tree = DecisionTree()

        severity = tree.classify_error("LINT_1501")
        assert severity == "warning"

    def test_should_escalate_critical(self) -> None:
        """Test escalation decision."""
        tree = DecisionTree()

        assert tree.should_escalate("ROLLBACK_602")
        assert not tree.should_escalate("MIGR_100")

    def test_can_auto_repair(self) -> None:
        """Test auto-repair decision."""
        tree = DecisionTree()

        # Retryable
        assert tree.can_auto_repair("MIGR_100")
        assert tree.can_auto_repair("SQL_700")

        # Not retryable
        assert not tree.can_auto_repair("CONFIG_001")
