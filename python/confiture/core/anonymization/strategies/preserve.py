"""Preserve (no-op) anonymization strategy.

Provides a no-operation strategy that returns values unchanged.
Useful for:
- Marking columns that should NOT be anonymized
- Placeholder in strategy chains
- Configuration clarity (explicit "don't anonymize" intent)
- Testing and debugging
"""

from dataclasses import dataclass

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


@dataclass
class PreserveConfig(StrategyConfig):
    """Configuration for preserve strategy.

    This strategy has no configuration options beyond base StrategyConfig.
    It simply returns values unchanged.

    Example:
        >>> config = PreserveConfig(seed=12345)
    """

    pass


class PreserveStrategy(AnonymizationStrategy):
    """No-operation anonymization strategy.

    Returns values unchanged. Useful for marking columns that should not
    be anonymized or as a placeholder in processing chains.

    Features:
    - Identity operation (returns input unchanged)
    - Handles all value types
    - NULL-safe
    - Useful for explicit "preserve" intent in configurations

    Example:
        >>> config = PreserveConfig()
        >>> strategy = PreserveStrategy(config)
        >>> strategy.anonymize("sensitive_data")
        'sensitive_data'  # Unchanged
    """

    config_type = PreserveConfig
    strategy_name = "preserve"

    def anonymize(self, value):
        """Return value unchanged.

        Args:
            value: Any value

        Returns:
            The same value unchanged

        Example:
            >>> strategy.anonymize("test@example.com")
            'test@example.com'
        """
        return value

    def validate(self, _value) -> bool:
        """Check if strategy can handle this value type.

        Args:
            _value: Sample value to validate (unused, preserve accepts any)

        Returns:
            True (preserve accepts any value type)
        """
        return True

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "preserve")
        """
        return self.strategy_name
