"""Comprehensive tests for phone masking anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.phone import (
    PhoneMaskConfig,
    PhoneMaskingStrategy,
)


class TestPhoneMaskingStrategy:
    """Tests for PhoneMaskingStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = PhoneMaskConfig(seed=12345)
        return PhoneMaskingStrategy(config)

    @pytest.fixture
    def strategy_custom_format(self):
        """Create strategy with custom format."""
        config = PhoneMaskConfig(seed=12345, format="(555) 123-{number}")
        return PhoneMaskingStrategy(config)

    @pytest.fixture
    def strategy_international(self):
        """Create strategy with international format."""
        config = PhoneMaskConfig(seed=12345, format="+44-20-{number}")
        return PhoneMaskingStrategy(config)

    # Basic anonymization tests
    def test_anonymize_basic_phone(self, strategy_default):
        """Test basic phone anonymization."""
        result = strategy_default.anonymize("+1-202-555-0123")
        assert result != "+1-202-555-0123"
        assert "+1-555-" in result

    def test_anonymize_deterministic(self, strategy_default):
        """Test same input gives same output."""
        phone = "+1-202-555-0123"
        result1 = strategy_default.anonymize(phone)
        result2 = strategy_default.anonymize(phone)
        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = PhoneMaskConfig(seed=12345)
        config2 = PhoneMaskConfig(seed=67890)
        strategy1 = PhoneMaskingStrategy(config1)
        strategy2 = PhoneMaskingStrategy(config2)

        phone = "+1-202-555-0123"
        result1 = strategy1.anonymize(phone)
        result2 = strategy2.anonymize(phone)
        assert result1 != result2

    def test_anonymize_different_phones_different_outputs(self, strategy_default):
        """Test different phones produce different outputs."""
        result1 = strategy_default.anonymize("+1-202-555-0123")
        result2 = strategy_default.anonymize("+1-202-555-0456")
        assert result1 != result2

    # Custom format tests
    def test_custom_format(self, strategy_custom_format):
        """Test custom format is applied."""
        result = strategy_custom_format.anonymize("+1-202-555-0123")
        assert "(555) 123-" in result

    def test_international_format(self, strategy_international):
        """Test international format."""
        result = strategy_international.anonymize("+1-202-555-0123")
        assert "+44-20-" in result

    def test_number_suffix_is_4_digits(self, strategy_default):
        """Test number suffix is exactly 4 digits."""
        result = strategy_default.anonymize("+1-202-555-0123")
        # Format is +1-555-{number}
        suffix = result.split("-")[-1]
        assert len(suffix) == 4
        assert suffix.isdigit()

    # Edge cases
    def test_anonymize_none_returns_none(self, strategy_default):
        """Test None input returns None."""
        assert strategy_default.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_default):
        """Test empty string returns empty string."""
        assert strategy_default.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_default):
        """Test whitespace returns empty string."""
        assert strategy_default.anonymize("   ") == ""

    def test_anonymize_non_phone_string(self, strategy_default):
        """Test non-phone string is still processed."""
        result = strategy_default.anonymize("notaphone")
        # Should still produce output with format
        assert "+1-555-" in result

    # Various phone formats
    def test_anonymize_phone_with_dashes(self, strategy_default):
        """Test phone with dashes."""
        result = strategy_default.anonymize("202-555-0123")
        assert "+1-555-" in result

    def test_anonymize_phone_with_parentheses(self, strategy_default):
        """Test phone with parentheses."""
        result = strategy_default.anonymize("(202) 555-0123")
        assert "+1-555-" in result

    def test_anonymize_phone_with_dots(self, strategy_default):
        """Test phone with dots."""
        result = strategy_default.anonymize("202.555.0123")
        assert "+1-555-" in result

    def test_anonymize_phone_no_separators(self, strategy_default):
        """Test phone without separators."""
        result = strategy_default.anonymize("2025550123")
        assert "+1-555-" in result

    def test_anonymize_phone_with_country_code(self, strategy_default):
        """Test phone with country code."""
        result = strategy_default.anonymize("+44 20 7123 4567")
        assert "+1-555-" in result

    def test_anonymize_phone_with_extension(self, strategy_default):
        """Test phone with extension."""
        result = strategy_default.anonymize("202-555-0123 ext. 456")
        assert "+1-555-" in result

    # Validate method tests
    def test_validate_valid_phone_with_dashes(self, strategy_default):
        """Test validate accepts phone with dashes."""
        assert strategy_default.validate("202-555-0123") is True

    def test_validate_valid_phone_with_plus(self, strategy_default):
        """Test validate accepts phone with plus."""
        assert strategy_default.validate("+1-202-555-0123") is True

    def test_validate_valid_phone_with_parentheses(self, strategy_default):
        """Test validate accepts phone with parentheses."""
        assert strategy_default.validate("(202) 555-0123") is True

    def test_validate_valid_phone_spaces(self, strategy_default):
        """Test validate accepts phone with spaces."""
        assert strategy_default.validate("202 555 0123") is True

    def test_validate_none(self, strategy_default):
        """Test validate rejects None."""
        assert strategy_default.validate(None) is False

    def test_validate_empty_string(self, strategy_default):
        """Test validate rejects empty string."""
        assert strategy_default.validate("") is False

    def test_validate_too_short(self, strategy_default):
        """Test validate rejects too short string."""
        assert strategy_default.validate("12345") is False

    def test_validate_letters_only(self, strategy_default):
        """Test validate rejects letters only."""
        assert strategy_default.validate("abcdefghij") is False

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        strategy = PhoneMaskingStrategy()
        result = strategy.anonymize("+1-202-555-0123")
        assert "+1-555-" in result


