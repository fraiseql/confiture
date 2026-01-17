"""Security utilities for Confiture.

This module provides security hardening features including:
- Input validation for SQL identifiers, paths, and configuration
- Secure logging with automatic secret redaction
- Defense-in-depth SQL safety checks
"""

from confiture.core.security.logging import SecureFormatter, configure_secure_logging
from confiture.core.security.validation import (
    ValidationError,
    sanitize_log_message,
    validate_config,
    validate_environment,
    validate_identifier,
    validate_path,
    validate_sql,
)

__all__ = [
    # Validation
    "ValidationError",
    "validate_identifier",
    "validate_path",
    "validate_environment",
    "validate_sql",
    "validate_config",
    "sanitize_log_message",
    # Logging
    "SecureFormatter",
    "configure_secure_logging",
]
