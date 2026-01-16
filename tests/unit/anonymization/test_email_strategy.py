"""Comprehensive tests for email masking anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.email import (
    EmailMaskConfig,
    EmailMaskingStrategy,
)


class TestEmailMaskingStrategy:
    """Tests for EmailMaskingStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = EmailMaskConfig(seed=12345)
        return EmailMaskingStrategy(config)

    @pytest.fixture
    def strategy_preserve_domain(self):
        """Create strategy that preserves domain."""
        config = EmailMaskConfig(seed=12345, preserve_domain=True)
        return EmailMaskingStrategy(config)

    @pytest.fixture
    def strategy_custom_format(self):
        """Create strategy with custom format."""
        config = EmailMaskConfig(
            seed=12345, format="anon_{hash}@test.org", hash_length=6
        )
        return EmailMaskingStrategy(config)

    @pytest.fixture
    def strategy_long_hash(self):
        """Create strategy with longer hash."""
        config = EmailMaskConfig(seed=12345, hash_length=16)
        return EmailMaskingStrategy(config)

    # Basic anonymization tests
    def test_anonymize_basic_email(self, strategy_default):
        """Test basic email anonymization."""
        result = strategy_default.anonymize("john@example.com")
        assert result != "john@example.com"
        assert "@example.com" in result
        assert result.startswith("user_")

    def test_anonymize_deterministic(self, strategy_default):
        """Test same input gives same output."""
        email = "john@example.com"
        result1 = strategy_default.anonymize(email)
        result2 = strategy_default.anonymize(email)
        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = EmailMaskConfig(seed=12345)
        config2 = EmailMaskConfig(seed=67890)
        strategy1 = EmailMaskingStrategy(config1)
        strategy2 = EmailMaskingStrategy(config2)

        email = "john@example.com"
        result1 = strategy1.anonymize(email)
        result2 = strategy2.anonymize(email)
        assert result1 != result2

    def test_anonymize_different_emails_different_outputs(self, strategy_default):
        """Test different emails produce different outputs."""
        result1 = strategy_default.anonymize("john@example.com")
        result2 = strategy_default.anonymize("jane@example.com")
        assert result1 != result2

    # Preserve domain tests
    def test_preserve_domain(self, strategy_preserve_domain):
        """Test domain is preserved when configured."""
        result = strategy_preserve_domain.anonymize("john@mycompany.com")
        assert "@mycompany.com" in result

    def test_preserve_domain_with_subdomain(self, strategy_preserve_domain):
        """Test subdomain is preserved."""
        result = strategy_preserve_domain.anonymize("john@mail.mycompany.com")
        assert "@mail.mycompany.com" in result

    def test_preserve_domain_invalid_email(self, strategy_preserve_domain):
        """Test invalid email uses example.com when preserving domain."""
        result = strategy_preserve_domain.anonymize("notanemail")
        assert "@example.com" in result

    # Custom format tests
    def test_custom_format(self, strategy_custom_format):
        """Test custom format is applied."""
        result = strategy_custom_format.anonymize("john@example.com")
        assert result.startswith("anon_")
        assert "@test.org" in result

    def test_custom_hash_length(self, strategy_custom_format):
        """Test custom hash length."""
        result = strategy_custom_format.anonymize("john@example.com")
        # Format is anon_{hash}@test.org, hash is 6 chars
        hash_part = result.split("_")[1].split("@")[0]
        assert len(hash_part) == 6

    def test_long_hash(self, strategy_long_hash):
        """Test longer hash length."""
        result = strategy_long_hash.anonymize("john@example.com")
        hash_part = result.split("_")[1].split("@")[0]
        assert len(hash_part) == 16

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

    def test_anonymize_non_email_string(self, strategy_default):
        """Test non-email string is still processed."""
        result = strategy_default.anonymize("notanemail")
        # Should still produce output with format
        assert "@example.com" in result

    # Various email formats
    def test_anonymize_email_with_plus(self, strategy_default):
        """Test email with plus addressing."""
        result = strategy_default.anonymize("john+test@example.com")
        assert "@example.com" in result

    def test_anonymize_email_with_dots(self, strategy_default):
        """Test email with dots in local part."""
        result = strategy_default.anonymize("john.doe@example.com")
        assert "@example.com" in result

    def test_anonymize_email_with_numbers(self, strategy_default):
        """Test email with numbers."""
        result = strategy_default.anonymize("john123@example.com")
        assert "@example.com" in result

    # Validate method tests
    def test_validate_valid_email(self, strategy_default):
        """Test validate accepts valid email."""
        assert strategy_default.validate("john@example.com") is True

    def test_validate_email_with_subdomain(self, strategy_default):
        """Test validate accepts email with subdomain."""
        assert strategy_default.validate("john@mail.example.com") is True

    def test_validate_none(self, strategy_default):
        """Test validate rejects None."""
        assert strategy_default.validate(None) is False

    def test_validate_empty_string(self, strategy_default):
        """Test validate rejects empty string."""
        assert strategy_default.validate("") is False

    def test_validate_no_at_symbol(self, strategy_default):
        """Test validate rejects string without @."""
        assert strategy_default.validate("notanemail") is False

    def test_validate_no_domain(self, strategy_default):
        """Test validate rejects email without domain."""
        assert strategy_default.validate("john@") is False

    def test_validate_no_local_part(self, strategy_default):
        """Test validate rejects email without local part."""
        assert strategy_default.validate("@example.com") is False

    def test_validate_no_tld(self, strategy_default):
        """Test validate rejects email without TLD."""
        assert strategy_default.validate("john@example") is False

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        strategy = EmailMaskingStrategy()
        result = strategy.anonymize("john@example.com")
        assert "@example.com" in result