class TestPhoneMaskConfig:
    """Tests for PhoneMaskConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PhoneMaskConfig(seed=12345)
        assert config.format == "+1-555-{number}"
        assert config.preserve_country_code is False

    def test_custom_format(self):
        """Test custom format."""
        config = PhoneMaskConfig(seed=12345, format="(555) {number}")
        assert config.format == "(555) {number}"

    def test_custom_preserve_country_code(self):
        """Test custom preserve_country_code."""
        config = PhoneMaskConfig(seed=12345, preserve_country_code=True)
        assert config.preserve_country_code is True

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = PhoneMaskConfig(
            seed=12345,
            format="+44-{number}",
            preserve_country_code=True,
        )
        assert config.format == "+44-{number}"
        assert config.preserve_country_code is True


class TestPhoneEdgeCases:
    """Edge case tests for phone anonymization."""

    def test_phone_regex_pattern(self):
        """Test PHONE_REGEX pattern exists."""
        assert PhoneMaskingStrategy.PHONE_REGEX is not None
        assert PhoneMaskingStrategy.PHONE_REGEX.match("202-555-0123")

    def test_hash_consistency(self):
        """Test hash is consistent for same input."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        # Same phone should always produce same output
        results = [strategy.anonymize("+1-202-555-0123") for _ in range(5)]
        assert len(set(results)) == 1  # All results should be identical

    def test_numeric_value_converted(self):
        """Test numeric value is converted to string."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        # Should handle non-string input
        result = strategy.anonymize(2025550123)
        assert "+1-555-" in result

    def test_number_suffix_always_4_digits(self):
        """Test number suffix is always 4 digits even with leading zeros."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        # Try multiple inputs to ensure padding works
        phones = [
            "+1-202-555-0001",
            "+1-202-555-0002",
            "+1-202-555-0003",
        ]
        for phone in phones:
            result = strategy.anonymize(phone)
            suffix = result.split("-")[-1]
            assert len(suffix) == 4

    def test_various_international_phones(self):
        """Test various international phone formats."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        phones = [
            "+44 20 7123 4567",  # UK
            "+33 1 23 45 67 89",  # France
            "+49 30 123456",  # Germany
            "+81 3 1234 5678",  # Japan
        ]
        for phone in phones:
            result = strategy.anonymize(phone)
            assert "+1-555-" in result  # All use default format
