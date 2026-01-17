"""Structured JSON logging for migrations.

Provides structured logging with correlation IDs for migration operations.
"""

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class LoggingConfig:
    """Configuration for structured logging."""

    enabled: bool = True
    format: str = "json"  # "json" or "text"
    level: str = "INFO"
    include_timestamp: bool = True
    include_correlation_id: bool = True


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, config: LoggingConfig):
        """Initialize structured formatter.

        Args:
            config: Logging configuration
        """
        super().__init__()
        self.config = config

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        if self.config.include_timestamp:
            log_data["timestamp"] = datetime.now(UTC).isoformat()

        if self.config.include_correlation_id:
            log_data["correlation_id"] = getattr(record, "correlation_id", str(uuid.uuid4())[:8])

        # Add extra fields from record
        extra_fields = [
            "migration_version",
            "migration_name",
            "duration_ms",
            "rows_affected",
            "operation",
            "table_name",
            "status",
        ]
        for field in extra_fields:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Add exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class StructuredLogger:
    """Logger with structured output and correlation IDs.

    Provides a logging interface that supports correlation IDs
    and structured fields for migration operations.

    Example:
        >>> logger = StructuredLogger("confiture.migration")
        >>> logger.set_correlation_id("abc123")
        >>> logger.info("Starting migration", migration_version="001")
    """

    def __init__(self, name: str, config: LoggingConfig | None = None):
        """Initialize structured logger.

        Args:
            name: Logger name
            config: Logging configuration (optional)
        """
        self.config = config or LoggingConfig()
        self._logger = logging.getLogger(name)
        self._correlation_id: str | None = None

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        """Log with extra fields.

        Args:
            level: Log level
            message: Log message
            **kwargs: Extra fields to include
        """
        extra = {"correlation_id": self._correlation_id or str(uuid.uuid4())[:8]}
        extra.update(kwargs)
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log exception with traceback."""
        extra = {"correlation_id": self._correlation_id or str(uuid.uuid4())[:8]}
        extra.update(kwargs)
        self._logger.exception(message, extra=extra)

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set correlation ID for subsequent logs.

        Args:
            correlation_id: Correlation ID to use
        """
        self._correlation_id = correlation_id

    def clear_correlation_id(self) -> None:
        """Clear the correlation ID."""
        self._correlation_id = None

    def new_correlation_id(self) -> str:
        """Generate and set a new correlation ID.

        Returns:
            The new correlation ID
        """
        self._correlation_id = str(uuid.uuid4())[:8]
        return self._correlation_id


def configure_logging(config: LoggingConfig | None = None) -> None:
    """Configure structured logging for Confiture.

    Args:
        config: Logging configuration (optional)
    """
    config = config or LoggingConfig()

    # Get root logger for confiture
    logger = logging.getLogger("confiture")
    logger.setLevel(getattr(logging, config.level))

    # Remove existing handlers
    logger.handlers.clear()

    # Add handler with appropriate formatter
    handler = logging.StreamHandler(sys.stderr)

    if config.format == "json":
        handler.setFormatter(StructuredFormatter(config))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False
