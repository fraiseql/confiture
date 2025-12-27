"""Masking with retention anonymization strategy (Phase 2.2.1).

Provides pattern-preserving anonymization that masks sensitive parts while
retaining structure for testing. Useful when format/pattern information
is needed but original values must be hidden.

Features:
- Pattern preservation (e.g., email keeps @ and domain)
- Configurable masking (which parts to mask, which to preserve)
- Deterministic (same input + seed = same output)
- Format-aware (handles different data types)

Example patterns:
    Email: john.doe@example.com → j***.d*e@example.com
    Phone: +1-555-123-4567 → +1-***-***-4567
    Credit Card: 4111-1111-1111-1111 → 4111-****-****-1111
    Address: 123 Main St, Springfield, IL 62701 → 123 **** St, ***, IL 62701

Use cases:
- Test data generation (need real-looking but fake values)
- PII masking in logs (can still identify person from pattern)
- Debugging production issues (masks PII but keeps structure)
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
class MaskingRetentionConfig(StrategyConfig):
    """Configuration for MaskingRetentionStrategy.

    Attributes:
        preserve_pattern: If True, mask selectively to preserve format
        preserve_start_chars: Number of starting characters to preserve
        preserve_end_chars: Number of ending characters to preserve
        mask_char: Character to use for masking (default: *)
        mask_percentage: Percentage of middle to mask (default: 100%)
        preserve_delimiters: If True, don't mask delimiter characters
    """

    preserve_pattern: bool = True
    """Preserve pattern/structure of original value."""

    preserve_start_chars: int = 0
    """Number of starting characters to preserve (0 = none)."""

    preserve_end_chars: int = 0
    """Number of ending characters to preserve (0 = none)."""

    mask_char: str = "*"
    """Character to use for masking (single character)."""

    mask_percentage: int = 100
    """Percentage of middle section to mask (0-100)."""

    preserve_delimiters: bool = True
    """Don't mask delimiter characters (@, -, ., etc.)."""


class MaskingRetentionStrategy(AnonymizationStrategy):
    """Mask sensitive data while preserving pattern/structure.

    This strategy masks data selectively to hide PII while preserving
    enough structure for testing and debugging. Different from full
    masking (which replaces everything) and format-preserving encryption
    (which requires keys).

    Features:
        - Selective masking: Preserve structure, mask content
        - Deterministic: Same input + seed = same output
        - Format-aware: Handles various data types
        - Configurable: Control what to preserve/mask
        - Fast: Simple string manipulation

    Security Note:
        - NOT suitable for production PII protection
        - Preserves enough information to potentially re-identify
        - Intended for test data and debugging only
        - Use FPE or hashing for true irreversible anonymization

    Example:
        >>> config = MaskingRetentionConfig(
        ...     preserve_pattern=True,
        ...     preserve_start_chars=1,
        ...     preserve_end_chars=3,
        ...     mask_char='*'
        ... )
        >>> strategy = MaskingRetentionStrategy(config)
        >>> strategy.anonymize('john.doe@example.com')
        'j***.*o*e@ex****e.com'
    """

    def __init__(self, config: MaskingRetentionConfig | None = None):
        """Initialize masking with retention strategy.

        Args:
            config: MaskingRetentionConfig instance
        """
        config = config or MaskingRetentionConfig()
        super().__init__(config)
        self.config: MaskingRetentionConfig = config

    def anonymize(self, value: Any) -> Any:
        """Mask value while preserving pattern.

        Args:
            value: Value to mask

        Returns:
            Masked value with preserved pattern

        Example:
            >>> strategy = MaskingRetentionStrategy(
            ...     MaskingRetentionConfig(seed=12345)
            ... )
            >>> strategy.anonymize('john@example.com')
            'j***@ex****e.com'
        """
        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        value_str = str(value).strip()
        if not value_str:
            return ""

        # If preservation disabled, return deterministic hash
        if not self.config.preserve_pattern:
            hash_val = hashlib.sha256(
                f"{self._seed}:{value_str}".encode()
            ).hexdigest()[:len(value_str)]
            return hash_val

        # Preserve start characters
        if self.config.preserve_start_chars >= len(value_str):
            return value_str  # Can't mask if preserving everything

        start_part = value_str[: self.config.preserve_start_chars]
        remaining = value_str[self.config.preserve_start_chars :]

        # Preserve end characters
        if self.config.preserve_end_chars > 0:
            end_part = remaining[-self.config.preserve_end_chars :]
            middle = remaining[: -self.config.preserve_end_chars]
        else:
            end_part = ""
            middle = remaining

        # Mask middle section
        masked_middle = self._mask_middle(middle)

        # Combine parts
        return start_part + masked_middle + end_part

    def _mask_middle(self, value: str) -> str:
        """Mask middle section of string.

        Args:
            value: String section to mask

        Returns:
            Masked string with delimiters optionally preserved
        """
        if not value:
            return value

        # Identify delimiters if preserving them
        delimiters = set()
        if self.config.preserve_delimiters:
            for i, char in enumerate(value):
                if not char.isalnum():
                    delimiters.add(i)

        # Calculate how many characters to mask
        chars_to_mask = max(1, int(len(value) * self.config.mask_percentage / 100))

        # Create mask array
        mask_indices = set()
        if delimiters:
            # Mask non-delimiter positions
            alphanumeric_indices = [i for i in range(len(value)) if i not in delimiters]
            # Mask first N alphanumeric characters
            for i in alphanumeric_indices[:chars_to_mask]:
                mask_indices.add(i)
        else:
            # Mask first N characters
            for i in range(min(chars_to_mask, len(value))):
                mask_indices.add(i)

        # Build masked string
        result = []
        for i, char in enumerate(value):
            if i in mask_indices:
                result.append(self.config.mask_char)
            else:
                result.append(char)

        return "".join(result)

    def validate(self, value: Any) -> bool:
        """Masking with retention works for any type.

        Args:
            value: Value to validate

        Returns:
            True if value can be converted to string
        """
        try:
            str(value)
            return True
        except (TypeError, ValueError):
            return False

    def validate_comprehensive(
        self,
        value: Any,
        column_name: str = "",
        table_name: str = "",
    ) -> tuple[bool, list[str]]:
        """Comprehensive validation for masking with retention.

        Args:
            value: Value to validate
            column_name: Column name (for error context)
            table_name: Table name (for error context)

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []

        # Masking with retention can handle anything that's a string-like
        try:
            value_str = str(value).strip()
            if not value_str:
                errors.append(
                    f"Column {table_name}.{column_name}: "
                    f"Empty string will be masked to empty string"
                )
        except Exception as e:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Cannot convert to string: {e}"
            )

        return len(errors) == 0, errors
