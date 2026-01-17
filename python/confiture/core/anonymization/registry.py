"""Strategy registry for managing anonymization strategies.

Provides a singleton registry for dynamically registering and retrieving
anonymization strategies, enabling extensibility without modifying core code.

Features:
- Dynamic strategy registration
- Type-safe strategy retrieval
- Strategy discovery and listing
- Configuration validation
"""

from collections.abc import Callable
from typing import Any

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig


class StrategyRegistry:
    """Singleton registry for anonymization strategies.

    Manages registration and retrieval of strategy implementations,
    enabling dynamic discovery and extensibility.

    Example:
        >>> StrategyRegistry.register("email", EmailMaskingStrategy)
        >>> strategy = StrategyRegistry.get("email", {"seed": 12345})
        >>> print(StrategyRegistry.list_available())
        ['email', 'hash', 'phone', ...]
    """

    _registry: dict[str, type[AnonymizationStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type[AnonymizationStrategy]) -> None:
        """Register a strategy implementation.

        Args:
            name: Unique strategy name (e.g., "email", "hash")
            strategy_class: Strategy class inheriting from AnonymizationStrategy

        Raises:
            TypeError: If strategy_class doesn't inherit from AnonymizationStrategy
            ValueError: If name is already registered

        Example:
            >>> StrategyRegistry.register("custom", CustomStrategy)
        """
        if not issubclass(strategy_class, AnonymizationStrategy):
            raise TypeError(
                f"{strategy_class.__name__} must inherit from AnonymizationStrategy"
            )

        if name in cls._registry:
            raise ValueError(f"Strategy '{name}' is already registered")

        cls._registry[name] = strategy_class

    @classmethod
    def get(
        cls, name: str, config: dict[str, Any] | StrategyConfig | None = None
    ) -> AnonymizationStrategy:
        """Get a strategy instance by name.

        Args:
            name: Strategy name to retrieve
            config: Configuration dict or StrategyConfig instance

        Returns:
            Instantiated strategy with given configuration

        Raises:
            ValueError: If strategy name not found

        Example:
            >>> strategy = StrategyRegistry.get("email", {"seed": 12345})
            >>> anonymized = strategy.anonymize("john@example.com")
        """
        if name not in cls._registry:
            available = ", ".join(cls.list_available())
            raise ValueError(
                f"Unknown strategy: '{name}'. Available: {available}"
            )

        strategy_class = cls._registry[name]

        # Handle config conversion if needed
        if config is None:
            config = {}

        if isinstance(config, dict):
            config = strategy_class.config_type(**config)

        return strategy_class(config)

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a strategy is registered.

        Args:
            name: Strategy name to check

        Returns:
            True if strategy is registered, False otherwise
        """
        return name in cls._registry

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered strategy names.

        Returns:
            Sorted list of available strategy names

        Example:
            >>> strategies = StrategyRegistry.list_available()
            >>> print(strategies)
            ['address', 'date', 'email', 'hash', 'name', 'phone', ...]
        """
        return sorted(cls._registry.keys())

    @classmethod
    def get_strategy_class(cls, name: str) -> type[AnonymizationStrategy]:
        """Get the strategy class (not instance).

        Useful for introspection, documentation, or creating multiple instances
        with different configurations.

        Args:
            name: Strategy name

        Returns:
            Strategy class

        Raises:
            ValueError: If strategy name not found

        Example:
            >>> EmailStrategy = StrategyRegistry.get_strategy_class("email")
            >>> print(EmailStrategy.__doc__)
        """
        if name not in cls._registry:
            raise ValueError(f"Unknown strategy: '{name}'")

        return cls._registry[name]

    @classmethod
    def unregister(cls, name: str) -> None:
        """Unregister a strategy (mainly for testing).

        Args:
            name: Strategy name to unregister

        Raises:
            ValueError: If strategy not found
        """
        if name not in cls._registry:
            raise ValueError(f"Strategy '{name}' not registered")

        del cls._registry[name]

    @classmethod
    def reset(cls) -> None:
        """Reset registry (mainly for testing).

        Clears all registered strategies.
        """
        cls._registry.clear()

    @classmethod
    def count(cls) -> int:
        """Get number of registered strategies.

        Returns:
            Count of registered strategies
        """
        return len(cls._registry)


def register_strategy(
    name: str,
) -> Callable[[type[AnonymizationStrategy]], type[AnonymizationStrategy]]:
    """Decorator for registering a strategy class.

    Enables cleaner registration syntax:

    Example:
        >>> @register_strategy("custom_email")
        ... class CustomEmailStrategy(AnonymizationStrategy):
        ...     ...
    """

    def decorator(
        strategy_class: type[AnonymizationStrategy],
    ) -> type[AnonymizationStrategy]:
        StrategyRegistry.register(name, strategy_class)
        return strategy_class

    return decorator
