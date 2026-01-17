"""Unit tests for email, phone, and redact strategies."""

from confiture.core.anonymization.strategies.email import (
    EmailMaskConfig,
    EmailMaskingStrategy,
)
from confiture.core.anonymization.strategies.phone import (
    PhoneMaskConfig,
    PhoneMaskingStrategy,
)
from confiture.core.anonymization.strategies.redact import (
    RedactConfig,
    SimpleRedactStrategy,
)


class TestEmailMaskingStrategy:
    """Test email masking strategy."""

    def test_deterministic_email_masking(self):
        """Same email + seed = same masked email."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        masked1 = strategy.anonymize("alice@example.com")
        masked2 = strategy.anonymize("alice@example.com")

        assert masked1 == masked2
        assert masked1.endswith("@example.com")

    def test_different_emails_different_masks(self):
        """Different emails produce different masks."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        masked_alice = strategy.anonymize("alice@example.com")
        masked_bob = strategy.anonymize("bob@example.com")

        assert masked_alice != masked_bob

    def test_email_format_preserved(self):
        """Masked email has valid email format."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        masked = strategy.anonymize("user@domain.com")
        assert "@" in masked
        assert "." in masked
        assert masked.count("@") == 1

    def test_null_email_handling(self):
        """NULL emails return NULL."""
        config = EmailMaskConfig()
        strategy = EmailMaskingStrategy(config)

        assert strategy.anonymize(None) is None

    def test_empty_email_handling(self):
        """Empty string returns empty string."""
        config = EmailMaskConfig()
        strategy = EmailMaskingStrategy(config)

        assert strategy.anonymize("") == ""

    def test_custom_format(self):
        """Custom email format is used."""
        config = EmailMaskConfig(seed=12345, format="test_{hash}@custom.org")
        strategy = EmailMaskingStrategy(config)

        masked = strategy.anonymize("user@example.com")
        assert "@custom.org" in masked

    def test_hash_length_configuration(self):
        """Hash length can be configured."""
        config = EmailMaskConfig(seed=12345, hash_length=16)
        strategy = EmailMaskingStrategy(config)

        masked = strategy.anonymize("user@example.com")
        # Extract hash part (between 'user_' and '@')
        start = masked.find("_") + 1
        end = masked.find("@")
        hash_part = masked[start:end]

        assert len(hash_part) == 16

    def test_validate_valid_email(self):
        """Valid email passes validation."""
        config = EmailMaskConfig()
        strategy = EmailMaskingStrategy(config)

        assert strategy.validate("user@example.com") is True
        assert strategy.validate("test.email@domain.co.uk") is True

    def test_validate_invalid_email(self):
        """Invalid email fails validation."""
        config = EmailMaskConfig()
        strategy = EmailMaskingStrategy(config)

        assert strategy.validate("not-an-email") is False
        assert strategy.validate("@example.com") is False
        assert strategy.validate("user@") is False
        assert strategy.validate(None) is False

    def test_unicode_email_handling(self):
        """Unicode in emails is handled."""
        config = EmailMaskConfig(seed=12345)
        strategy = EmailMaskingStrategy(config)

        # Unicode in local part
        masked1 = strategy.anonymize("tëst@example.com")
        assert masked1 is not None

        # Same unicode input = same output
        masked2 = strategy.anonymize("tëst@example.com")
        assert masked1 == masked2


class TestPhoneMaskingStrategy:
    """Test phone number masking strategy."""

    def test_deterministic_phone_masking(self):
        """Same phone + seed = same masked phone."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        masked1 = strategy.anonymize("+1-202-555-0123")
        masked2 = strategy.anonymize("+1-202-555-0123")

        assert masked1 == masked2
        assert "+1-555-" in masked1

    def test_different_phones_different_masks(self):
        """Different phones produce different masks."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        masked1 = strategy.anonymize("+1-202-555-0123")
        masked2 = strategy.anonymize("+1-203-555-0456")

        assert masked1 != masked2

    def test_phone_format_preserved(self):
        """Masked phone has valid phone format."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        masked = strategy.anonymize("555-1234")
        assert "-" in masked or len(masked) > 8  # Has some format

    def test_null_phone_handling(self):
        """NULL phones return NULL."""
        config = PhoneMaskConfig()
        strategy = PhoneMaskingStrategy(config)

        assert strategy.anonymize(None) is None

    def test_empty_phone_handling(self):
        """Empty string returns empty string."""
        config = PhoneMaskConfig()
        strategy = PhoneMaskingStrategy(config)

        assert strategy.anonymize("") == ""

    def test_custom_phone_format(self):
        """Custom phone format is used."""
        config = PhoneMaskConfig(seed=12345, format="(555) {number}")
        strategy = PhoneMaskingStrategy(config)

        masked = strategy.anonymize("202-555-0123")
        assert masked.startswith("(555)")

    def test_validate_valid_phone(self):
        """Valid phone numbers pass validation."""
        config = PhoneMaskConfig()
        strategy = PhoneMaskingStrategy(config)

        assert strategy.validate("+1-202-555-0123") is True
        assert strategy.validate("202-555-0123") is True
        assert strategy.validate("(202) 555-0123") is True

    def test_validate_invalid_phone(self):
        """Invalid phone numbers fail validation."""
        config = PhoneMaskConfig()
        strategy = PhoneMaskingStrategy(config)

        assert strategy.validate("not-a-phone") is False
        assert strategy.validate("123") is False
        assert strategy.validate(None) is False

    def test_various_phone_formats(self):
        """Various phone formats are handled."""
        config = PhoneMaskConfig(seed=12345)
        strategy = PhoneMaskingStrategy(config)

        formats = [
            "+1-202-555-0123",
            "202-555-0123",
            "(202) 555-0123",
            "202.555.0123",
            "+44 20 7946 0958",
        ]

        results = []
        for phone in formats:
            masked = strategy.anonymize(phone)
            assert masked is not None
            results.append(masked)

        # All should be different (different input)
        assert len(set(results)) == len(results)


