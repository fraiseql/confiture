"""Tests for structured JSON logger.

Tests the StructuredLogger for JSON-formatted error logging with context,
error codes, severity levels, and timestamps.
"""

import json
from io import StringIO

from confiture.core.logging import LogLevel, StructuredLogger
from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    MigrationError,
)


class TestStructuredLoggerCreation:
    """Test StructuredLogger instantiation."""

    def test_logger_creation(self) -> None:
        """Test creating a logger instance."""
        logger = StructuredLogger()
        assert logger is not None

    def test_logger_creation_with_level(self) -> None:
        """Test creating a logger with specific log level."""
        logger = StructuredLogger(level=LogLevel.DEBUG)
        assert logger.level == LogLevel.DEBUG

    def test_logger_creation_with_output(self) -> None:
        """Test creating a logger with output stream."""
        output = StringIO()
        logger = StructuredLogger(output=output)
        assert logger.output is output

    def test_logger_creation_default_level(self) -> None:
        """Test that logger defaults to INFO level."""
        logger = StructuredLogger()
        assert logger.level == LogLevel.INFO


class TestJsonErrorLogging:
    """Test JSON error logging functionality."""

    def test_log_simple_error(self) -> None:
        """Test logging a simple error to JSON."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test error")
        logger.log_error(error)

        # Should have written something
        assert len(output.getvalue()) > 0

    def test_log_error_produces_valid_json(self) -> None:
        """Test that logged error is valid JSON."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test error")
        logger.log_error(error)

        # Parse JSON to verify it's valid
        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data is not None
        assert isinstance(json_data, dict)

    def test_log_error_includes_message(self) -> None:
        """Test that error message is included in JSON."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test message")
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("message") == "Test message"

    def test_log_error_with_error_code(self) -> None:
        """Test logging error with error code."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfigurationError(
            "Missing config",
            error_code="CONFIG_001",
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("error_code") == "CONFIG_001"

    def test_log_error_with_severity(self) -> None:
        """Test that error severity is logged."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("severity") == "error"

    def test_log_error_includes_timestamp(self) -> None:
        """Test that timestamp is included in log."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        # Timestamp should be a string in ISO format
        assert "timestamp" in json_data
        assert isinstance(json_data["timestamp"], str)

    def test_log_error_with_context(self) -> None:
        """Test logging error with additional context."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError(
            "Test",
            context={"file": "config.yaml", "field": "database_url"},
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("context") == {"file": "config.yaml", "field": "database_url"}

    def test_log_error_with_extra_kwargs(self) -> None:
        """Test logging error with extra keyword arguments."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(
            error,
            request_id="req-123",
            operation="migrate",
        )

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("request_id") == "req-123"
        assert json_data.get("operation") == "migrate"


class TestMigrationErrorLogging:
    """Test logging specific exception types."""

    def test_log_migration_error(self) -> None:
        """Test logging MigrationError with version info."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = MigrationError(
            "Migration failed",
            version="001",
            error_code="MIGR_100",
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("error_code") == "MIGR_100"
        assert json_data.get("message") == "Migration failed"


class TestLogLevelFiltering:
    """Test log level filtering."""

    def test_logger_respects_log_level_debug(self) -> None:
        """Test that DEBUG level logs everything."""
        output = StringIO()
        logger = StructuredLogger(output=output, level=LogLevel.DEBUG)

        error = ConfiturError("Test")
        logger.log_error(error, level=LogLevel.DEBUG)

        # Should be logged
        assert len(output.getvalue()) > 0

    def test_logger_respects_log_level_info(self) -> None:
        """Test that INFO level logs INFO and above."""
        output = StringIO()
        logger = StructuredLogger(output=output, level=LogLevel.INFO)

        error = ConfiturError("Test")
        logger.log_error(error, level=LogLevel.INFO)

        # Should be logged
        assert len(output.getvalue()) > 0

    def test_logger_filters_below_level(self) -> None:
        """Test that logs below threshold are filtered."""
        output = StringIO()
        logger = StructuredLogger(output=output, level=LogLevel.ERROR)

        error = ConfiturError("Test")
        # Try to log as INFO (below ERROR threshold)
        logger.log_error(error, level=LogLevel.INFO)

        # Should not be logged
        assert len(output.getvalue()) == 0

    def test_logger_includes_level_in_output(self) -> None:
        """Test that log level is included in JSON output."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(error, level=LogLevel.WARNING)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        assert json_data.get("level") == "warning"


class TestMultipleOutputs:
    """Test logging to multiple outputs."""

    def test_logger_with_multiple_outputs(self) -> None:
        """Test logger can write to multiple output streams."""
        output1 = StringIO()
        output2 = StringIO()
        logger = StructuredLogger(outputs=[output1, output2])

        error = ConfiturError("Test")
        logger.log_error(error)

        # Both outputs should have content
        assert len(output1.getvalue()) > 0
        assert len(output2.getvalue()) > 0

    def test_logger_outputs_are_independent(self) -> None:
        """Test that outputs don't interfere with each other."""
        output1 = StringIO()
        output2 = StringIO()
        logger = StructuredLogger(outputs=[output1, output2])

        error = ConfiturError("Test error")
        logger.log_error(error)

        # Both should have same content
        assert output1.getvalue() == output2.getvalue()


class TestJsonSchema:
    """Test the structure of logged JSON."""

    def test_json_has_required_fields(self) -> None:
        """Test that logged JSON has all required fields."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        # Required fields
        required_fields = ["message", "severity", "timestamp"]
        for field in required_fields:
            assert field in json_data, f"Missing required field: {field}"

    def test_json_optional_fields(self) -> None:
        """Test that optional fields are included when present."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError(
            "Test",
            error_code="CONFIG_001",
            context={"key": "value"},
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        # Optional fields should be present
        assert "error_code" in json_data
        assert "context" in json_data

    def test_json_no_optional_fields_when_not_present(self) -> None:
        """Test that optional fields are omitted when not present."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfiturError("Test")
        logger.log_error(error)

        log_line = output.getvalue().strip()
        json_data = json.loads(log_line)

        # Optional fields should not be present
        assert json_data.get("error_code") is None
        assert json_data.get("resolution_hint") is None
