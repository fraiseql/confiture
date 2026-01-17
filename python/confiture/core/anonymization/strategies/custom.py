"""Custom anonymization strategy.

Provides a framework for implementing custom anonymization logic:
- Callable-based strategy (use any Python function)
- Deterministic with seed
- Type validation
- Logging-friendly

Useful for domain-specific anonymization that doesn't fit into built-in strategies.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


@dataclass
class CustomConfig(StrategyConfig):
    """Configuration for custom anonymization strategy.

    Attributes:
        seed: Seed for deterministic randomization
        func: Callable that performs anonymization
        name: Human-readable name for custom function
        accepts_seed: If True, func receives (value, seed) else just (value)

    Example:
        >>> def upper_mask(value):
        ...     return value.upper() if isinstance(value, str) else value
        >>> config = CustomConfig(seed=12345, func=upper_mask, name="uppercase")
    """

    func: Callable[[Any], Any] | None = None
    name: str = "custom"
    accepts_seed: bool = False


class CustomStrategy(AnonymizationStrategy):
    """Custom anonymization strategy using callable functions.

    Allows implementing domain-specific anonymization logic without
    creating a full strategy class. Useful for one-off anonymization needs.

    Features:
    - Function-based anonymization
    - Optional seed parameter
    - Type validation
    - Clear error handling

    Example:
        >>> def hash_value(value):
        ...     return f"hash_{hash(str(value))}"
        >>> config = CustomConfig(seed=12345, func=hash_value)
        >>> strategy = CustomStrategy(config)
        >>> strategy.anonymize("secret")
        'hash_...'
    """

    config_type = CustomConfig
    strategy_name = "custom"

    def anonymize(self, value: Any) -> Any:
        """Apply custom anonymization function.

        Args:
            value: Value to anonymize

        Returns:
            Anonymized value

        Raises:
            RuntimeError: If custom function is not configured
            Exception: Any exception from custom function
        """
        if self.config.func is None:
            raise RuntimeError("Custom strategy requires 'func' to be configured")

        try:
            if self.config.accepts_seed:
                return self.config.func(value, self.config.seed)
            else:
                return self.config.func(value)
        except Exception as e:
            raise Exception(
                f"Error in custom anonymization function '{self.config.name}': {e}"
            ) from e

    def validate(self, value: Any) -> bool:  # noqa: ARG002
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate (unused, custom accepts any)

        Returns:
            True (custom accepts any value type)
        """
        return True

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "custom:my_function")
        """
        return f"{self.strategy_name}:{self.config.name}"


class CustomLambdaStrategy(AnonymizationStrategy):
    """Custom strategy using inline lambda functions.

    Simplified version using lambda expressions for very simple
    anonymization logic.

    Example:
        >>> config = CustomConfig(
        ...     func=lambda x: f"anon_{hash(x) % 10000}",
        ...     name="hash_last4"
        ... )
        >>> strategy = CustomLambdaStrategy(config)
    """

    config_type = CustomConfig
    strategy_name = "custom_lambda"

    def anonymize(self, value: Any) -> Any:
        """Apply lambda-based anonymization.

        Args:
            value: Value to anonymize

        Returns:
            Anonymized value
        """
        if self.config.func is None:
            raise RuntimeError("Lambda strategy requires 'func' to be configured")

        try:
            return self.config.func(value)
        except Exception as e:
            raise Exception(
                f"Error in lambda anonymization: {e}"
            ) from e

    def validate(self, value: Any) -> bool:  # noqa: ARG002
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate (unused, lambda accepts any)

        Returns:
            True (lambda accepts any value type)
        """
        return True

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name
        """
        return f"{self.strategy_name}:{self.config.name}"
