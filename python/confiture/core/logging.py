"""Structured JSON logging for Confiture operations.

This module provides the StructuredLogger for JSON-formatted error logging
with support for error codes, severity levels, context, and timestamps.
"""

import json
from datetime import datetime
from enum import Enum
from sys import stdout
from typing import Any

from confiture.exceptions import ConfiturError


class LogLevel(str, Enum):
    """Log level for filtering."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogOutput:
    """Represents an output target for logs."""

    def __init__(self, stream: Any) -> None:
        """Initialize log output.

        Args:
            stream: Output stream (file-like object with write method)
        """
        self.stream = stream

    def write(self, line: str) -> None:
        """Write a line to the output.

        Args:
            line: The line to write
        """
        self.stream.write(line + "\n")
        if hasattr(self.stream, "flush"):
            self.stream.flush()


class StructuredLogger:
    """Logger for structured JSON error logging.

    Logs errors as JSON with error codes, severity, context, and timestamps.

    Example:
        >>> logger = StructuredLogger()
        >>> error = ConfigurationError("Missing config", error_code="CONFIG_001")
        >>> logger.log_error(error, request_id="req-123")
    """

    def __init__(
        self,
        level: LogLevel = LogLevel.INFO,
        output: Any | None = None,
        outputs: list[Any] | None = None,
    ) -> None:
        """Initialize StructuredLogger.

        Args:
            level: Minimum log level to output
            output: Single output stream (file-like)
            outputs: Multiple output streams
        """
        self.level = level
        self._single_output = output

        # Build output list
        if outputs:
            self.outputs = [LogOutput(o) for o in outputs]
        elif output:
            self.outputs = [LogOutput(output)]
        else:
            self.outputs = [LogOutput(stdout)]

    @property
    def output(self) -> Any | None:
        """Get the single output stream if set."""
        return self._single_output

    def log_error(
        self,
        error: Exception,
        level: LogLevel = LogLevel.ERROR,
        **kwargs: Any,
    ) -> None:
        """Log an error as JSON.

        Args:
            error: The exception to log
            level: Log level for this error
            **kwargs: Additional context fields (request_id, operation, etc.)
        """
        # Check if this level should be logged
        level_order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]
        if level_order.index(level) < level_order.index(self.level):
            return

        # Build JSON object
        log_entry = self._build_log_entry(error, level, kwargs)

        # Convert to JSON
        json_line = json.dumps(log_entry)

        # Write to all outputs
        for output in self.outputs:
            output.write(json_line)

    def _build_log_entry(
        self,
        error: Exception,
        level: LogLevel,
        extra_fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a log entry dict from an error.

        Args:
            error: The exception
            level: Log level
            extra_fields: Additional fields to include

        Returns:
            Dict ready for JSON serialization
        """
        entry: dict[str, Any] = {
            "message": str(error),
            "severity": self._get_severity(error),
            "level": level.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add error code if present
        if isinstance(error, ConfiturError):
            if error.error_code:
                entry["error_code"] = error.error_code
            if error.context:
                entry["context"] = error.context
            if error.resolution_hint:
                entry["resolution_hint"] = error.resolution_hint

        # Add extra fields
        entry.update(extra_fields)

        return entry

    def _get_severity(self, error: Exception) -> str:
        """Get severity string from error.

        Args:
            error: The exception

        Returns:
            Severity string (info, warning, error, critical)
        """
        if isinstance(error, ConfiturError):
            return error.severity.value
        return "error"
