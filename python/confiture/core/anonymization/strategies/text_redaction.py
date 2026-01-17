"""Text redaction anonymization strategy.

Provides regex-based text pattern matching and redaction:
- Match patterns (emails, URLs, phone numbers, SSN, etc)
- Redact matching content
- Preserve text structure
- Configurable replacement patterns
- Case-insensitive matching

Useful for documents, logs, and unstructured text.
"""

import re
from dataclasses import dataclass, field

from confiture.core.anonymization.strategy import AnonymizationStrategy, StrategyConfig

# Common patterns for redaction
COMMON_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone_us": r"\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b",
    "ssn": r"\b(?:\d{3}-\d{2}-\d{4}|\d{9})\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "url": r"https?://[^\s]+",
    "ipv4": r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
    "date_us": r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/(?:\d{4}|\d{2})\b",
}


@dataclass
class TextRedactionConfig(StrategyConfig):
    """Configuration for text redaction strategy.

    Attributes:
        seed: Seed for deterministic randomization (unused for redaction)
        patterns: List of pattern names or regex patterns to redact
        replacement: Replacement string (can include {match} for length-aware masking)
        case_insensitive: If True, case-insensitive matching (default True)
        preserve_length: If True, replacement length matches original (default False)

    Example:
        >>> config = TextRedactionConfig(
        ...     seed=12345,
        ...     patterns=["email", "phone_us"],
        ...     replacement="[REDACTED]"
        ... )
    """

    patterns: list[str] = field(default_factory=lambda: ["email"])
    replacement: str = "[REDACTED]"
    case_insensitive: bool = True
    preserve_length: bool = False


class TextRedactionStrategy(AnonymizationStrategy):
    """Anonymization strategy for redacting text patterns.

    Provides regex-based pattern matching and redaction for unstructured text:
    - Built-in patterns (email, phone, SSN, credit card, URL, IP, date)
    - Custom regex patterns
    - Configurable replacement strings
    - Length-aware redaction

    Features:
    - Pattern library
    - Case-insensitive matching
    - Multiple pattern support
    - Preserve text structure

    Example:
        >>> config = TextRedactionConfig(patterns=["email", "phone_us"])
        >>> strategy = TextRedactionStrategy(config)
        >>> strategy.anonymize("Call me at 555-123-4567 or email john@example.com")
        'Call me at [REDACTED] or email [REDACTED]'
    """

    config_type = TextRedactionConfig
    strategy_name = "text_redaction"

    def __init__(self, config: TextRedactionConfig | None = None):
        """Initialize strategy with compiled patterns."""
        super().__init__(config or TextRedactionConfig())
        self._compiled_patterns = self._compile_patterns()

    def anonymize(self, value: str | None) -> str | None:
        """Redact matching text patterns.

        Args:
            value: Text to redact

        Returns:
            Text with matching patterns redacted

        Example:
            >>> strategy.anonymize("Email: john@example.com")
            'Email: [REDACTED]'
        """
        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return value

        result = value

        # Apply each pattern
        for pattern in self._compiled_patterns:
            result = pattern["compiled"].sub(
                lambda m: self._get_replacement(m.group(0)),
                result,
            )

        return result

    def validate(self, value: str) -> bool:
        """Check if strategy can handle this value type.

        Args:
            value: Sample value to validate

        Returns:
            True if value is a string or None
        """
        return isinstance(value, str) or value is None

    def _compile_patterns(self) -> list[dict]:
        """Compile configured patterns into regex objects.

        Returns:
            List of compiled pattern dictionaries
        """
        compiled = []
        flags = re.IGNORECASE if self.config.case_insensitive else 0

        for pattern_name in self.config.patterns:
            # Get built-in pattern or use as custom regex
            regex_pattern = COMMON_PATTERNS.get(pattern_name, pattern_name)

            try:
                compiled_regex = re.compile(regex_pattern, flags)
                compiled.append({
                    "name": pattern_name if pattern_name in COMMON_PATTERNS else "custom",
                    "pattern": regex_pattern,
                    "compiled": compiled_regex,
                })
            except re.error:
                # Skip invalid patterns
                continue

        return compiled

    def _get_replacement(self, original: str) -> str:
        """Get replacement string for matched text.

        Args:
            original: Original matched text

        Returns:
            Replacement string
        """
        if self.config.preserve_length:
            # Match length of original
            return self.config.replacement[0] * len(original)
        else:
            return self.config.replacement

    def short_name(self) -> str:
        """Return short strategy name for logging.

        Returns:
            Short name (e.g., "text_redaction:email_phone")
        """
        pattern_names = []
        for pattern_name in self.config.patterns:
            if pattern_name in COMMON_PATTERNS:
                pattern_names.append(pattern_name)
            else:
                pattern_names.append("custom")

        patterns_str = "_".join(pattern_names[:3])  # Limit to 3 for readability
        return f"{self.strategy_name}:{patterns_str}"
