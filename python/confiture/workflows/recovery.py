"""Error recovery strategies and workflows.

Provides recovery handlers for different error categories and codes,
enabling automated decision-making about how to recover from errors.
"""

from enum import Enum

from confiture.exceptions import ConfiturError


class RecoveryAction(str, Enum):
    """Actions available for error recovery."""

    RETRY = "retry"
    ABORT = "abort"
    MANUAL = "manual"
    HEAL = "heal"


class RecoveryHandler:
    """Base handler for error recovery decisions.

    Example:
        >>> handler = RecoveryHandler("CONFIG_001")
        >>> action = handler.decide()
        >>> if action == RecoveryAction.RETRY:
        ...     # Attempt recovery
        ...     pass
    """

    def __init__(self, error_code: str) -> None:
        """Initialize recovery handler.

        Args:
            error_code: The error code to handle
        """
        self.error_code = error_code

    def decide(self) -> RecoveryAction:
        """Decide what recovery action to take.

        Returns:
            RecoveryAction indicating how to proceed
        """
        # Default: depend on error code category
        category = self.error_code.split("_")[0]

        # Hardcoded recovery strategies by category
        recovery_map = {
            "CONFIG": RecoveryAction.MANUAL,
            "MIGR": RecoveryAction.RETRY,
            "SCHEMA": RecoveryAction.MANUAL,
            "SYNC": RecoveryAction.RETRY,
            "DIFFER": RecoveryAction.MANUAL,
            "VALID": RecoveryAction.ABORT,
            "ROLLBACK": RecoveryAction.ABORT,
            "SQL": RecoveryAction.RETRY,
            "GIT": RecoveryAction.MANUAL,
            "PGGIT": RecoveryAction.MANUAL,
            "PRECON": RecoveryAction.ABORT,
            "HOOK": RecoveryAction.MANUAL,
            "POOL": RecoveryAction.RETRY,
            "LOCK": RecoveryAction.RETRY,
            "ANON": RecoveryAction.MANUAL,
            "LINT": RecoveryAction.MANUAL,
        }

        return recovery_map.get(category, RecoveryAction.MANUAL)

    def apply(self) -> bool:
        """Apply recovery if possible.

        Returns:
            True if recovery was successful, False otherwise
        """
        # Default: no automatic recovery
        return False


def get_recovery_handler(error: Exception) -> RecoveryHandler | None:
    """Get appropriate recovery handler for an error.

    Args:
        error: The exception to handle

    Returns:
        RecoveryHandler for the error, or None
    """
    if isinstance(error, ConfiturError) and error.error_code:
        return RecoveryHandler(error.error_code)

    # Return default handler
    return RecoveryHandler("ERROR_001")
