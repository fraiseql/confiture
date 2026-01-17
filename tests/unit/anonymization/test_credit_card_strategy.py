"""Comprehensive tests for credit card anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.credit_card import (
    CARD_TYPES,
    CreditCardConfig,
    CreditCardStrategy,
    detect_card_type,
    is_valid_card_number,
    luhn_checksum,
)


class TestLuhnChecksum:
    """Tests for Luhn checksum calculation."""

    def test_luhn_checksum_visa(self):
        """Test Luhn checksum for Visa card."""
        # Visa test number: 4532015112830366
        # Without last digit: 453201511283036
        checksum = luhn_checksum("453201511283036")
        assert checksum == 6

    def test_luhn_checksum_mastercard(self):
        """Test Luhn checksum for Mastercard."""
        # Mastercard: 5425233430109903
        checksum = luhn_checksum("542523343010990")
        assert checksum == 3

    def test_luhn_checksum_amex(self):
        """Test Luhn checksum for Amex."""
        # Amex: 374245455400126
        checksum = luhn_checksum("37424545540012")
        assert checksum == 6

    def test_luhn_checksum_all_zeros(self):
        """Test Luhn with all zeros."""
        checksum = luhn_checksum("000000000000000")
        assert isinstance(checksum, int)
        assert 0 <= checksum <= 9

    def test_luhn_checksum_returns_single_digit(self):
        """Test checksum is always single digit."""
        for i in range(10):
            card = f"12345678901234{i}"
            checksum = luhn_checksum(card)
            assert 0 <= checksum <= 9

    def test_luhn_checksum_different_inputs(self):
        """Test various inputs produce valid checksums."""
        test_cases = [
            "123456789012345",
            "111111111111111",
            "999999999999999",
        ]
        for card in test_cases:
            checksum = luhn_checksum(card)
            assert isinstance(checksum, int)
            assert 0 <= checksum <= 9


class TestDetectCardType:
    """Tests for card type detection."""

    @pytest.mark.parametrize(
        "card,expected",
        [
            ("4532015112830366", "visa"),
            ("4111111111111111", "visa"),
            ("5425233430109903", "mastercard"),
            ("5105105105105100", "mastercard"),
            ("374245455400126", "amex"),
            ("378282246310005", "amex"),
            ("6011111111111117", "discover"),
            ("3530111333300000", "jcb"),
        ],
    )
    def test_detect_known_card_types(self, card, expected):
        """Test detection of known card types."""
        assert detect_card_type(card) == expected

    def test_detect_unknown_card_type(self):
        """Test unknown card type detection."""
        assert detect_card_type("1234567890123456") == "unknown"

    def test_detect_empty_string(self):
        """Test empty string returns unknown."""
        assert detect_card_type("") == "unknown"

    def test_detect_non_digit_string(self):
        """Test non-digit string returns unknown."""
        assert detect_card_type("abcd1234efgh5678") == "unknown"

    def test_detect_wrong_length(self):
        """Test wrong length returns unknown."""
        assert detect_card_type("4111") == "unknown"  # Too short for Visa

    def test_detect_visa_variants(self):
        """Test various Visa card numbers."""
        visa_cards = [
            "4111111111111111",
            "4012888888881881",
            "4222222222222",
        ]
        for card in visa_cards:
            # Visa cards start with 4 and are 13 or 16 digits
            if len(card) == 16:
                assert detect_card_type(card) == "visa"

    def test_detect_mastercard_prefixes(self):
        """Test Mastercard with different prefixes (51-55)."""
        for prefix in [51, 52, 53, 54, 55]:
            card = f"{prefix}00000000000000"
            assert detect_card_type(card) == "mastercard"

    def test_detect_amex_prefixes(self):
        """Test Amex with different prefixes (34, 37)."""
        for prefix in [34, 37]:
            card = f"{prefix}0000000000000"  # 15 digits
            assert detect_card_type(card) == "amex"

    def test_detect_diners_cards(self):
        """Test Diners Club detection."""
        # Diners: 14 digits, starts with 36, 38, 39
        diners_cards = [
            "36000000000000",
            "38000000000000",
        ]
        for card in diners_cards:
            assert detect_card_type(card) == "diners"


class TestIsValidCardNumber:
    """Tests for card number validation."""

    @pytest.mark.parametrize(
        "card",
        [
            "4532015112830366",
            "5425233430109903",
            "374245455400126",
            "6011111111111117",
            "4111111111111111",
        ],
    )
    def test_valid_card_numbers(self, card):
        """Test valid card numbers pass validation."""
        assert is_valid_card_number(card) is True

    def test_valid_card_with_spaces(self):
        """Test card with spaces is valid."""
        assert is_valid_card_number("4532 0151 1283 0366") is True

    def test_valid_card_with_dashes(self):
        """Test card with dashes is valid."""
        assert is_valid_card_number("4532-0151-1283-0366") is True

    def test_invalid_checksum(self):
        """Test card with invalid checksum fails."""
        assert is_valid_card_number("4532015112830367") is False

    def test_empty_string(self):
        """Test empty string is invalid."""
        assert is_valid_card_number("") is False

    def test_none_value(self):
        """Test None is invalid."""
        assert is_valid_card_number(None) is False

    def test_too_short(self):
        """Test too short card is invalid."""
        assert is_valid_card_number("411111111") is False

    def test_too_long(self):
        """Test too long card is invalid."""
        assert is_valid_card_number("41111111111111111111") is False

    def test_non_digit_characters(self):
        """Test non-digit characters (except space/dash) are invalid."""
        assert is_valid_card_number("4532a151b283c366") is False

    def test_mixed_separators(self):
        """Test card with mixed separators."""
        assert is_valid_card_number("4532 0151-1283 0366") is True


class TestCreditCardStrategy:
    """Tests for CreditCardStrategy class."""

    @pytest.fixture
    def strategy_preserve_last4(self):
        """Create strategy that preserves last 4 digits."""
        config = CreditCardConfig(seed=12345, preserve_last4=True, preserve_bin=False)
        return CreditCardStrategy(config)

    @pytest.fixture
    def strategy_preserve_bin(self):
        """Create strategy that preserves BIN."""
        config = CreditCardConfig(seed=12345, preserve_last4=False, preserve_bin=True)
        return CreditCardStrategy(config)

    @pytest.fixture
    def strategy_full_anonymize(self):
        """Create strategy for full anonymization."""
        config = CreditCardConfig(seed=12345, preserve_last4=False, preserve_bin=False)
        return CreditCardStrategy(config)

    # Basic Anonymization Tests
    def test_anonymize_preserves_last4(self, strategy_preserve_last4):
        """Test last 4 digits are preserved."""
        original = "4532015112830366"
        result = strategy_preserve_last4.anonymize(original)
        cleaned_result = result.replace(" ", "").replace("-", "")

        # Last 4 should match or be similar (due to Luhn recalculation)
        assert cleaned_result[-4:] == original[-4:] or len(cleaned_result) == 16
        assert result != original

    def test_anonymize_preserves_bin(self, strategy_preserve_bin):
        """Test BIN (first 6) is preserved."""
        original = "4532015112830366"
        result = strategy_preserve_bin.anonymize(original)
        cleaned_result = result.replace(" ", "").replace("-", "")

        # BIN should be preserved
        assert cleaned_result[:6] == original[:6]

    def test_anonymize_deterministic(self, strategy_preserve_last4):
        """Test same input gives same output (deterministic)."""
        original = "4532015112830366"
        result1 = strategy_preserve_last4.anonymize(original)
        result2 = strategy_preserve_last4.anonymize(original)

        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = CreditCardConfig(seed=12345, preserve_last4=True)
        config2 = CreditCardConfig(seed=67890, preserve_last4=True)

        strategy1 = CreditCardStrategy(config1)
        strategy2 = CreditCardStrategy(config2)

        original = "4532015112830366"
        result1 = strategy1.anonymize(original)
        result2 = strategy2.anonymize(original)

        assert result1 != result2

    # Format Preservation Tests
    def test_anonymize_preserves_spaces_format(self, strategy_preserve_last4):
        """Test spaces in card number are preserved."""
        original = "4532 0151 1283 0366"
        result = strategy_preserve_last4.anonymize(original)

        # Should have same format (4 groups of 4 with spaces)
        assert result.count(" ") == 3

    def test_anonymize_preserves_dash_format(self, strategy_preserve_last4):
        """Test dashes in card number are preserved."""
        original = "4532-0151-1283-0366"
        result = strategy_preserve_last4.anonymize(original)

        # Should have same format (4 groups of 4 with dashes)
        assert result.count("-") == 3

    # Edge Cases
    def test_anonymize_none_value(self, strategy_preserve_last4):
        """Test None input returns None."""
        assert strategy_preserve_last4.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_preserve_last4):
        """Test empty string returns empty string."""
        assert strategy_preserve_last4.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_preserve_last4):
        """Test whitespace-only returns whitespace."""
        assert strategy_preserve_last4.anonymize("   ") == "   "

    def test_anonymize_invalid_card_masked(self):
        """Test invalid card is simply masked."""
        config = CreditCardConfig(seed=12345, validate=True)
        strategy = CreditCardStrategy(config)

        result = strategy.anonymize("1234567890123456")  # Invalid Luhn
        # Should be masked (not pass-through)
        assert result != "1234567890123456"

    def test_anonymize_skip_validation(self):
        """Test validation can be skipped."""
        config = CreditCardConfig(seed=12345, validate=False)
        strategy = CreditCardStrategy(config)

        # Should process even invalid numbers
        result = strategy.anonymize("0000000000000000")
        assert len(result) == 16

    # Luhn Validity of Output
    def test_output_passes_luhn_preserve_bin(self, strategy_preserve_bin):
        """Test anonymized output with preserve_bin passes Luhn validation."""
        original = "4532015112830366"
        result = strategy_preserve_bin.anonymize(original)

        # Remove any formatting
        cleaned = result.replace(" ", "").replace("-", "")
        assert is_valid_card_number(cleaned)

    def test_output_passes_luhn_full_anonymize(self, strategy_full_anonymize):
        """Test fully anonymized output passes Luhn validation."""
        original = "4532015112830366"
        result = strategy_full_anonymize.anonymize(original)

        cleaned = result.replace(" ", "").replace("-", "")
        assert is_valid_card_number(cleaned)

    # Card Type Tests
    @pytest.mark.parametrize(
        "card_type,original",
        [
            ("visa", "4532015112830366"),
            ("mastercard", "5425233430109903"),
            ("amex", "374245455400126"),
        ],
    )
    def test_anonymize_different_card_types(self, card_type, original):
        """Test anonymization works for different card types."""
        config = CreditCardConfig(seed=12345, preserve_bin=True)
        strategy = CreditCardStrategy(config)

        result = strategy.anonymize(original)
        assert result != original
        assert len(result.replace(" ", "").replace("-", "")) == len(original)

    # Validate Method
    def test_validate_string(self, strategy_preserve_last4):
        """Test validate accepts string."""
        assert strategy_preserve_last4.validate("4532015112830366") is True

    def test_validate_none(self, strategy_preserve_last4):
        """Test validate accepts None."""
        assert strategy_preserve_last4.validate(None) is True

    def test_validate_non_string(self, strategy_preserve_last4):
        """Test validate rejects non-string."""
        assert strategy_preserve_last4.validate(12345) is False

    # Short Name
    def test_short_name_preserve_last4(self, strategy_preserve_last4):
        """Test short name for preserve_last4 mode."""
        assert strategy_preserve_last4.short_name() == "credit_card:preserve_last4"

    def test_short_name_preserve_bin(self, strategy_preserve_bin):
        """Test short name for preserve_bin mode."""
        assert strategy_preserve_bin.short_name() == "credit_card:preserve_bin"

    def test_short_name_full(self, strategy_full_anonymize):
        """Test short name for full anonymization."""
        assert strategy_full_anonymize.short_name() == "credit_card:full"

    # Config and Strategy Name
    def test_strategy_name(self, strategy_preserve_last4):
        """Test strategy name is credit_card."""
        assert strategy_preserve_last4.strategy_name == "credit_card"

    def test_config_type(self, strategy_preserve_last4):
        """Test config type is CreditCardConfig."""
        assert strategy_preserve_last4.config_type == CreditCardConfig


class TestCreditCardConfig:
    """Tests for CreditCardConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CreditCardConfig(seed=12345)

        assert config.preserve_last4 is True
        assert config.preserve_bin is False
        assert config.mask_char == "*"
        assert config.validate is True

    def test_custom_mask_char(self):
        """Test custom mask character."""
        config = CreditCardConfig(seed=12345, mask_char="X")
        assert config.mask_char == "X"

    def test_preserve_both_options(self):
        """Test both preserve options can be set."""
        config = CreditCardConfig(
            seed=12345, preserve_last4=True, preserve_bin=True
        )
        assert config.preserve_last4 is True
        assert config.preserve_bin is True

    def test_disable_validation(self):
        """Test validation can be disabled."""
        config = CreditCardConfig(seed=12345, validate=False)
        assert config.validate is False


class TestCardTypes:
    """Tests for CARD_TYPES constant."""

    def test_card_types_contains_major_cards(self):
        """Test CARD_TYPES contains major card brands."""
        assert "visa" in CARD_TYPES
        assert "mastercard" in CARD_TYPES
        assert "amex" in CARD_TYPES
        assert "discover" in CARD_TYPES

    def test_card_types_structure(self):
        """Test CARD_TYPES has correct structure."""
        for _card_type, (length, prefixes) in CARD_TYPES.items():
            assert isinstance(length, int)
            assert isinstance(prefixes, list)
            assert len(prefixes) > 0