class TestEmailMaskConfig:
    """Tests for EmailMaskConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = EmailMaskConfig(seed=12345)
        assert config.format == "user_{hash}@example.com"
        assert config.hash_length == 8
        assert config.preserve_domain is False

    def test_custom_format(self):
        """Test custom format."""
        config = EmailMaskConfig(seed=12345, format="anon_{hash}@test.org")
        assert config.format == "anon_{hash}@test.org"

    def test_custom_hash_length(self):
        """Test custom hash_length."""
        config = EmailMaskConfig(seed=12345, hash_length=12)
        assert config.hash_length == 12

    def test_custom_preserve_domain(self):
        """Test custom preserve_domain."""
        config = EmailMaskConfig(seed=12345, preserve_domain=True)
        assert config.preserve_domain is True

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = EmailMaskConfig(
            seed=12345,
            format="masked_{hash}@anonymous.org",
            hash_length=10,
            preserve_domain=True,
        )
        assert config.format == "masked_{hash}@anonymous.org"
        assert config.hash_length == 10
        assert config.preserve_domain is True


class TestEmailEdgeCases:
    """Edge case tests for email anonymization."""

    def test_unicode_email(self):
        """Test email with unicode characters."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        # International email
        result = strategy.anonymize("用户@example.com")
        assert "@example.com" in result

    def test_very_long_email(self):
        """Test very long email address."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        long_local = "a" * 100
        result = strategy.anonymize(f"{long_local}@example.com")
        assert "@example.com" in result

    def test_email_regex_pattern(self):
        """Test EMAIL_REGEX pattern exists."""
        assert EmailMaskingStrategy.EMAIL_REGEX is not None
        assert EmailMaskingStrategy.EMAIL_REGEX.match("test@example.com")

    def test_hash_consistency(self):
        """Test hash is consistent for same input."""
        config = EmailMaskConfig(seed=12345, hash_length=8)
        strategy = EmailMaskingStrategy(config)

        # Same email should always produce same hash
        results = [strategy.anonymize("john@example.com") for _ in range(5)]
        assert len(set(results)) == 1  # All results should be identical

    def test_numeric_value_converted(self):
        """Test numeric value is converted to string."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        # Should handle non-string input
        result = strategy.anonymize(12345)
        assert "@example.com" in result
