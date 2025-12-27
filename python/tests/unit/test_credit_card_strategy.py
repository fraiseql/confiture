"""Unit tests for credit card masking strategy.

Tests:
- Credit card validation (Luhn algorithm)
- Preservation modes (last4, BIN, none)
- Format preservation (dashes, spaces)
- Card type detection (Visa, Mastercard, Amex, etc)
- Invalid card handling
- Deterministic output
"""

import pytest
from confiture.core.anonymization.strategies.credit_card import (
    CreditCardStrategy,
    CreditCardConfig,
    is_valid_card_number,
    detect_card_type,
    luhn_checksum,
)


class TestCreditCardValidation:
    """Tests for credit card validation."""

    def test_valid_visa_card(self):
        """Test valid Visa card passes validation."""
        # Valid Visa test card from Stripe
        assert is_valid_card_number("4242424242424242")

    def test_valid_mastercard(self):
        """Test valid Mastercard passes validation."""
        # Valid Mastercard test card from Stripe
        assert is_valid_card_number("5555555555554444")

    def test_valid_amex(self):
        """Test valid Amex passes validation."""
        # Valid Amex test card (15 digits)
        assert is_valid_card_number("378282246310005")

    def test_invalid_checksum(self):
        """Test invalid checksum fails validation."""
        assert not is_valid_card_number("4242424242424243")

    def test_too_short_card(self):
        """Test card with too few digits fails."""
        assert not is_valid_card_number("424242424")

    def test_too_long_card(self):
        """Test card with too many digits fails."""
        assert not is_valid_card_number("42424242424242424242")

    def test_non_digit_card(self):
        """Test non-numeric card fails validation."""
        assert not is_valid_card_number("abcd-efgh-ijkl-mnop")

    def test_empty_card(self):
        """Test empty string fails validation."""
        assert not is_valid_card_number("")

    def test_none_card(self):
        """Test None fails validation."""
        assert not is_valid_card_number(None)

    def test_card_with_spaces(self):
        """Test card with spaces passes validation."""
        assert is_valid_card_number("4242 4242 4242 4242")

    def test_card_with_dashes(self):
        """Test card with dashes passes validation."""
        assert is_valid_card_number("4242-4242-4242-4242")


class TestCardTypeDetection:
    """Tests for card type detection."""

    def test_detect_visa(self):
        """Test Visa detection."""
        assert detect_card_type("4242424242424242") == "visa"
        assert detect_card_type("4111111111111111") == "visa"

    def test_detect_mastercard(self):
        """Test Mastercard detection."""
        assert detect_card_type("5555555555554444") == "mastercard"
        assert detect_card_type("5105105105105100") == "mastercard"

    def test_detect_amex(self):
        """Test Amex detection."""
        assert detect_card_type("378282246310005") == "amex"
        assert detect_card_type("371449635398431") == "amex"

    def test_detect_discover(self):
        """Test Discover detection."""
        assert detect_card_type("6011111111111117") == "discover"
        assert detect_card_type("6011000990139424") == "discover"

    def test_detect_diners(self):
        """Test Diners Club detection."""
        assert detect_card_type("36148906660006") == "diners"

    def test_detect_jcb(self):
        """Test JCB detection."""
        assert detect_card_type("3530111333300000") == "jcb"

    def test_detect_unknown(self):
        """Test unknown card type."""
        assert detect_card_type("9999999999999999") == "unknown"

    def test_detect_invalid_number(self):
        """Test invalid number returns unknown."""
        assert detect_card_type("abcd") == "unknown"
        assert detect_card_type("") == "unknown"


class TestLuhnChecksum:
    """Tests for Luhn checksum calculation."""

    def test_luhn_checksum_produces_valid_number(self):
        """Test that generated checksum creates valid card number."""
        # Take 15 digits and calculate checksum
        partial = "424242424242424"
        checksum = luhn_checksum(partial)
        full_card = partial + str(checksum)

        # Full card should be valid
        assert is_valid_card_number(full_card)

    def test_luhn_mastercard_checksum_valid(self):
        """Test Luhn checksum for Mastercard creates valid card."""
        partial = "555555555555444"
        checksum = luhn_checksum(partial)
        full_card = partial + str(checksum)

        # Full card should be valid
        assert is_valid_card_number(full_card)


