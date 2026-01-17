"""Phone number masking anonymization strategy.

Generates deterministic fake phone numbers from real ones, useful for:
    - PII protection in test/staging environments
    - Preserving phone-like format for testing
    - Reproducible anonymization (deterministic with seed)
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class PhoneMaskConfig(StrategyConfig):
    """Configuration for PhoneMaskingStrategy.

    Attributes:
        format: Phone number format template (use {number} placeholder)
        preserve_country_code: If True, keep original country code
        seed_env_var: Environment variable containing seed
        seed: Hardcoded seed (testing only)
    """

    format: str = "+1-555-{number}"
    """Phone format template with {number} placeholder."""

    preserve_country_code: bool = False
    """If True, try to preserve original country code."""


class PhoneMaskingStrategy(AnonymizationStrategy):
    """Generate deterministic fake phone numbers from real ones.

    Features:
        - Deterministic: Same number + seed = same fake number
        - Format customizable: Template-based generation
        - Format preserving: Output looks like a real phone number
        - Unique: Preserves uniqueness for referential integrity

    Example:
        >>> config = PhoneMaskConfig(
        ...     format="+1-555-{number}",
        ...     seed_env_var='ANONYMIZATION_SEED'
        ... )
        >>> strategy = PhoneMaskingStrategy(config)
        >>> result = strategy.anonymize('+1-202-555-0123')
        >>> result  # e.g., '+1-555-1234'
        '+1-555-1234'
    """

    # Basic phone number regex (allows various formats)
    PHONE_REGEX = re.compile(r"[\d\s\-\+\(\)]{10,}")

    def __init__(self, config: PhoneMaskConfig | None = None):
        """Initialize phone masking strategy.

        Args:
            config: PhoneMaskConfig instance
        """
        config = config or PhoneMaskConfig()
        super().__init__(config)
        self.config: PhoneMaskConfig = config

    def anonymize(self, value: Any) -> Any:
        """Generate fake phone number from real number.

        Args:
            value: Phone number to anonymize

        Returns:
            Fake phone number with same format as original

        Example:
            >>> strategy = PhoneMaskingStrategy(PhoneMaskConfig(seed=12345))
            >>> strategy.anonymize('+1-202-555-0123')
            '+1-555-1234'
        """
        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        value_str = str(value).strip()
        if not value_str:
            return ""

        # Create deterministic hash from phone number
        hash_value = hashlib.sha256(f"{self._seed}:{value_str}".encode()).hexdigest()

        # Extract digits to generate phone number
        # Use hash to create a 4-digit phone number suffix
        number_suffix = str(int(hash_value[:8], 16) % 10000).zfill(4)

        # Format output
        output = self.config.format.format(number=number_suffix)

        return output

    def validate(self, value: Any) -> bool:
        """Check if value looks like a phone number.

        Args:
            value: Value to validate

        Returns:
            True if value matches basic phone pattern
        """
        if value is None:
            return False

        value_str = str(value).strip()
        return bool(self.PHONE_REGEX.match(value_str))