class TestSimpleRedactStrategy:
    """Test simple redaction strategy."""

    def test_redaction_consistency(self):
        """All values redacted to same text."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        assert strategy.anonymize("secret") == "[REDACTED]"
        assert strategy.anonymize("password") == "[REDACTED]"
        assert strategy.anonymize("12345") == "[REDACTED]"
        assert strategy.anonymize(True) == "[REDACTED]"
        assert strategy.anonymize(3.14) == "[REDACTED]"

    def test_null_not_redacted(self):
        """NULL values are not redacted (special case)."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        assert strategy.anonymize(None) is None

    def test_empty_string_redacted(self):
        """Empty strings are still redacted."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        assert strategy.anonymize("") == "[REDACTED]"

    def test_custom_redaction_text(self):
        """Custom redaction text can be used."""
        config = RedactConfig(replacement="[HIDDEN]")
        strategy = SimpleRedactStrategy(config)

        assert strategy.anonymize("anything") == "[HIDDEN]"
        assert strategy.anonymize("secret") == "[HIDDEN]"

    def test_validate_all_types(self):
        """Redaction validates all types as OK."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        assert strategy.validate("string") is True
        assert strategy.validate(12345) is True
        assert strategy.validate(3.14) is True
        assert strategy.validate(True) is True
        assert strategy.validate([1, 2, 3]) is True
        assert strategy.validate({"key": "value"}) is True

    def test_no_determinism_needed(self):
        """Redaction doesn't need seed for determinism."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        # Even without seed, redaction is "deterministic" (always same output)
        assert strategy.anonymize("value1") == strategy.anonymize("value2")

    def test_unicode_redaction(self):
        """Unicode values are redacted."""
        config = RedactConfig()
        strategy = SimpleRedactStrategy(config)

        assert strategy.anonymize("école") == "[REDACTED]"
        assert strategy.anonymize("北京") == "[REDACTED]"
        assert strategy.anonymize("🎉") == "[REDACTED]"