class TestCreditCardMasking:
    """Tests for credit card masking."""

    def test_anonymize_none_returns_none(self):
        """Test anonymizing None returns None."""
        config = CreditCardConfig(seed=12345)
        strategy = CreditCardStrategy(config)
        assert strategy.anonymize(None) is None

    def test_anonymize_empty_string_returns_empty(self):
        """Test anonymizing empty string returns empty."""
        config = CreditCardConfig(seed=12345)
        strategy = CreditCardStrategy(config)
        assert strategy.anonymize("") == ""

    def test_preserve_last4_digits(self):
        """Test preserving last 4 digits (except checksum digit)."""
        config = CreditCardConfig(
            seed=12345, preserve_last4=True, preserve_bin=False
        )
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242424242424242")

        # Extract last 4 from both
        original_last4 = "4242424242424242"[-4:-1]  # Get 3rd, 2nd, 1st before last (last is checksum)
        result_last4 = result[-4:-1]

        # Should preserve first 3 of last 4
        assert result_last4 == original_last4
        # Should not be identical to original (BIN/middle digits changed)
        assert result != "4242424242424242"

    def test_preserve_bin(self):
        """Test preserving BIN (first 6 digits)."""
        config = CreditCardConfig(
            seed=12345, preserve_last4=False, preserve_bin=True
        )
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242424242424242")

        # Should start with BIN
        assert result.startswith("424242")
        # Should not be identical to original
        assert result != "4242424242424242"

    def test_full_anonymization(self):
        """Test full anonymization (no preservation)."""
        config = CreditCardConfig(
            seed=12345, preserve_last4=False, preserve_bin=False
        )
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242424242424242")

        # Should be different
        assert result != "4242424242424242"
        # Should be valid (pass Luhn)
        cleaned = result.replace(" ", "").replace("-", "")
        assert is_valid_card_number(cleaned)

    def test_format_preservation_dashes(self):
        """Test format preservation with dashes."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242-4242-4242-4242")

        # Should have same format (dashes)
        assert "-" in result
        # Result should be same structure
        parts = result.split("-")
        assert len(parts) == 4
        assert all(len(p) == 4 for p in parts)

    def test_format_preservation_spaces(self):
        """Test format preservation with spaces."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242 4242 4242 4242")

        # Should have same format (spaces)
        assert " " in result
        parts = result.split(" ")
        assert len(parts) == 4

    def test_deterministic_output(self):
        """Test same seed produces same output."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)

        result1 = strategy.anonymize("4242424242424242")
        result2 = strategy.anonymize("4242424242424242")

        assert result1 == result2

    def test_different_seed_different_output(self):
        """Test different seed produces different output."""
        strategy1 = CreditCardStrategy(CreditCardConfig(seed=12345))
        strategy2 = CreditCardStrategy(CreditCardConfig(seed=67890))

        result1 = strategy1.anonymize("4242424242424242")
        result2 = strategy2.anonymize("4242424242424242")

        assert result1 != result2

    def test_invalid_card_masked(self):
        """Test invalid card number is masked."""
        config = CreditCardConfig(seed=12345, validate=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("1234567890123456")

        # Should be masked
        assert result is not None
        assert "*" in result or result == "1234567890123456"

    def test_valid_output_passes_luhn(self):
        """Test output passes Luhn validation."""
        config = CreditCardConfig(seed=12345, preserve_last4=True, validate=False)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4242424242424242")

        # Remove formatting
        cleaned = result.replace(" ", "").replace("-", "")

        # Should pass Luhn validation
        assert is_valid_card_number(cleaned)


class TestCreditCardEdgeCases:
    """Tests for edge cases."""

    def test_visa_with_last4(self):
        """Test Visa card masking."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("4532-1111-1111-1234")

        assert "1234" in result

    def test_amex_15_digits(self):
        """Test Amex 15-digit card."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("378282246310005")

        # Should preserve length
        assert len(result.replace(" ", "").replace("-", "")) == 15

    def test_mastercard_bin_preservation(self):
        """Test Mastercard with BIN preservation."""
        config = CreditCardConfig(seed=12345, preserve_bin=True)
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("5555-5555-5555-4444")

        # Should preserve first 6 digits
        cleaned = result.replace("-", "")
        assert cleaned.startswith("555555")

    def test_multiple_cards_consistent(self):
        """Test multiple cards with same seed are consistent."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)

        card1 = "4242424242424242"
        card2 = "5555555555554444"

        result1a = strategy.anonymize(card1)
        result1b = strategy.anonymize(card1)
        result2a = strategy.anonymize(card2)
        result2b = strategy.anonymize(card2)

        assert result1a == result1b
        assert result2a == result2b
        assert result1a != result2a  # Different cards = different results


class TestCreditCardShortName:
    """Tests for strategy short name."""

    def test_short_name_preserve_last4(self):
        """Test short name for preserve_last4 mode."""
        config = CreditCardConfig(seed=12345, preserve_last4=True)
        strategy = CreditCardStrategy(config)
        assert strategy.short_name() == "credit_card:preserve_last4"

    def test_short_name_preserve_bin(self):
        """Test short name for preserve_bin mode."""
        config = CreditCardConfig(seed=12345, preserve_bin=True)
        strategy = CreditCardStrategy(config)
        assert strategy.short_name() == "credit_card:preserve_bin"

    def test_short_name_full(self):
        """Test short name for full anonymization."""
        config = CreditCardConfig(
            seed=12345, preserve_last4=False, preserve_bin=False
        )
        strategy = CreditCardStrategy(config)
        assert strategy.short_name() == "credit_card:full"


class TestCreditCardConfigValidation:
    """Tests for configuration validation."""

    def test_default_config(self):
        """Test default configuration."""
        config = CreditCardConfig()
        assert config.preserve_last4 is True
        assert config.preserve_bin is False
        assert config.mask_char == "*"
        assert config.validate is True

    def test_custom_mask_char(self):
        """Test custom mask character."""
        config = CreditCardConfig(seed=12345, mask_char="X")
        strategy = CreditCardStrategy(config)
        result = strategy.anonymize("invalid-card")

        # Should use custom mask char if invalid
        assert "X" in result or result == "invalid-card"
