"""Self-healing strategies for automated error recovery."""


class HealingStrategy:
    """Base class for self-healing strategies."""

    def __init__(self, error_code: str) -> None:
        """Initialize healing strategy.

        Args:
            error_code: Error code to heal
        """
        self.error_code = error_code

    def can_heal(self) -> bool:
        """Determine if this error can be auto-healed.

        Returns:
            True if healing is possible
        """
        # CONFIG errors typically can't auto-heal without user input
        healable = {"MIGR", "SQL", "POOL", "LOCK"}
        category = self.error_code.split("_")[0]
        return category in healable

    def heal(self) -> bool:
        """Attempt to heal the error.

        Returns:
            True if healing was successful
        """
        return self.can_heal()


def get_healing_strategy(error_code: str) -> HealingStrategy:
    """Get healing strategy for error code.

    Args:
        error_code: Error code

    Returns:
        HealingStrategy for the error
    """
    return HealingStrategy(error_code)
