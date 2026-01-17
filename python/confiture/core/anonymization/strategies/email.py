"""Email masking anonymization strategy.

Generates deterministic fake emails from real ones, useful for:
    - PII protection in test/staging environments
    - Preserving email-like format for testing
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
class EmailMaskConfig(StrategyConfig):
    """Configuration for EmailMaskingStrategy.

    Attributes:
        format: Email format template (use {hash} placeholder)
        hash_length: Length of hash in generated email
        preserve_domain: If True, keep original domain (not recommended)
        seed_env_var: Environment variable containing seed
        seed: Hardcoded seed (testing only)
    """

    format: str = "user_{hash}@example.com"
    """Email format template with {hash} placeholder."""

    hash_length: int = 8
    """Length of hash portion (e.g., 8 = user_12345678@example.com)."""

    preserve_domain: bool = False
    """If True, keep original domain (security risk, not recommended)."""


class EmailMaskingStrategy(AnonymizationStrategy):
    """Generate deterministic fake emails from real ones.

    Features:
        - Deterministic: Same email + seed = same fake email
        - Format customizable: Template-based generation
        - Format preserving: Output looks like a real email
        - Unique: Preserves uniqueness for referential integrity

    Security Note:
        - preserve_domain=False (default) is more secure
        - preserve_domain=True leaks organizational information
        - Should always use seed from environment variable

    Example:
        >>> config = EmailMaskConfig(
        ...     format="user_{hash}@example.com",
        ...     hash_length=8,
        ...     seed_env_var='ANONYMIZATION_SEED'
        ... )
        >>> strategy = EmailMaskingStrategy(config)
        >>> result = strategy.anonymize('john@example.com')
        >>> result  # e.g., 'user_a1b2c3d4@example.com'
        'user_a1b2c3d4@example.com'
    """

    # Simple email regex for validation
    EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

    def __init__(self, config: EmailMaskConfig | None = None):
        """Initialize email masking strategy.

        Args:
            config: EmailMaskConfig instance
        """
        config = config or EmailMaskConfig()
        super().__init__(config)
        self.config: EmailMaskConfig = config

    def anonymize(self, value: Any) -> Any:
        """Generate fake email from real email.

        Args:
            value: Email address to anonymize

        Returns:
            Fake email with same format as original

        Example:
            >>> strategy = EmailMaskingStrategy(EmailMaskConfig(seed=12345))
            >>> strategy.anonymize('alice@example.com')
            'user_a1b2c3d4@example.com'
        """
        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        value_str = str(value).strip()
        if not value_str:
            return ""

        # Create deterministic hash from email
        hash_value = hashlib.sha256(f"{self._seed}:{value_str}".encode()).hexdigest()[
            : self.config.hash_length
        ]

        # Extract domain if preserving (not recommended)
        if self.config.preserve_domain:
            try:
                _, domain = value_str.split("@", 1)
            except ValueError:
                # Not a valid email, use example domain
                domain = "example.com"
        else:
            domain = "example.com"

        # Format output
        output = self.config.format.format(hash=hash_value)

        # Replace example.com with actual domain if requested
        if self.config.preserve_domain:
            output = output.replace("example.com", domain)

        return output

    def validate(self, value: Any) -> bool:
        """Check if value looks like an email address.

        Args:
            value: Value to validate

        Returns:
            True if value matches basic email pattern
        """
        if value is None:
            return False

        value_str = str(value).strip()
        return bool(self.EMAIL_REGEX.match(value_str))
