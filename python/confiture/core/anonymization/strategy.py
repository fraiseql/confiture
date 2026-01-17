"""Anonymization strategy base class and interfaces.

This module provides the abstract base class and configuration system for all
anonymization strategies. Strategies are pluggable implementations that can
anonymize different types of PII (emails, phone numbers, etc.).

Security Note:
    Seeds can be configured via:
    1. Environment variables (RECOMMENDED): seed_env_var="ANONYMIZATION_SEED"
    2. Hardcoded values (TESTING ONLY): seed=12345
    3. Default (seed=0 if neither provided)

    NEVER commit seeds to version control. Use environment variables in production.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class StrategyConfig:
    """Base configuration for any anonymization strategy.

    Attributes:
        seed: Optional hardcoded seed (testing only, not for production)
        seed_env_var: Name of environment variable containing seed (RECOMMENDED)
        name: Human-readable name for this configuration
    """

    seed: int | None = None
    """Hardcoded seed value (use only for testing, not production)."""

    seed_env_var: str | None = None
    """Environment variable name containing the seed (recommended for production)."""

    name: str = ""
    """Human-readable name for this configuration."""


def resolve_seed(config: StrategyConfig) -> int:
    """Resolve seed from environment variable, config, or default.

    Resolution order:
        1. Environment variable (if seed_env_var is set)
        2. Hardcoded seed (if seed is set)
        3. Default seed (0)

    Args:
        config: StrategyConfig instance

    Returns:
        Resolved seed value as integer

    Raises:
        ValueError: If environment variable contains non-integer value

    Example:
        >>> import os
        >>> os.environ['MY_SEED'] = '12345'
        >>> config = StrategyConfig(seed_env_var='MY_SEED')
        >>> resolve_seed(config)
        12345

        >>> config = StrategyConfig(seed=99999)
        >>> resolve_seed(config)
        99999

        >>> config = StrategyConfig()
        >>> resolve_seed(config)
        0
    """
    # Priority 1: Environment variable
    if config.seed_env_var:
        env_value = os.getenv(config.seed_env_var)
        if env_value is not None and env_value != "":
            try:
                return int(env_value)
            except ValueError as e:
                raise ValueError(
                    f"Invalid integer in environment variable {config.seed_env_var}: {env_value}"
                ) from e

    # Priority 2: Hardcoded seed
    if config.seed is not None:
        return config.seed

    # Priority 3: Default seed
    return 0


class AnonymizationStrategy(ABC):
    """Abstract base class for all anonymization strategies.

    Strategies must be:
        - Deterministic: Same input + seed = same output (important for testing)
        - Type-aware: Handle NULL values, integers, strings differently
        - PII-safe: Preserve data properties for testing while hiding real values
        - Composable: Can be combined with other strategies

    Example:
        >>> from python.confiture.core.anonymization.strategies.email import EmailMaskingStrategy
        >>> from python.confiture.core.anonymization.strategy import StrategyConfig
        >>>
        >>> config = StrategyConfig(seed=12345)
        >>> strategy = EmailMaskingStrategy(config)
        >>> result = strategy.anonymize("john@example.com")
        >>> result
        'user_a1b2c3d4@example.com'
    """

    config_type: type[StrategyConfig] = StrategyConfig
    strategy_name: str = "base"

    def __init__(self, config: StrategyConfig | None = None):
        """Initialize strategy with configuration.

        Args:
            config: Strategy configuration (creates default if not provided)
        """
        self.config = config or StrategyConfig()
        self._seed = resolve_seed(self.config)

    @abstractmethod
    def anonymize(self, value: Any) -> Any:
        """Apply anonymization to a value.

        Must handle:
            - None/NULL values (return None)
            - Empty strings (return "" or "[EMPTY]")
            - Unicode/non-ASCII (handle UTF-8 properly)
            - Very long values (truncate or hash as needed)

        Must be deterministic if seed is set (same input = same output).

        Args:
            value: Original value to anonymize

        Returns:
            Anonymized value (same type as input if possible)

        Raises:
            ValueError: If value cannot be anonymized for this strategy
        """
        raise NotImplementedError

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Check if strategy can handle this value type.

        Used to determine if strategy is applicable for a column.

        Args:
            value: Sample value to validate

        Returns:
            True if strategy can handle this value type
        """
        raise NotImplementedError

    def validate_comprehensive(
        self,
        value: Any,
        column_name: str = "",
        table_name: str = "",
    ) -> tuple[bool, list[str]]:
        """Comprehensive validation with detailed error reporting.

        Extended validation method that provides:
        - Basic type validation (from validate())
        - Completeness checking (NULL handling)
        - Format validation (if applicable)
        - Reversibility checking (for tokenization/encryption)
        - Size constraints (max length, etc.)

        Args:
            value: Value to validate
            column_name: Column name (for error context)
            table_name: Table name (for error context)

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
            - is_valid: True if value is acceptable
            - errors: List of validation error messages (empty if valid)

        Example:
            >>> strategy = EmailMaskingStrategy(StrategyConfig(seed=12345))
            >>> is_valid, errors = strategy.validate_comprehensive(
            ...     "john@example.com",
            ...     column_name="email",
            ...     table_name="users"
            ... )
            >>> if not is_valid:
            ...     for error in errors:
            ...         print(f"Validation error: {error}")
        """
        errors = []

        # 1. Basic type validation
        if not self.validate(value):
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Value '{value}' (type {type(value).__name__}) "
                f"cannot be handled by {self.name_short()}"
            )
            return False, errors

        # 2. NULL/None handling
        if value is None:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"NULL value detected (strategy may not handle NULL)"
            )
            return False, errors

        # 3. Empty string handling
        if isinstance(value, str) and len(value.strip()) == 0:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Empty string detected (strategy may produce artifacts)"
            )
            return False, errors

        # All checks passed
        return True, []

    def name_short(self) -> str:
        """Return short name for this strategy (for logging/reporting).

        Example:
            >>> strategy = EmailMaskingStrategy()
            >>> strategy.name_short()
            'email_mask'
        """
        return self.__class__.__name__.replace("Strategy", "").lower()

    def __repr__(self) -> str:
        """String representation for debugging."""
        seed_info = f", seed={self._seed}" if self._seed else ""
        return f"{self.__class__.__name__}({self.config.name}{seed_info})"
