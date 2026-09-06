"""Deterministic hash-based anonymization strategy.

Uses HMAC-based hashing to provide:
    - Deterministic output (same input = same output with seed)
    - Rainbow table resistance (HMAC prevents offline attacks)
    - Uniqueness preservation (enables referential integrity testing)
    - Configurable length and prefix
"""

from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.pseudonymizer import Pseudonymizer
from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class DeterministicHashConfig(StrategyConfig):
    """Configuration for DeterministicHashStrategy.

    Attributes:
        algorithm: Hash algorithm ('sha256', 'sha1', 'md5')
        length: Optional truncation length (None = full hash)
        prefix: Optional prefix for output (e.g., 'hash_')
        seed_env_var: Environment variable containing seed (RECOMMENDED)
        seed: Hardcoded seed (testing only)
    """

    algorithm: str = "sha256"
    """Hash algorithm: sha256, sha1, or md5."""

    length: int | None = None
    """Optional truncation length (None = full hash)."""

    prefix: str = ""
    """Optional prefix for output."""

    def validate_algorithm(self):
        """Validate algorithm is one of allowed values."""
        allowed = {"sha256", "sha1", "md5"}
        if self.algorithm not in allowed:
            raise ValueError(f"Algorithm must be one of {allowed}, got '{self.algorithm}'")


class DeterministicHashStrategy(AnonymizationStrategy):
    """Hash-based anonymization using HMAC (resistant to rainbow tables).

    Features:
        - Deterministic: Same input + seed = same hash
        - Rainbow-table resistant: Uses HMAC with secret key
        - Unique: Preserves uniqueness for referential integrity
        - Configurable: Algorithm, length, prefix
        - Fast: One-way operation (no reversibility)

    Security:
        - Uses HMAC-SHA256 by default (not plain SHA256)
        - Secret key from the ANONYMIZATION_SECRET env var — mandatory, no default
        - Prevents offline attacks even if seed is compromised

    Example:
        >>> import os
        >>> os.environ['ANONYMIZATION_SECRET'] = 'my-secret'
        >>> config = DeterministicHashConfig(
        ...     seed_env_var='ANONYMIZATION_SEED',
        ...     algorithm='sha256',
        ...     length=16,
        ...     prefix='hash_'
        ... )
        >>> strategy = DeterministicHashStrategy(config)
        >>> result = strategy.anonymize('john@example.com')
        >>> result  # e.g., 'hash_a1b2c3d4e5f6g7h8'
        'hash_...'
    """

    # Lets StrategyRegistry.get("hash") build the right config (not the base
    # StrategyConfig, which lacks algorithm / length / validate_algorithm).
    config_type = DeterministicHashConfig
    strategy_name = "hash"

    def __init__(self, config: DeterministicHashConfig | None = None):
        """Initialize strategy with configuration.

        Args:
            config: DeterministicHashConfig instance

        Raises:
            ValueError: If algorithm is invalid
        """
        config = config or DeterministicHashConfig()
        config.validate_algorithm()
        super().__init__(config)
        self.config: DeterministicHashConfig = config
        self._pseudonymizer: Pseudonymizer | None = None

    def anonymize(self, value: Any) -> Any:
        """Hash a value using HMAC.

        Args:
            value: Value to hash (can be any type)

        Returns:
            Hashed value as string with optional prefix and truncation

        Raises:
            ConfigurationError: ``ANONYMIZATION_SECRET`` is not set (``CONFIG_009``).

        Example:
            >>> strategy = DeterministicHashStrategy(DeterministicHashConfig(seed=12345))
            >>> h1 = strategy.anonymize('test')
            >>> h2 = strategy.anonymize('test')
            >>> h1 == h2  # Deterministic
            True
        """
        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        if isinstance(value, str) and value == "":
            return ""

        if self._pseudonymizer is None:
            self._pseudonymizer = Pseudonymizer(algorithm=self.config.algorithm)

        # Key = f"{seed}{secret}", message = value — the derivation this strategy
        # has always used, so anyone who already set a real secret sees the same
        # output.
        hash_value = self._pseudonymizer.hex(value, seed=self._seed, length=self.config.length)

        # Apply prefix if specified
        if self.config.prefix:
            hash_value = f"{self.config.prefix}{hash_value}"

        return hash_value

    def validate(self, value: Any) -> bool:
        """Hash strategy can handle any value type.

        Args:
            value: Sample value (not used, hashing works for anything)

        Returns:
            Always True (hashing works for all types)
        """
        # Hash strategy can handle any value type
        del value
        return True
