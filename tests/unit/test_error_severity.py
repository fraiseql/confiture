"""Tests for ErrorSeverity enum.

This module tests the ErrorSeverity enum following the LintSeverity pattern.
"""

import pytest

from confiture.models.error import ErrorSeverity


class TestErrorSeverityEnum:
    """Test ErrorSeverity enum definition and behavior."""

    def test_error_severity_values(self) -> None:
        """Test that ErrorSeverity has all required values."""
        assert ErrorSeverity.INFO.value == "info"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_error_severity_is_string_enum(self) -> None:
        """Test that ErrorSeverity is a string enum."""
        # Should be comparable to strings
        assert ErrorSeverity.INFO == "info"
        assert ErrorSeverity.WARNING == "warning"
        assert ErrorSeverity.ERROR == "error"
        assert ErrorSeverity.CRITICAL == "critical"

    def test_error_severity_iteration(self) -> None:
        """Test that we can iterate over ErrorSeverity values."""
        severities = list(ErrorSeverity)
        assert len(severities) == 4
        assert ErrorSeverity.INFO in severities
        assert ErrorSeverity.WARNING in severities
        assert ErrorSeverity.ERROR in severities
        assert ErrorSeverity.CRITICAL in severities

    def test_error_severity_from_string(self) -> None:
        """Test creating ErrorSeverity from string value."""
        assert ErrorSeverity("info") == ErrorSeverity.INFO
        assert ErrorSeverity("warning") == ErrorSeverity.WARNING
        assert ErrorSeverity("error") == ErrorSeverity.ERROR
        assert ErrorSeverity("critical") == ErrorSeverity.CRITICAL

    def test_error_severity_invalid_value(self) -> None:
        """Test that invalid severity values raise ValueError."""
        with pytest.raises(ValueError):
            ErrorSeverity("invalid")

    def test_error_severity_matches_lint_severity_pattern(self) -> None:
        """Test that ErrorSeverity follows same pattern as LintSeverity."""
        from confiture.models.lint import LintSeverity

        # ErrorSeverity should have similar structure to LintSeverity
        # Both should be string enums
        assert isinstance(ErrorSeverity.INFO, str)
        assert isinstance(LintSeverity.INFO, str)

        # Both should have ERROR level
        assert hasattr(ErrorSeverity, "ERROR")
        assert hasattr(LintSeverity, "ERROR")
