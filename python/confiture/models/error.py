"""Error models for structured error handling.

This module provides data structures for error categorization and classification,
including severity levels for error messages.
"""

from enum import Enum


class ErrorSeverity(str, Enum):
    """Severity levels for errors.

    Attributes:
        INFO: Informational, no action needed
        WARNING: Should investigate but not blocking
        ERROR: Blocking issue, must fix
        CRITICAL: Severe issue, potential data loss

    Example:
        >>> from confiture.models.error import ErrorSeverity
        >>> ErrorSeverity.ERROR
        <ErrorSeverity.ERROR: 'error'>
        >>> ErrorSeverity.ERROR == "error"
        True
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
