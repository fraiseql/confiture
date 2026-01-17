"""Comprehensive tests for format-preserving encryption (FPE) strategy.

Tests cover:
- FPEConfig configuration
- FormatPreservingEncryptionStrategy initialization
- Format-preserving encryption behavior
- Decrypt functionality
- Validation methods
- Edge cases and error handling
"""

from unittest.mock import Mock

import pytest

from confiture.core.anonymization.strategies.format_preserving_encryption import (
    FormatPreservingEncryptionStrategy,
    FPEConfig,
)


class TestFPEConfig:
    """Tests for FPEConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = FPEConfig()

        assert config.algorithm == "ff3-1"
        assert config.key_id == "fpe-key"
        assert config.tweak == ""
        assert config.preserve_length is True
        assert config.preserve_type is True

    def test_custom_algorithm(self):
        """Test custom algorithm configuration."""
        config = FPEConfig(algorithm="ff1")
        assert config.algorithm == "ff1"

    def test_custom_key_id(self):
        """Test custom key_id configuration."""
        config = FPEConfig(key_id="my-fpe-key-123")
        assert config.key_id == "my-fpe-key-123"

    def test_custom_tweak(self):
        """Test custom tweak configuration."""
        config = FPEConfig(tweak="column-specific-tweak")
        assert config.tweak == "column-specific-tweak"

    def test_preserve_length_disabled(self):
        """Test disabling length preservation."""
        config = FPEConfig(preserve_length=False)
        assert config.preserve_length is False

    def test_preserve_type_disabled(self):
        """Test disabling type preservation."""
        config = FPEConfig(preserve_type=False)
        assert config.preserve_type is False


class TestFormatPreservingEncryptionStrategyInit:
    """Tests for FormatPreservingEncryptionStrategy initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        strategy = FormatPreservingEncryptionStrategy()

        assert strategy.config.algorithm == "ff3-1"
        assert strategy.kms_client is None
        assert strategy.column_name == ""
        assert strategy.is_reversible is True
        assert strategy.requires_kms is True

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = FPEConfig(
            algorithm="ff3-1",
            key_id="custom-key",
            tweak="custom-tweak",
        )
        strategy = FormatPreservingEncryptionStrategy(config)

        assert strategy.config.algorithm == "ff3-1"
        assert strategy.config.key_id == "custom-key"
        assert strategy.config.tweak == "custom-tweak"

    def test_init_with_kms_client(self):
        """Test initialization with KMS client."""
        mock_kms = Mock()
        strategy = FormatPreservingEncryptionStrategy(kms_client=mock_kms)

        assert strategy.kms_client is mock_kms

    def test_init_with_column_name(self):
        """Test initialization with column name."""
        strategy = FormatPreservingEncryptionStrategy(column_name="email")

        assert strategy.column_name == "email"


