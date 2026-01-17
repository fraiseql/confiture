"""Secure logging utilities.

This module provides logging utilities that automatically redact sensitive
information from log messages, preventing accidental credential exposure.
"""

import logging
import re
from typing import Any

from confiture.core.security.validation import sanitize_log_message


class SecureFormatter(logging.Formatter):
    """Logging formatter that automatically redacts sensitive data.

    This formatter extends the standard logging formatter to automatically
    redact passwords, tokens, API keys, and other sensitive information
    from log messages before they are emitted.

    Example:
        >>> handler = logging.StreamHandler()
        >>> handler.setFormatter(SecureFormatter())
        >>> logger = logging.getLogger("myapp")
        >>> logger.addHandler(handler)
        >>> logger.info("Connecting to postgresql://user:secret@host/db")
        # Output: Connecting to postgresql://***@host/db
    """

    # Additional patterns specific to formatting (beyond validation module)
    EXTRA_PATTERNS = [
        (re.compile(r"AWS_SECRET_ACCESS_KEY=\S+", re.IGNORECASE), "AWS_SECRET_ACCESS_KEY=***"),
        (re.compile(r"AWS_ACCESS_KEY_ID=\S+", re.IGNORECASE), "AWS_ACCESS_KEY_ID=***"),
        (re.compile(r"GOOGLE_APPLICATION_CREDENTIALS=\S+"), "GOOGLE_APPLICATION_CREDENTIALS=***"),
        (re.compile(r'"password"\s*:\s*"[^"]*"'), '"password": "***"'),
        (re.compile(r"'password'\s*:\s*'[^']*'"), "'password': '***'"),
    ]

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with sensitive data redacted.

        Args:
            record: The log record to format

        Returns:
            Formatted log string with sensitive data replaced by ***
        """
        # First, let the parent do standard formatting
        message = super().format(record)

        # Apply sanitization from validation module
        message = sanitize_log_message(message)

        # Apply additional formatting-specific patterns
        for pattern, replacement in self.EXTRA_PATTERNS:
            message = pattern.sub(replacement, message)

        return message


class SecureLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that sanitizes messages before logging.

    This adapter wraps a logger and ensures all messages are sanitized
    before being passed to the underlying logger.

    Example:
        >>> logger = logging.getLogger("myapp")
        >>> secure_logger = SecureLoggerAdapter(logger)
        >>> secure_logger.info("Password is secret123")
        # Message will be sanitized before logging
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Process the logging message to sanitize sensitive data.

        Args:
            msg: The log message
            kwargs: Additional keyword arguments

        Returns:
            Tuple of (sanitized message, kwargs)
        """
        sanitized_msg = sanitize_log_message(str(msg))
        return sanitized_msg, kwargs


def configure_secure_logging(
    level: int = logging.INFO,
    format_string: str | None = None,
    logger_name: str | None = None,
) -> logging.Logger:
    """Configure logging with secure formatter.

    Sets up logging with automatic secret redaction. This should be called
    early in application startup.

    Args:
        level: Logging level (default: INFO)
        format_string: Custom format string (default: standard format)
        logger_name: Logger name to configure (default: root logger)

    Returns:
        The configured logger

    Example:
        >>> logger = configure_secure_logging(logging.DEBUG)
        >>> logger.info("Connecting to postgresql://user:secret@host/db")
        # Output: 2024-01-15 10:30:00 - INFO - Connecting to postgresql://***@host/db
    """
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Create secure formatter
    formatter = SecureFormatter(format_string)

    # Create handler with secure formatter
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # Get logger
    logger = logging.getLogger(logger_name)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Add secure handler
    logger.addHandler(handler)
    logger.setLevel(level)

    return logger


def get_secure_logger(name: str) -> SecureLoggerAdapter:
    """Get a logger wrapped with secure adapter.

    Args:
        name: Logger name

    Returns:
        SecureLoggerAdapter wrapping the named logger

    Example:
        >>> logger = get_secure_logger("confiture.migration")
        >>> logger.info("Running with password=secret123")
        # password will be redacted
    """
    base_logger = logging.getLogger(name)
    return SecureLoggerAdapter(base_logger, {})


class SensitiveValue:
    """Wrapper for sensitive values that redacts them in string representation.

    Use this to wrap sensitive values that might accidentally be logged
    or included in error messages.

    Example:
        >>> password = SensitiveValue("secret123")
        >>> print(f"Password is {password}")
        Password is ***
        >>> str(password)
        '***'
        >>> password.get_value()
        'secret123'
    """

    def __init__(self, value: Any):
        """Initialize with a sensitive value.

        Args:
            value: The sensitive value to wrap
        """
        self._value = value

    def get_value(self) -> Any:
        """Get the actual sensitive value.

        Returns:
            The wrapped value
        """
        return self._value

    def __str__(self) -> str:
        """Return redacted string representation."""
        return "***"

    def __repr__(self) -> str:
        """Return redacted repr."""
        return "SensitiveValue(***)"

    def __eq__(self, other: Any) -> bool:
        """Compare values."""
        if isinstance(other, SensitiveValue):
            return self._value == other._value
        return self._value == other

    def __hash__(self) -> int:
        """Hash the value."""
        return hash(self._value)
