"""Error models for structured error handling: the severity every error and finding carries.

A leaf: ``confiture.exceptions`` and ``confiture.error_codes`` both read it, so it
imports nothing of theirs.
"""

from enum import Enum

__all__ = ["ErrorSeverity"]


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