class TestFormatPreservingEncryptionAnonymize:
    """Tests for FormatPreservingEncryptionStrategy.anonymize() method."""

    @pytest.fixture
    def mock_kms(self):
        """Create mock KMS client."""
        return Mock()

    @pytest.fixture
    def strategy(self, mock_kms):
        """Create strategy with mock KMS."""
        return FormatPreservingEncryptionStrategy(kms_client=mock_kms)

    def test_anonymize_requires_kms_client(self):
        """Test anonymize raises error when no KMS client."""
        strategy = FormatPreservingEncryptionStrategy()  # No KMS

        with pytest.raises(ValueError, match="requires kms_client"):
            strategy.anonymize("john@example.com")

    def test_anonymize_none_returns_none(self, strategy):
        """Test None input returns None."""
        result = strategy.anonymize(None)

        assert result is None

    def test_anonymize_empty_string_returns_empty(self, strategy):
        """Test empty string returns empty string."""
        result = strategy.anonymize("")

        assert result == ""

    def test_anonymize_whitespace_only_returns_empty(self, strategy):
        """Test whitespace-only string returns empty."""
        result = strategy.anonymize("   ")

        assert result == ""

    def test_anonymize_email_preserves_structure(self, strategy):
        """Test email encryption preserves @ and structure."""
        result = strategy.anonymize("john@example.com")

        # Should have same length as original
        assert len(result) == len("john@example.com")
        # Should preserve @ symbol
        assert "@" in result

    def test_anonymize_phone_preserves_format(self, strategy):
        """Test phone number encryption preserves format."""
        result = strategy.anonymize("+1-555-123-4567")

        # Should have same length
        assert len(result) == len("+1-555-123-4567")
        # Should preserve + and -
        assert "+" in result
        assert "-" in result

    def test_anonymize_preserves_length(self, strategy):
        """Test output length equals input length."""
        test_cases = [
            "hello",
            "a" * 100,
            "test123",
            "user@domain.org",
        ]

        for original in test_cases:
            result = strategy.anonymize(original)
            assert len(result) == len(original), f"Length mismatch for '{original}'"

    def test_anonymize_preserves_non_alphanumeric_chars(self, strategy):
        """Test non-alphanumeric characters are preserved."""
        result = strategy.anonymize("test-value_with.dots")

        # Non-alphanumeric chars should be preserved
        assert "-" in result
        assert "_" in result
        assert "." in result

    def test_anonymize_deterministic_with_same_seed(self):
        """Test same seed produces same output."""
        mock_kms = Mock()
        config = FPEConfig(seed=12345)

        strategy1 = FormatPreservingEncryptionStrategy(config, kms_client=mock_kms)
        strategy2 = FormatPreservingEncryptionStrategy(config, kms_client=mock_kms)

        result1 = strategy1.anonymize("test-value")
        result2 = strategy2.anonymize("test-value")

        assert result1 == result2

    def test_anonymize_different_seeds_different_outputs(self):
        """Test different seeds produce different outputs."""
        mock_kms = Mock()
        config1 = FPEConfig(seed=12345)
        config2 = FPEConfig(seed=67890)

        strategy1 = FormatPreservingEncryptionStrategy(config1, kms_client=mock_kms)
        strategy2 = FormatPreservingEncryptionStrategy(config2, kms_client=mock_kms)

        result1 = strategy1.anonymize("test-value")
        result2 = strategy2.anonymize("test-value")

        assert result1 != result2

    def test_anonymize_integer_value(self, strategy):
        """Test integer value is converted to string and encrypted."""
        result = strategy.anonymize(12345)

        assert len(result) == 5  # Same as "12345"

    def test_anonymize_credit_card_preserves_format(self, strategy):
        """Test credit card encryption preserves format."""
        result = strategy.anonymize("4111-1111-1111-1111")

        # Should have same length
        assert len(result) == len("4111-1111-1111-1111")
        # Should preserve dashes
        assert result.count("-") == 3


class TestFormatPreservingEncryptionDecrypt:
    """Tests for FormatPreservingEncryptionStrategy.decrypt() method."""

    @pytest.fixture
    def mock_kms(self):
        """Create mock KMS client."""
        return Mock()

    @pytest.fixture
    def strategy(self, mock_kms):
        """Create strategy with mock KMS."""
        return FormatPreservingEncryptionStrategy(kms_client=mock_kms)

    def test_decrypt_requires_kms_client(self):
        """Test decrypt raises error when no KMS client."""
        strategy = FormatPreservingEncryptionStrategy()  # No KMS

        with pytest.raises(ValueError, match="requires kms_client"):
            strategy.decrypt("encrypted-value")

    def test_decrypt_returns_value(self, strategy):
        """Test decrypt returns a value (placeholder implementation)."""
        result = strategy.decrypt("encrypted-value")

        # Placeholder implementation just returns the input
        assert result == "encrypted-value"


class TestFormatPreservingEncryptionValidation:
    """Tests for validation methods."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for validation tests."""
        return FormatPreservingEncryptionStrategy()

    def test_validate_string(self, strategy):
        """Test validate accepts string."""
        assert strategy.validate("hello") is True

    def test_validate_int(self, strategy):
        """Test validate accepts int (convertible to string)."""
        assert strategy.validate(12345) is True

    def test_validate_float(self, strategy):
        """Test validate accepts float (convertible to string)."""
        assert strategy.validate(123.45) is True

    def test_validate_comprehensive_valid_with_kms(self):
        """Test comprehensive validation with KMS configured."""
        mock_kms = Mock()
        strategy = FormatPreservingEncryptionStrategy(kms_client=mock_kms)

        is_valid, errors = strategy.validate_comprehensive("hello", "name", "users")

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_comprehensive_no_kms_client(self):
        """Test comprehensive validation without KMS client."""
        strategy = FormatPreservingEncryptionStrategy()  # No KMS

        is_valid, errors = strategy.validate_comprehensive("hello", "name", "users")

        assert is_valid is False
        assert len(errors) > 0
        assert "requires kms_client" in errors[0]

    def test_validate_comprehensive_empty_string(self):
        """Test comprehensive validation with empty string."""
        mock_kms = Mock()
        strategy = FormatPreservingEncryptionStrategy(kms_client=mock_kms)

        is_valid, errors = strategy.validate_comprehensive("", "name", "users")

        assert is_valid is False
        assert "Empty string" in errors[0]

    def test_validate_comprehensive_value_too_long(self):
        """Test comprehensive validation with too-long value."""
        mock_kms = Mock()
        strategy = FormatPreservingEncryptionStrategy(kms_client=mock_kms)

        long_value = "x" * 1001  # Over 1000 chars

        is_valid, errors = strategy.validate_comprehensive(long_value, "data", "table")

        assert is_valid is False
        assert "too long" in errors[0]

    def test_validate_comprehensive_with_column_context(self):
        """Test comprehensive validation includes column context."""
        strategy = FormatPreservingEncryptionStrategy()

        is_valid, errors = strategy.validate_comprehensive("test", "email", "users")

        assert "users.email" in errors[0]


