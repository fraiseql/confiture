"""Strategy composition system for chaining multiple anonymization strategies.

Provides:
- Sequential strategy chaining (apply strategies one after another)
- Composite strategy containers
- Configuration-driven composition
- Error handling and validation
- Logging and monitoring

Enables complex anonymization scenarios like:
- Apply name masking first, then custom hash
- Redact emails, then preserve remaining text
- Multiple transforms on same column
"""

from dataclasses import dataclass, field
from typing import Any, List
from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig
from confiture.core.anonymization.registry import StrategyRegistry


@dataclass
class CompositionConfig(StrategyConfig):
    """Configuration for strategy composition.

    Attributes:
        seed: Seed for deterministic randomization
        strategies: List of strategy names or config dicts to chain
        stop_on_none: If True, stop chain if any strategy returns None (default False)
        stop_on_error: If True, stop chain on error (default False)
        continue_on_empty: If True, skip empty strings/None in chain (default False)

    Example:
        >>> config = CompositionConfig(
        ...     seed=12345,
        ...     strategies=["name", "custom"],
        ...     stop_on_none=False
        ... )
    """

    strategies: List[str] = field(default_factory=list)
    stop_on_none: bool = False
    stop_on_error: bool = False
    continue_on_empty: bool = False


class StrategyComposer(AnonymizationStrategy):
    """Composite strategy that chains multiple strategies sequentially.

    Applies strategies one after another, passing output of each as input
    to the next. Useful for complex anonymization workflows.

    Features:
    - Sequential strategy chaining
    - Configuration-driven composition
    - Error handling and recovery
    - Logging of applied strategies
    - Deterministic output

    Example:
        >>> config = CompositionConfig(
        ...     seed=12345,
        ...     strategies=["name:firstname_lastname", "custom:hash"]
        ... )
        >>> composer = StrategyComposer(config)
        >>> composer.anonymize("John Doe")
        'hashed_michael_johnson'
    """

    config_type = CompositionConfig
    strategy_name = "compose"

    def __init__(self, config: CompositionConfig | None = None):
        """Initialize composer with loaded strategies."""
        super().__init__(config or CompositionConfig())
        self._strategies = self._load_strategies()

    def anonymize(self, value: Any) -> Any:
        """Apply chained strategies to value.

        Args:
            value: Value to anonymize

        Returns:
            Anonymized value after all strategies applied

        Example:
            >>> composer.anonymize("test data")
            'transformed_data'
        """
        if value is None:
            return None

        current_value = value

        for strategy, strategy_name in self._strategies:
            try:
                # Check skip conditions
                if self.config.continue_on_empty:
                    if current_value is None or (
                        isinstance(current_value, str) and not current_value.strip()
                    ):
                        continue

                # Apply strategy
                current_value = strategy.anonymize(current_value)

                # Check stop conditions
                if self.config.stop_on_none and current_value is None:
                    break

            except Exception as e:
                if self.config.stop_on_error:
                    raise Exception(
                        f"Error in strategy '{strategy_name}': {e}"
                    ) from e
                else:
                    # Skip failing strategy and continue
                    continue

        return current_value

    def validate(self, value: Any) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if any strategy can handle this type
        """
        if not self._strategies:
            return True

        # Check if any strategy accepts this type
        for strategy, _ in self._strategies:
            if strategy.validate(value):
                return True

        return False

    def _load_strategies(self) -> List[tuple]:
        """Load strategies from configuration.

        Returns:
            List of (strategy_instance, strategy_name) tuples

        Raises:
            ValueError: If strategy not found in registry
        """
        loaded = []

        for strategy_spec in self.config.strategies:
            try:
                # Handle strategy name or config dict
                if isinstance(strategy_spec, str):
                    # Extract base strategy name (remove config suffix if present)
                    # "name:firstname_lastname" -> get "name" from registry
                    base_name = strategy_spec.split(":")[0]

                    # Get from registry with seed
                    strategy = StrategyRegistry.get(
                        base_name, {"seed": self.config.seed}
                    )
                    strategy_name = strategy_spec
                else:
                    # Config dict or StrategyConfig object
                    raise ValueError("Strategy dict config not yet supported")

                loaded.append((strategy, strategy_name))

            except Exception as e:
                raise ValueError(
                    f"Failed to load strategy '{strategy_spec}': {e}"
                ) from e

        return loaded

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "compose:name_custom")
        """
        if not self._strategies:
            return f"{self.strategy_name}:empty"

        strategy_names = [name for _, name in self._strategies[:3]]
        strategies_str = "_".join(strategy_names)
        return f"{self.strategy_name}:{strategies_str}"

    def get_strategy_chain(self) -> List[str]:
        """Get list of strategies in chain.

        Returns:
            List of strategy names in order
        """
        return [name for _, name in self._strategies]


class StrategySequence:
    """Builder for composing strategies with fluent API.

    Provides convenient syntax for building strategy chains.

    Example:
        >>> sequence = StrategySequence(seed=12345)
        >>> sequence.add("name:firstname_lastname").add("custom:hash").build()
        StrategyComposer instance
    """

    def __init__(self, seed: int = 0):
        """Initialize sequence builder.

        Args:
            seed: Seed for deterministic randomization
        """
        self.seed = seed
        self.strategies = []
        self.stop_on_none = False
        self.stop_on_error = False
        self.continue_on_empty = False

    def add(self, strategy_name: str) -> "StrategySequence":
        """Add strategy to sequence.

        Args:
            strategy_name: Name of strategy to add

        Returns:
            Self for chaining
        """
        self.strategies.append(strategy_name)
        return self

    def add_many(self, *strategy_names: str) -> "StrategySequence":
        """Add multiple strategies to sequence.

        Args:
            *strategy_names: Variable number of strategy names

        Returns:
            Self for chaining

        Example:
            >>> seq.add_many("name", "email", "phone")
        """
        self.strategies.extend(strategy_names)
        return self

    def on_none(self, stop: bool = True) -> "StrategySequence":
        """Configure stopping on None values.

        Args:
            stop: If True, stop chain on None

        Returns:
            Self for chaining
        """
        self.stop_on_none = stop
        return self

    def on_error(self, stop: bool = True) -> "StrategySequence":
        """Configure stopping on errors.

        Args:
            stop: If True, stop chain on error

        Returns:
            Self for chaining
        """
        self.stop_on_error = stop
        return self

    def skip_empty(self, skip: bool = True) -> "StrategySequence":
        """Configure skipping empty strings/None.

        Args:
            skip: If True, skip empty values

        Returns:
            Self for chaining
        """
        self.continue_on_empty = skip
        return self

    def build(self) -> StrategyComposer:
        """Build the composed strategy.

        Returns:
            StrategyComposer instance

        Raises:
            ValueError: If no strategies configured
        """
        if not self.strategies:
            raise ValueError("No strategies configured")

        config = CompositionConfig(
            seed=self.seed,
            strategies=self.strategies,
            stop_on_none=self.stop_on_none,
            stop_on_error=self.stop_on_error,
            continue_on_empty=self.continue_on_empty,
        )

        return StrategyComposer(config)
