"""Comprehensive tests for simple redaction anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.redact import (
    RedactConfig,
    SimpleRedactStrategy,
)


class TestSimpleRedactStrategy:
    """Tests for SimpleRedactStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = RedactConfig(seed=12345)
        return SimpleRedactStrategy(config)

    @pytest.fixture
    def strategy_custom(self):
        """Create strategy with custom replacement."""
        config = RedactConfig(seed=12345, replacement="[HIDDEN]")
        return SimpleRedactStrategy(config)

    @pytest.fixture
    def strategy_empty(self):
        """Create strategy with empty replacement."""
        config = RedactConfig(seed=12345, replacement="")
        return SimpleRedactStrategy(config)

    @pytest.fixture
    def strategy_asterisks(self):
        """Create strategy with asterisk replacement."""
        config = RedactConfig(seed=12345, replacement="****")
        return SimpleRedactStrategy(config)

    # Basic redaction tests
    def test_redact_string(self, strategy_default):
        """Test redacting a string."""
        result = strategy_default.anonymize("secret data")
        assert result == "[REDACTED]"

    def test_redact_different_strings_same_output(self, strategy_default):
        """Test all strings produce same output."""
        result1 = strategy_default.anonymize("string1")
        result2 = strategy_default.anonymize("string2")
        assert result1 == result2 == "[REDACTED]"

    def test_redact_integer(self, strategy_default):
        """Test redacting an integer."""
        result = strategy_default.anonymize(12345)
        assert result == "[REDACTED]"

    def test_redact_float(self, strategy_default):
        """Test redacting a float."""
        result = strategy_default.anonymize(123.45)
        assert result == "[REDACTED]"

    def test_redact_list(self, strategy_default):
        """Test redacting a list."""
        result = strategy_default.anonymize([1, 2, 3])
        assert result == "[REDACTED]"

    def test_redact_dict(self, strategy_default):
        """Test redacting a dict."""
        result = strategy_default.anonymize({"key": "value"})
        assert result == "[REDACTED]"

    def test_redact_boolean(self, strategy_default):
        """Test redacting a boolean."""
        result = strategy_default.anonymize(True)
        assert result == "[REDACTED]"

    # None handling tests
    def test_redact_none_returns_none(self, strategy_default):
        """Test None input returns None."""
        assert strategy_default.anonymize(None) is None

    def test_none_not_replaced(self, strategy_default):
        """Test None is not replaced with redaction text."""
        result = strategy_default.anonymize(None)
        assert result is None
        assert result != "[REDACTED]"

    # Custom replacement tests
    def test_custom_replacement(self, strategy_custom):
        """Test custom replacement text."""
        result = strategy_custom.anonymize("secret")
        assert result == "[HIDDEN]"

    def test_empty_replacement(self, strategy_empty):
        """Test empty replacement text."""
        result = strategy_empty.anonymize("secret")
        assert result == ""

    def test_asterisk_replacement(self, strategy_asterisks):
        """Test asterisk replacement."""
        result = strategy_asterisks.anonymize("secret")
        assert result == "****"

    # Empty string tests
    def test_redact_empty_string(self, strategy_default):
        """Test redacting empty string."""
        result = strategy_default.anonymize("")
        assert result == "[REDACTED]"

    def test_redact_whitespace(self, strategy_default):
        """Test redacting whitespace."""
        result = strategy_default.anonymize("   ")
        assert result == "[REDACTED]"

    # Validate method tests
    def test_validate_always_true(self, strategy_default):
        """Test validate always returns True."""
        assert strategy_default.validate("string") is True
        assert strategy_default.validate(12345) is True
        assert strategy_default.validate(None) is True
        assert strategy_default.validate([1, 2, 3]) is True
        assert strategy_default.validate({"key": "value"}) is True
        assert strategy_default.validate(True) is True

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        strategy = SimpleRedactStrategy()
        result = strategy.anonymize("test")
        assert result == "[REDACTED]"

    # Idempotency test
    def test_redact_idempotent(self, strategy_default):
        """Test redacting redacted value gives same result."""
        result1 = strategy_default.anonymize("secret")
        result2 = strategy_default.anonymize(result1)
        assert result1 == result2 == "[REDACTED]"


class TestRedactConfig:
    """Tests for RedactConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RedactConfig(seed=12345)
        assert config.replacement == "[REDACTED]"

    def test_custom_replacement(self):
        """Test custom replacement."""
        config = RedactConfig(seed=12345, replacement="[HIDDEN]")
        assert config.replacement == "[HIDDEN]"

    def test_empty_replacement(self):
        """Test empty replacement."""
        config = RedactConfig(seed=12345, replacement="")
        assert config.replacement == ""

    def test_long_replacement(self):
        """Test long replacement text."""
        long_text = "X" * 100
        config = RedactConfig(seed=12345, replacement=long_text)
        assert config.replacement == long_text

    def test_unicode_replacement(self):
        """Test unicode replacement."""
        config = RedactConfig(seed=12345, replacement="[非公開]")
        assert config.replacement == "[非公開]"


class TestRedactEdgeCases:
    """Edge case tests for redaction."""

    def test_various_data_types(self):
        """Test redaction works for various data types."""
        config = RedactConfig(seed=12345)
        strategy = SimpleRedactStrategy(config)

        test_values = [
            "string",
            123,
            123.45,
            True,
            False,
            [1, 2, 3],
            {"key": "value"},
            (1, 2, 3),
            {1, 2, 3},
            b"bytes",
        ]

        for value in test_values:
            result = strategy.anonymize(value)
            assert result == "[REDACTED]"

    def test_seed_does_not_affect_output(self):
        """Test seed has no effect on redaction output."""
        config1 = RedactConfig(seed=12345)
        config2 = RedactConfig(seed=67890)
        strategy1 = SimpleRedactStrategy(config1)
        strategy2 = SimpleRedactStrategy(config2)

        # Different seeds should still produce same output
        result1 = strategy1.anonymize("test")
        result2 = strategy2.anonymize("test")
        assert result1 == result2

    def test_consistency(self):
        """Test redaction is consistent across calls."""
        config = RedactConfig(seed=12345)
        strategy = SimpleRedactStrategy(config)

        results = [strategy.anonymize("test") for _ in range(100)]
        assert all(r == "[REDACTED]" for r in results)

    def test_special_characters(self):
        """Test redaction of special characters."""
        config = RedactConfig(seed=12345)
        strategy = SimpleRedactStrategy(config)

        special_values = [
            "test\n",
            "test\t",
            "test\r\n",
            "test\0",
            "<script>alert('xss')</script>",
            "'; DROP TABLE users;--",
        ]

        for value in special_values:
            result = strategy.anonymize(value)
            assert result == "[REDACTED]"