class TestFormatPreservingEncryptionProperties:
    """Tests for strategy properties."""

    def test_is_reversible_true(self):
        """Test FPE is reversible."""
        strategy = FormatPreservingEncryptionStrategy()

        assert strategy.is_reversible is True

    def test_requires_kms_true(self):
        """Test FPE requires KMS."""
        strategy = FormatPreservingEncryptionStrategy()

        assert strategy.requires_kms is True


class TestPlaceholderEncrypt:
    """Tests for _placeholder_encrypt method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with mock KMS."""
        mock_kms = Mock()
        return FormatPreservingEncryptionStrategy(kms_client=mock_kms)

    def test_placeholder_encrypt_preserves_length(self, strategy):
        """Test placeholder encryption preserves length."""
        test_cases = [
            "hello",
            "test123",
            "a" * 50,
            "mixed-case_Test",
        ]

        for original in test_cases:
            result = strategy._placeholder_encrypt(original)
            assert len(result) == len(original)

    def test_placeholder_encrypt_preserves_special_chars(self, strategy):
        """Test placeholder encryption preserves special characters."""
        original = "test@example.com"
        result = strategy._placeholder_encrypt(original)

        assert "@" in result
        assert "." in result

    def test_placeholder_encrypt_preserves_dashes(self, strategy):
        """Test placeholder encryption preserves dashes."""
        original = "123-45-6789"
        result = strategy._placeholder_encrypt(original)

        assert result.count("-") == 2

    def test_placeholder_encrypt_preserves_spaces(self, strategy):
        """Test placeholder encryption preserves spaces."""
        original = "hello world test"
        result = strategy._placeholder_encrypt(original)

        assert result.count(" ") == 2

    def test_placeholder_encrypt_deterministic(self, strategy):
        """Test placeholder encryption is deterministic."""
        original = "test-value"

        result1 = strategy._placeholder_encrypt(original)
        result2 = strategy._placeholder_encrypt(original)

        assert result1 == result2


class TestFormatPreservingEncryptionEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with mock KMS."""
        mock_kms = Mock()
        return FormatPreservingEncryptionStrategy(kms_client=mock_kms)

    def test_anonymize_single_char(self, strategy):
        """Test anonymizing single character."""
        result = strategy.anonymize("x")

        assert len(result) == 1

    def test_anonymize_single_digit(self, strategy):
        """Test anonymizing single digit."""
        result = strategy.anonymize("5")

        assert len(result) == 1

    def test_anonymize_all_special_chars(self, strategy):
        """Test anonymizing all special characters."""
        original = "@#$%^&*()"
        result = strategy.anonymize(original)

        # All special chars are preserved in their positions
        assert len(result) == len(original)
        # The result should be all special chars (no alphanumeric conversion)
        for char in result:
            assert not char.isalnum()

    def test_anonymize_unicode_chars(self, strategy):
        """Test anonymizing unicode characters."""
        result = strategy.anonymize("héllo wörld")

        assert len(result) == len("héllo wörld")

    def test_anonymize_mixed_content(self, strategy):
        """Test anonymizing mixed alphanumeric and special content."""
        result = strategy.anonymize("User123-Data_Test.value")

        assert len(result) == len("User123-Data_Test.value")
        assert "-" in result
        assert "_" in result
        assert "." in result

    def test_anonymize_email_domain_preserved(self, strategy):
        """Test email domain structure is preserved."""
        result = strategy.anonymize("user@domain.org")

        # Check structure: something@something.something
        assert "@" in result
        assert "." in result
