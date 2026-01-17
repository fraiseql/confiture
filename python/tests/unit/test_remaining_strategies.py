"""Unit tests for remaining strategies: text redaction, preserve, custom.

Tests for:
- Text redaction with patterns
- Preserve strategy (no-op)
- Custom function-based strategies
"""

import pytest

from confiture.core.anonymization.strategies.custom import (
    CustomConfig,
    CustomLambdaStrategy,
    CustomStrategy,
)
from confiture.core.anonymization.strategies.preserve import (
    PreserveConfig,
    PreserveStrategy,
)
from confiture.core.anonymization.strategies.text_redaction import (
    TextRedactionConfig,
    TextRedactionStrategy,
)


class TestTextRedaction:
    """Tests for text redaction strategy."""

    def test_redact_email(self):
        """Test email redaction."""
        config = TextRedactionConfig(patterns=["email"], replacement="[EMAIL]")
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Contact me at john@example.com")

        assert "[EMAIL]" in result
        assert "john@example.com" not in result

    def test_redact_multiple_emails(self):
        """Test multiple emails redacted."""
        config = TextRedactionConfig(patterns=["email"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize(
            "Email john@example.com or jane@test.org for details"
        )

        # Both emails should be redacted
        assert "john@example.com" not in result
        assert "jane@test.org" not in result

    def test_redact_phone_us(self):
        """Test US phone number redaction."""
        config = TextRedactionConfig(patterns=["phone_us"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Call 555-123-4567 or (555) 987-6543")

        # Phone numbers should be redacted
        assert "555-123-4567" not in result

    def test_redact_ssn(self):
        """Test SSN redaction."""
        config = TextRedactionConfig(patterns=["ssn"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("SSN: 123-45-6789")

        assert "123-45-6789" not in result
        assert "[REDACTED]" in result

    def test_redact_credit_card(self):
        """Test credit card redaction."""
        config = TextRedactionConfig(patterns=["credit_card"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Card: 4242-4242-4242-4242")

        assert "4242-4242-4242-4242" not in result

    def test_redact_url(self):
        """Test URL redaction."""
        config = TextRedactionConfig(patterns=["url"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Visit https://example.com for info")

        assert "https://example.com" not in result

    def test_redact_multiple_patterns(self):
        """Test redacting multiple pattern types."""
        config = TextRedactionConfig(patterns=["email", "phone_us"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize(
            "Email john@example.com or call 555-123-4567"
        )

        assert "john@example.com" not in result
        assert "555-123-4567" not in result

    def test_case_insensitive_redaction(self):
        """Test case-insensitive pattern matching."""
        config = TextRedactionConfig(patterns=["email"], case_insensitive=True)
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Contact: JOHN@EXAMPLE.COM")

        # Should still be redacted despite uppercase
        assert "JOHN@EXAMPLE.COM" not in result

    def test_case_sensitive_redaction(self):
        """Test case-sensitive pattern matching."""
        config = TextRedactionConfig(patterns=["email"], case_insensitive=False)
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Contact: john@example.com")

        # Lowercase email should be redacted
        assert "john@example.com" not in result

    def test_preserve_length_redaction(self):
        """Test preserve-length redaction."""
        config = TextRedactionConfig(
            patterns=["email"], replacement="*", preserve_length=True
        )
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("Email: john@example.com")

        # Should have same length as original
        assert result.count("*") == len("john@example.com")

    def test_none_returns_none(self):
        """Test None returns None."""
        config = TextRedactionConfig(patterns=["email"])
        strategy = TextRedactionStrategy(config)
        assert strategy.anonymize(None) is None

    def test_empty_string_returns_empty(self):
        """Test empty string returns empty."""
        config = TextRedactionConfig(patterns=["email"])
        strategy = TextRedactionStrategy(config)
        assert strategy.anonymize("") == ""

    def test_no_matches_unchanged(self):
        """Test text with no matches is unchanged."""
        config = TextRedactionConfig(patterns=["email"])
        strategy = TextRedactionStrategy(config)
        original = "This text has no emails"
        result = strategy.anonymize(original)

        assert result == original

    def test_custom_regex_pattern(self):
        """Test custom regex pattern."""
        config = TextRedactionConfig(patterns=[r"\d{3}-\d{2}-\d{4}"])
        strategy = TextRedactionStrategy(config)
        result = strategy.anonymize("ID: 123-45-6789")

        assert "123-45-6789" not in result


class TestPreserveStrategy:
    """Tests for preserve (no-op) strategy."""

    def test_preserve_string(self):
        """Test string is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.anonymize("secret data") == "secret data"

    def test_preserve_number(self):
        """Test number is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.anonymize(12345) == 12345

    def test_preserve_none(self):
        """Test None is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.anonymize(None) is None

    def test_preserve_empty_string(self):
        """Test empty string is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.anonymize("") == ""

    def test_preserve_list(self):
        """Test list is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        original = [1, 2, 3]
        assert strategy.anonymize(original) == original

    def test_preserve_dict(self):
        """Test dict is preserved unchanged."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        original = {"key": "value"}
        assert strategy.anonymize(original) == original

    def test_validate_accepts_all(self):
        """Test validate returns True for all types."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.validate("string") is True
        assert strategy.validate(123) is True
        assert strategy.validate(None) is True
        assert strategy.validate([]) is True
        assert strategy.validate({}) is True

    def test_short_name(self):
        """Test short name."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        assert strategy.short_name() == "preserve"


class TestCustomStrategy:
    """Tests for custom function-based strategy."""

    def test_custom_func_uppercase(self):
        """Test custom function that uppercases."""
        def uppercase(value):
            return value.upper() if isinstance(value, str) else value

        config = CustomConfig(seed=12345, func=uppercase, name="uppercase")
        strategy = CustomStrategy(config)
        assert strategy.anonymize("hello") == "HELLO"

    def test_custom_func_with_seed(self):
        """Test custom function that uses seed."""
        def hash_with_seed(value, seed):
            return f"{value}_{seed}"

        config = CustomConfig(
            seed=12345, func=hash_with_seed, name="hash", accepts_seed=True
        )
        strategy = CustomStrategy(config)
        result = strategy.anonymize("data")

        assert result == "data_12345"

    def test_custom_func_none_handling(self):
        """Test custom function with None."""
        def identity(value):
            return value

        config = CustomConfig(func=identity)
        strategy = CustomStrategy(config)
        assert strategy.anonymize(None) is None

    def test_custom_func_not_configured(self):
        """Test error when function not configured."""
        config = CustomConfig(func=None)
        strategy = CustomStrategy(config)

        with pytest.raises(RuntimeError, match="requires 'func'"):
            strategy.anonymize("test")

    def test_custom_func_exception_handling(self):
        """Test exception from custom function is wrapped."""
        def failing_func(value):
            raise ValueError("Custom error")

        config = CustomConfig(func=failing_func, name="failing")
        strategy = CustomStrategy(config)

        with pytest.raises(Exception, match="Error in custom anonymization"):
            strategy.anonymize("test")

    def test_custom_validate_accepts_all(self):
        """Test custom validate accepts all types."""
        config = CustomConfig(func=lambda x: x)
        strategy = CustomStrategy(config)
        assert strategy.validate("string") is True
        assert strategy.validate(123) is True
        assert strategy.validate(None) is True

    def test_custom_short_name(self):
        """Test short name includes custom function name."""
        config = CustomConfig(func=lambda x: x, name="my_func")
        strategy = CustomStrategy(config)
        assert strategy.short_name() == "custom:my_func"


class TestCustomLambdaStrategy:
    """Tests for custom lambda strategy."""

    def test_lambda_simple(self):
        """Test simple lambda function."""
        config = CustomConfig(func=lambda x: f"masked_{x}", name="mask")
        strategy = CustomLambdaStrategy(config)
        assert strategy.anonymize("data") == "masked_data"

    def test_lambda_hash(self):
        """Test lambda that generates hash."""
        config = CustomConfig(func=lambda x: f"hash_{hash(x)}", name="hash")
        strategy = CustomLambdaStrategy(config)
        result = strategy.anonymize("test")

        assert result.startswith("hash_")

    def test_lambda_uppercase(self):
        """Test lambda that uppercases."""
        config = CustomConfig(
            func=lambda x: x.upper() if isinstance(x, str) else x,
            name="upper",
        )
        strategy = CustomLambdaStrategy(config)
        assert strategy.anonymize("hello") == "HELLO"

    def test_lambda_not_configured(self):
        """Test error when lambda not configured."""
        config = CustomConfig(func=None)
        strategy = CustomLambdaStrategy(config)

        with pytest.raises(RuntimeError, match="requires 'func'"):
            strategy.anonymize("test")

    def test_lambda_short_name(self):
        """Test short name."""
        config = CustomConfig(func=lambda x: x, name="my_lambda")
        strategy = CustomLambdaStrategy(config)
        assert strategy.short_name() == "custom_lambda:my_lambda"
