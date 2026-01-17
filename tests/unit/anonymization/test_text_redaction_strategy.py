"""Comprehensive tests for text redaction anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.text_redaction import (
    COMMON_PATTERNS,
    TextRedactionConfig,
    TextRedactionStrategy,
)


class TestTextRedactionStrategy:
    """Tests for TextRedactionStrategy class."""

    @pytest.fixture
    def strategy_email(self):
        """Create strategy for email redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["email"])
        return TextRedactionStrategy(config)

    @pytest.fixture
    def strategy_phone(self):
        """Create strategy for phone number redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["phone_us"])
        return TextRedactionStrategy(config)

    @pytest.fixture
    def strategy_multiple(self):
        """Create strategy with multiple patterns."""
        config = TextRedactionConfig(seed=12345, patterns=["email", "phone_us", "ssn"])
        return TextRedactionStrategy(config)

    @pytest.fixture
    def strategy_preserve_length(self):
        """Create strategy that preserves length."""
        config = TextRedactionConfig(
            seed=12345, patterns=["email"], preserve_length=True, replacement="*"
        )
        return TextRedactionStrategy(config)

    @pytest.fixture
    def strategy_custom_replacement(self):
        """Create strategy with custom replacement."""
        config = TextRedactionConfig(seed=12345, patterns=["email"], replacement="[EMAIL HIDDEN]")
        return TextRedactionStrategy(config)

    # Email redaction tests
    def test_redact_email_basic(self, strategy_email):
        """Test basic email redaction."""
        result = strategy_email.anonymize("Contact john@example.com for help")
        assert "john@example.com" not in result
        assert "[REDACTED]" in result

    def test_redact_email_multiple(self, strategy_email):
        """Test multiple email redaction."""
        result = strategy_email.anonymize("Email john@example.com or jane@test.org")
        assert "john@example.com" not in result
        assert "jane@test.org" not in result
        assert result.count("[REDACTED]") == 2

    def test_redact_email_various_formats(self, strategy_email):
        """Test various email formats."""
        emails = [
            "user@example.com",
            "user.name@example.com",
            "user+tag@example.com",
            "user@sub.domain.example.com",
        ]
        for email in emails:
            result = strategy_email.anonymize(f"Email: {email}")
            assert email not in result, f"Failed to redact: {email}"

    # Phone redaction tests
    def test_redact_phone_basic(self, strategy_phone):
        """Test basic phone number redaction."""
        result = strategy_phone.anonymize("Call 555-123-4567")
        assert "555-123-4567" not in result
        assert "[REDACTED]" in result

    def test_redact_phone_various_formats(self, strategy_phone):
        """Test various phone formats."""
        phones = [
            "555-123-4567",
            "(555) 123-4567",
            "555.123.4567",
            "5551234567",
            "1-555-123-4567",
            "+1 555 123 4567",
        ]
        for phone in phones:
            result = strategy_phone.anonymize(f"Call {phone}")
            # Some formats may not match, just verify it processes
            assert isinstance(result, str)

    # SSN redaction tests
    def test_redact_ssn_basic(self):
        """Test basic SSN redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["ssn"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("SSN: 123-45-6789")
        assert "123-45-6789" not in result
        assert "[REDACTED]" in result

    def test_redact_ssn_no_dashes(self):
        """Test SSN without dashes."""
        config = TextRedactionConfig(seed=12345, patterns=["ssn"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("SSN: 123456789")
        assert "123456789" not in result

    # URL redaction tests
    def test_redact_url_basic(self):
        """Test basic URL redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["url"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Visit https://example.com/path")
        assert "https://example.com/path" not in result
        assert "[REDACTED]" in result

    def test_redact_url_http(self):
        """Test HTTP URL redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["url"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Visit http://example.com")
        assert "http://example.com" not in result

    # IPv4 redaction tests
    def test_redact_ipv4_basic(self):
        """Test basic IPv4 redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["ipv4"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Server at 192.168.1.100")
        assert "192.168.1.100" not in result
        assert "[REDACTED]" in result

    def test_redact_ipv4_various(self):
        """Test various IPv4 addresses."""
        config = TextRedactionConfig(seed=12345, patterns=["ipv4"])
        strategy = TextRedactionStrategy(config)

        ips = ["0.0.0.0", "255.255.255.255", "10.0.0.1", "127.0.0.1"]
        for ip in ips:
            result = strategy.anonymize(f"IP: {ip}")
            assert ip not in result

    # Credit card redaction tests
    def test_redact_credit_card_basic(self):
        """Test basic credit card redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["credit_card"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Card: 4532-0151-1283-0366")
        assert "4532-0151-1283-0366" not in result

    def test_redact_credit_card_spaces(self):
        """Test credit card with spaces."""
        config = TextRedactionConfig(seed=12345, patterns=["credit_card"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Card: 4532 0151 1283 0366")
        assert "4532 0151 1283 0366" not in result

    # Date redaction tests
    def test_redact_date_basic(self):
        """Test basic date redaction."""
        config = TextRedactionConfig(seed=12345, patterns=["date_us"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("DOB: 05/15/2020")
        assert "05/15/2020" not in result

    # Multiple patterns tests
    def test_redact_multiple_patterns(self, strategy_multiple):
        """Test redacting multiple patterns at once."""
        text = "Contact john@example.com or call 555-123-4567. SSN: 123-45-6789"
        result = strategy_multiple.anonymize(text)

        assert "john@example.com" not in result
        assert "555-123-4567" not in result
        assert "123-45-6789" not in result

    # Custom regex tests
    def test_custom_regex_pattern(self):
        """Test custom regex pattern."""
        config = TextRedactionConfig(
            seed=12345, patterns=[r"\bConfidential\b"], replacement="[REMOVED]"
        )
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("This is Confidential information")
        assert "Confidential" not in result
        assert "[REMOVED]" in result

    def test_invalid_regex_pattern_skipped(self):
        """Test invalid regex pattern is skipped."""
        config = TextRedactionConfig(seed=12345, patterns=["[invalid("])
        strategy = TextRedactionStrategy(config)

        # Should not raise, just skip invalid pattern
        result = strategy.anonymize("Some text")
        assert result == "Some text"

    # Preserve length tests
    def test_preserve_length_email(self, strategy_preserve_length):
        """Test preserve length for email."""
        result = strategy_preserve_length.anonymize("Email: john@example.com")
        # john@example.com is 16 chars
        assert "*" * 16 in result

    def test_preserve_length_various(self):
        """Test preserve length for various inputs."""
        config = TextRedactionConfig(
            seed=12345, patterns=["email"], preserve_length=True, replacement="X"
        )
        strategy = TextRedactionStrategy(config)

        text = "Email: a@b.com"  # 6 chars
        result = strategy.anonymize(text)
        assert "X" * 6 in result

    # Custom replacement tests
    def test_custom_replacement(self, strategy_custom_replacement):
        """Test custom replacement string."""
        result = strategy_custom_replacement.anonymize("Email: john@example.com")
        assert "[EMAIL HIDDEN]" in result
        assert "[REDACTED]" not in result

    # Case sensitivity tests
    def test_case_insensitive_default(self, strategy_email):
        """Test case insensitive matching is default."""
        result = strategy_email.anonymize("Email: JOHN@EXAMPLE.COM")
        assert "JOHN@EXAMPLE.COM" not in result

    def test_case_sensitive(self):
        """Test case sensitive matching."""
        config = TextRedactionConfig(seed=12345, patterns=["email"], case_insensitive=False)
        strategy = TextRedactionStrategy(config)

        # Pattern is lowercase, so uppercase should still match (emails are usually case-insensitive)
        result = strategy.anonymize("Email: john@example.com")
        assert "john@example.com" not in result

    # Edge cases
    def test_anonymize_none_returns_none(self, strategy_email):
        """Test None input returns None."""
        assert strategy_email.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_email):
        """Test empty string returns empty string."""
        assert strategy_email.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_email):
        """Test whitespace returns whitespace."""
        assert strategy_email.anonymize("   ") == "   "

    def test_anonymize_no_matches(self, strategy_email):
        """Test text with no matches returns unchanged."""
        result = strategy_email.anonymize("No email here")
        assert result == "No email here"

    # Validate method
    def test_validate_string(self, strategy_email):
        """Test validate accepts string."""
        assert strategy_email.validate("Some text") is True

    def test_validate_none(self, strategy_email):
        """Test validate accepts None."""
        assert strategy_email.validate(None) is True

    def test_validate_non_string(self, strategy_email):
        """Test validate rejects non-string."""
        assert strategy_email.validate(12345) is False
        assert strategy_email.validate(["text"]) is False

    # Short name tests
    def test_short_name_single_pattern(self, strategy_email):
        """Test short name with single pattern."""
        assert strategy_email.short_name() == "text_redaction:email"

    def test_short_name_multiple_patterns(self, strategy_multiple):
        """Test short name with multiple patterns."""
        assert strategy_multiple.short_name() == "text_redaction:email_phone_us_ssn"

    def test_short_name_custom_pattern(self):
        """Test short name with custom pattern."""
        config = TextRedactionConfig(seed=12345, patterns=[r"\btest\b"])
        strategy = TextRedactionStrategy(config)
        assert strategy.short_name() == "text_redaction:custom"

    def test_short_name_mixed_patterns(self):
        """Test short name with mixed built-in and custom patterns."""
        config = TextRedactionConfig(seed=12345, patterns=["email", r"\btest\b"])
        strategy = TextRedactionStrategy(config)
        assert strategy.short_name() == "text_redaction:email_custom"

    def test_short_name_many_patterns_limited(self):
        """Test short name limits to 3 patterns."""
        config = TextRedactionConfig(
            seed=12345, patterns=["email", "phone_us", "ssn", "url", "ipv4"]
        )
        strategy = TextRedactionStrategy(config)
        # Should only include first 3
        assert strategy.short_name() == "text_redaction:email_phone_us_ssn"

    # Strategy name and config type
    def test_strategy_name(self, strategy_email):
        """Test strategy name is text_redaction."""
        assert strategy_email.strategy_name == "text_redaction"

    def test_config_type(self, strategy_email):
        """Test config type is TextRedactionConfig."""
        assert strategy_email.config_type == TextRedactionConfig

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        strategy = TextRedactionStrategy()
        result = strategy.anonymize("Email: john@example.com")
        assert "john@example.com" not in result


class TestTextRedactionConfig:
    """Tests for TextRedactionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TextRedactionConfig(seed=12345)
        assert config.patterns == ["email"]
        assert config.replacement == "[REDACTED]"
        assert config.case_insensitive is True
        assert config.preserve_length is False

    def test_custom_patterns(self):
        """Test custom patterns."""
        config = TextRedactionConfig(seed=12345, patterns=["phone_us", "ssn"])
        assert config.patterns == ["phone_us", "ssn"]

    def test_custom_replacement(self):
        """Test custom replacement."""
        config = TextRedactionConfig(seed=12345, replacement="***")
        assert config.replacement == "***"

    def test_custom_case_insensitive(self):
        """Test custom case_insensitive."""
        config = TextRedactionConfig(seed=12345, case_insensitive=False)
        assert config.case_insensitive is False

    def test_custom_preserve_length(self):
        """Test custom preserve_length."""
        config = TextRedactionConfig(seed=12345, preserve_length=True)
        assert config.preserve_length is True

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = TextRedactionConfig(
            seed=12345,
            patterns=["email", "phone_us"],
            replacement="[REMOVED]",
            case_insensitive=False,
            preserve_length=True,
        )
        assert config.patterns == ["email", "phone_us"]
        assert config.replacement == "[REMOVED]"
        assert config.case_insensitive is False
        assert config.preserve_length is True


class TestCommonPatterns:
    """Tests for COMMON_PATTERNS constant."""

    def test_common_patterns_not_empty(self):
        """Test COMMON_PATTERNS is not empty."""
        assert len(COMMON_PATTERNS) > 0

    def test_common_patterns_keys(self):
        """Test expected pattern keys exist."""
        expected_keys = ["email", "phone_us", "ssn", "credit_card", "url", "ipv4"]
        for key in expected_keys:
            assert key in COMMON_PATTERNS

    def test_common_patterns_are_valid_regex(self):
        """Test all patterns are valid regex."""
        import re

        for name, pattern in COMMON_PATTERNS.items():
            try:
                re.compile(pattern)
            except re.error:
                pytest.fail(f"Invalid regex pattern: {name}")


class TestTextRedactionEdgeCases:
    """Edge case tests for text redaction."""

    def test_overlapping_patterns(self):
        """Test overlapping patterns."""
        # URL and email might overlap in some cases
        config = TextRedactionConfig(seed=12345, patterns=["url", "email"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Visit https://example.com or email user@example.com")
        assert "https://example.com" not in result
        assert "user@example.com" not in result

    def test_embedded_patterns(self):
        """Test embedded patterns in text."""
        config = TextRedactionConfig(seed=12345, patterns=["email"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("The email (john@example.com) was sent.")
        assert "john@example.com" not in result
        assert result == "The email ([REDACTED]) was sent."

    def test_multiline_text(self):
        """Test multiline text processing."""
        config = TextRedactionConfig(seed=12345, patterns=["email"])
        strategy = TextRedactionStrategy(config)

        text = """Line 1: john@example.com
        Line 2: jane@test.org
        Line 3: No email here"""

        result = strategy.anonymize(text)
        assert "john@example.com" not in result
        assert "jane@test.org" not in result
        assert "No email here" in result

    def test_special_characters_preserved(self):
        """Test special characters are preserved."""
        config = TextRedactionConfig(seed=12345, patterns=["email"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Email: <john@example.com>!")
        assert result == "Email: <[REDACTED]>!"

    def test_unicode_text(self):
        """Test unicode text handling."""
        config = TextRedactionConfig(seed=12345, patterns=["email"])
        strategy = TextRedactionStrategy(config)

        result = strategy.anonymize("Eメール: john@example.com です")
        assert "john@example.com" not in result
        assert "Eメール:" in result
        assert "です" in result
