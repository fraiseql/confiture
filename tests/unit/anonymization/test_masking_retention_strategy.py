"""Comprehensive tests for masking with retention anonymization strategy.

Tests cover:
- MaskingRetentionConfig configuration
- MaskingRetentionStrategy initialization
- Selective masking behavior
- Pattern preservation
- Delimiter handling
- Edge cases and error handling
"""

import pytest

from confiture.core.anonymization.strategies.masking_retention import (
    MaskingRetentionConfig,
    MaskingRetentionStrategy,
)


class TestMaskingRetentionConfig:
    """Tests for MaskingRetentionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = MaskingRetentionConfig()

        assert config.preserve_pattern is True
        assert config.preserve_start_chars == 0
        assert config.preserve_end_chars == 0
        assert config.mask_char == "*"
        assert config.mask_percentage == 100
        assert config.preserve_delimiters is True

    def test_custom_preserve_start_chars(self):
        """Test custom preserve_start_chars."""
        config = MaskingRetentionConfig(preserve_start_chars=3)
        assert config.preserve_start_chars == 3

    def test_custom_preserve_end_chars(self):
        """Test custom preserve_end_chars."""
        config = MaskingRetentionConfig(preserve_end_chars=4)
        assert config.preserve_end_chars == 4

    def test_custom_mask_char(self):
        """Test custom mask character."""
        config = MaskingRetentionConfig(mask_char="X")
        assert config.mask_char == "X"

    def test_custom_mask_percentage(self):
        """Test custom mask percentage."""
        config = MaskingRetentionConfig(mask_percentage=50)
        assert config.mask_percentage == 50

    def test_preserve_delimiters_disabled(self):
        """Test disabling delimiter preservation."""
        config = MaskingRetentionConfig(preserve_delimiters=False)
        assert config.preserve_delimiters is False

    def test_preserve_pattern_disabled(self):
        """Test disabling pattern preservation."""
        config = MaskingRetentionConfig(preserve_pattern=False)
        assert config.preserve_pattern is False


class TestMaskingRetentionStrategyInit:
    """Tests for MaskingRetentionStrategy initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        strategy = MaskingRetentionStrategy()

        assert strategy.config.preserve_pattern is True
        assert strategy.config.mask_char == "*"

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = MaskingRetentionConfig(
            preserve_start_chars=2,
            preserve_end_chars=3,
            mask_char="X",
        )
        strategy = MaskingRetentionStrategy(config)

        assert strategy.config.preserve_start_chars == 2
        assert strategy.config.preserve_end_chars == 3
        assert strategy.config.mask_char == "X"


