"""Simple redaction anonymization strategy.

One-size-fits-all redaction for sensitive data that should be completely hidden,
not anonymized to a plausible value.
"""

from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class RedactConfig(StrategyConfig):
    """Configuration for SimpleRedactStrategy.

    Attributes:
        replacement: Text to replace sensitive values with
        seed_env_var: Environment variable containing seed (unused for redaction)
        seed: Hardcoded seed (unused for redaction)
    """

    replacement: str = "[REDACTED]"
    """Text to use for all redacted values."""


class SimpleRedactStrategy(AnonymizationStrategy):
    """Simple one-size-fits-all redaction strategy.

    Features:
        - Fast: No hashing or computation
        - Complete: All data values replaced with same text
        - Safe: Zero information leakage
        - Simple: Easy to understand and audit

    Use when:
        - PII is highly sensitive (no testing needed with real-like data)
        - You don't need to preserve data format (testing doesn't rely on structure)
        - You want maximum privacy with zero complexity

    Don't use when:
        - You need to preserve uniqueness for testing (FK constraints)
        - You need format-preserving anonymization (testing email-like values)
        - You need to correlate anonymized data across tables

    Example:
        >>> config = RedactConfig(replacement="[HIDDEN]")
        >>> strategy = SimpleRedactStrategy(config)
        >>> strategy.anonymize("secret data")
        '[HIDDEN]'
    """

    def __init__(self, config: RedactConfig | None = None):
        """Initialize redaction strategy.

        Args:
            config: RedactConfig instance
        """
        config = config or RedactConfig()
        super().__init__(config)
        self.config: RedactConfig = config

    def anonymize(self, value: Any) -> Any:
        """Redact value to replacement text.

        Args:
            value: Value to redact

        Returns:
            Replacement text (same for all values)

        Example:
            >>> strategy = SimpleRedactStrategy()
            >>> strategy.anonymize("anything")
            '[REDACTED]'
            >>> strategy.anonymize("123")
            '[REDACTED]'
            >>> strategy.anonymize(None)  # Special case: NULL stays NULL
        """
        # Special case: NULL stays NULL
        if value is None:
            return None

        # All other values replaced with redaction text
        return self.config.replacement

    def validate(self, value: Any) -> bool:
        """Redaction works for any value type.

        Args:
            value: Value to validate (not really used)

        Returns:
            Always True (redaction works for all types)
        """
        # Redaction works for all types
        del value
        return True