class TestMaskingRetentionStrategyAnonymize:
    """Tests for MaskingRetentionStrategy.anonymize() method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with default config."""
        return MaskingRetentionStrategy()

    def test_anonymize_none_returns_none(self, strategy):
        """Test None input returns None."""
        result = strategy.anonymize(None)
        assert result is None

    def test_anonymize_empty_string(self, strategy):
        """Test empty string returns empty string."""
        result = strategy.anonymize("")
        assert result == ""

    def test_anonymize_whitespace_only(self, strategy):
        """Test whitespace-only returns empty string."""
        result = strategy.anonymize("   ")
        assert result == ""

    def test_anonymize_basic_masking(self, strategy):
        """Test basic masking replaces with mask character."""
        result = strategy.anonymize("hello")

        assert "*" in result
        assert len(result) == 5

    def test_anonymize_preserve_start_chars(self):
        """Test preserving start characters."""
        config = MaskingRetentionConfig(preserve_start_chars=2)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert result.startswith("he")
        assert result[2:] == "***"

    def test_anonymize_preserve_end_chars(self):
        """Test preserving end characters."""
        config = MaskingRetentionConfig(preserve_end_chars=2)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert result.endswith("lo")
        assert result[:3] == "***"

    def test_anonymize_preserve_both_start_and_end(self):
        """Test preserving both start and end characters."""
        config = MaskingRetentionConfig(
            preserve_start_chars=1,
            preserve_end_chars=2,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert result[0] == "h"  # First char preserved
        assert result[-2:] == "lo"  # Last 2 preserved
        assert result[1:3] == "**"  # Middle masked


class TestMaskingRetentionDelimiters:
    """Tests for delimiter preservation."""

    def test_preserve_email_delimiters(self):
        """Test preserving @ and . in email."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("john@example.com")

        assert "@" in result
        assert "." in result

    def test_preserve_phone_delimiters(self):
        """Test preserving - in phone numbers."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("555-123-4567")

        assert result.count("-") == 2

    def test_preserve_credit_card_delimiters(self):
        """Test preserving - in credit card numbers."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("4111-1111-1111-1111")

        assert result.count("-") == 3

    def test_no_delimiter_preservation(self):
        """Test disabling delimiter preservation."""
        config = MaskingRetentionConfig(preserve_delimiters=False)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("john@example.com")

        # Without delimiter preservation, everything gets masked
        # (except based on other settings)
        assert "*" in result


class TestMaskingRetentionPatternPreservation:
    """Tests for pattern preservation."""

    def test_pattern_disabled_returns_hash(self):
        """Test disabling pattern returns hash-like value."""
        config = MaskingRetentionConfig(preserve_pattern=False, seed=12345)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        # Should be deterministic hash
        assert len(result) == 5
        # Should not contain mask character (hash is alphanumeric)
        assert "*" not in result

    def test_pattern_disabled_deterministic(self):
        """Test pattern disabled is deterministic."""
        config = MaskingRetentionConfig(preserve_pattern=False, seed=12345)
        strategy = MaskingRetentionStrategy(config)

        result1 = strategy.anonymize("hello")
        result2 = strategy.anonymize("hello")

        assert result1 == result2

    def test_pattern_disabled_different_seeds(self):
        """Test different seeds give different results."""
        config1 = MaskingRetentionConfig(preserve_pattern=False, seed=12345)
        config2 = MaskingRetentionConfig(preserve_pattern=False, seed=67890)

        strategy1 = MaskingRetentionStrategy(config1)
        strategy2 = MaskingRetentionStrategy(config2)

        result1 = strategy1.anonymize("hello")
        result2 = strategy2.anonymize("hello")

        assert result1 != result2


class TestMaskingRetentionMaskPercentage:
    """Tests for mask percentage."""

    def test_full_mask_percentage(self):
        """Test 100% mask percentage."""
        config = MaskingRetentionConfig(mask_percentage=100)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        # All chars should be masked
        assert result == "*****"

    def test_partial_mask_percentage(self):
        """Test 50% mask percentage."""
        config = MaskingRetentionConfig(
            mask_percentage=50,
            preserve_delimiters=False,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello world")

        # Some chars should not be masked
        assert result.count("*") < len("hello world")

    def test_zero_mask_percentage(self):
        """Test 0% mask percentage (minimal masking)."""
        config = MaskingRetentionConfig(mask_percentage=0)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        # Should still mask at least 1 char
        assert result.count("*") >= 1


class TestMaskingRetentionCustomMaskChar:
    """Tests for custom mask character."""

    def test_custom_mask_char_x(self):
        """Test using X as mask character."""
        config = MaskingRetentionConfig(mask_char="X")
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert "X" in result
        assert "*" not in result

    def test_custom_mask_char_hash(self):
        """Test using # as mask character."""
        config = MaskingRetentionConfig(mask_char="#")
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert "#" in result

    def test_custom_mask_char_dot(self):
        """Test using . as mask character."""
        config = MaskingRetentionConfig(mask_char=".")
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")

        assert "." in result


class TestMaskingRetentionValidation:
    """Tests for validation methods."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for validation tests."""
        return MaskingRetentionStrategy()

    def test_validate_string(self, strategy):
        """Test validate accepts string."""
        assert strategy.validate("hello") is True

    def test_validate_int(self, strategy):
        """Test validate accepts int."""
        assert strategy.validate(12345) is True

    def test_validate_float(self, strategy):
        """Test validate accepts float."""
        assert strategy.validate(123.45) is True

    def test_validate_comprehensive_valid(self, strategy):
        """Test comprehensive validation with valid value."""
        is_valid, errors = strategy.validate_comprehensive("hello", "name", "users")

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_comprehensive_empty_string_warning(self, strategy):
        """Test comprehensive validation warns about empty string."""
        is_valid, errors = strategy.validate_comprehensive("", "name", "users")

        # Empty string is "valid" but produces warning
        assert is_valid is False or len(errors) > 0

    def test_validate_comprehensive_includes_context(self, strategy):
        """Test comprehensive validation includes column context."""
        is_valid, errors = strategy.validate_comprehensive("  ", "email", "users")

        # Context should be in error message
        for error in errors:
            assert "users.email" in error


class TestMaskMiddle:
    """Tests for _mask_middle method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for _mask_middle tests."""
        return MaskingRetentionStrategy()

    def test_mask_middle_empty_string(self, strategy):
        """Test _mask_middle with empty string."""
        result = strategy._mask_middle("")
        assert result == ""

    def test_mask_middle_preserves_delimiters(self):
        """Test _mask_middle preserves delimiter positions."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)

        result = strategy._mask_middle("john@test")

        assert "@" in result

    def test_mask_middle_no_delimiter_preservation(self):
        """Test _mask_middle masks everything without delimiter preservation."""
        config = MaskingRetentionConfig(preserve_delimiters=False)
        strategy = MaskingRetentionStrategy(config)

        result = strategy._mask_middle("hello")

        assert result == "*****"


class TestMaskingRetentionEdgeCases:
    """Tests for edge cases."""

    def test_anonymize_single_char(self):
        """Test masking single character."""
        strategy = MaskingRetentionStrategy()
        result = strategy.anonymize("x")

        assert result == "*"

    def test_anonymize_preserve_start_exceeds_length(self):
        """Test preserving more start chars than string length."""
        config = MaskingRetentionConfig(preserve_start_chars=10)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")  # Only 5 chars

        # Should return original when preserve_start >= length
        assert result == "hello"

    def test_anonymize_preserve_end_exceeds_remaining(self):
        """Test preserving end chars when little middle remains."""
        config = MaskingRetentionConfig(
            preserve_start_chars=2,
            preserve_end_chars=2,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("hello")  # 5 chars

        # Start: "he", End: "lo", Middle: "l" -> "he*lo"
        assert result.startswith("he")
        assert result.endswith("lo")

    def test_anonymize_integer_value(self):
        """Test anonymizing integer value."""
        strategy = MaskingRetentionStrategy()
        result = strategy.anonymize(12345)

        assert len(result) == 5

    def test_anonymize_float_value(self):
        """Test anonymizing float value."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)
        result = strategy.anonymize(123.45)

        # Should preserve decimal point
        assert "." in result

    def test_anonymize_all_delimiters(self):
        """Test string with only delimiter characters."""
        config = MaskingRetentionConfig(preserve_delimiters=True)
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("@-._")

        # All should be preserved
        assert result == "@-._"

    def test_anonymize_unicode_chars(self):
        """Test masking unicode characters."""
        strategy = MaskingRetentionStrategy()
        result = strategy.anonymize("héllo")

        assert len(result) == 5

    def test_anonymize_deterministic(self):
        """Test masking is deterministic."""
        strategy = MaskingRetentionStrategy()

        result1 = strategy.anonymize("hello")
        result2 = strategy.anonymize("hello")

        assert result1 == result2


class TestMaskingRetentionRealWorldExamples:
    """Tests with real-world data patterns."""

    def test_email_masking_with_start_preserve(self):
        """Test realistic email masking."""
        config = MaskingRetentionConfig(
            preserve_start_chars=1,
            preserve_delimiters=True,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("john.doe@example.com")

        assert result[0] == "j"  # First char preserved
        assert "@" in result
        assert "." in result

    def test_phone_masking_preserve_last_4(self):
        """Test phone masking preserving last 4 digits."""
        config = MaskingRetentionConfig(
            preserve_end_chars=4,
            preserve_delimiters=True,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("555-123-4567")

        assert result.endswith("4567")
        assert result.count("-") == 2

    def test_credit_card_masking_preserve_last_4(self):
        """Test credit card masking preserving last 4."""
        config = MaskingRetentionConfig(
            preserve_end_chars=4,
            preserve_delimiters=True,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("4111-1111-1111-1111")

        assert result.endswith("1111")
        assert result.count("-") == 3

    def test_ssn_masking_preserve_last_4(self):
        """Test SSN masking preserving last 4."""
        config = MaskingRetentionConfig(
            preserve_end_chars=4,
            preserve_delimiters=True,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("123-45-6789")

        assert result.endswith("6789")
        assert result.count("-") == 2

    def test_name_masking_preserve_first_initial(self):
        """Test name masking preserving first initial."""
        config = MaskingRetentionConfig(
            preserve_start_chars=1,
            preserve_delimiters=True,
        )
        strategy = MaskingRetentionStrategy(config)

        result = strategy.anonymize("John Doe")

        assert result[0] == "J"
        assert " " in result  # Space preserved as delimiter
