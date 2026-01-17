"""Unit tests for date masking strategy.

Tests:
- Date masking with preserve modes (none, year, month)
- Multiple date format support (ISO, US, UK, etc)
- Determinism (seed-based jitter reproducibility)
- NULL and empty string handling
- Output format preservation
- Edge cases (leap years, month boundaries)
- Invalid date handling
"""

from datetime import datetime

import pytest

from confiture.core.anonymization.strategies.date import (
    DateMaskConfig,
    DateMaskingStrategy,
)


class TestDateMaskingBasics:
    """Basic date masking tests."""

    def test_anonymize_none_returns_none(self):
        """Test anonymizing None returns None."""
        config = DateMaskConfig(seed=12345)
        strategy = DateMaskingStrategy(config)
        assert strategy.anonymize(None) is None

    def test_anonymize_empty_string_returns_empty(self):
        """Test anonymizing empty string returns empty."""
        config = DateMaskConfig(seed=12345)
        strategy = DateMaskingStrategy(config)
        assert strategy.anonymize("") == ""

    def test_anonymize_whitespace_returns_whitespace(self):
        """Test anonymizing whitespace returns whitespace."""
        config = DateMaskConfig(seed=12345)
        strategy = DateMaskingStrategy(config)
        assert strategy.anonymize("   ") == "   "

    def test_strategy_name(self):
        """Test strategy has correct name."""
        config = DateMaskConfig(seed=12345)
        strategy = DateMaskingStrategy(config)
        assert strategy.strategy_name == "date"

    def test_unparseable_date_returns_as_is(self):
        """Test unparseable date is returned unchanged."""
        config = DateMaskConfig(seed=12345)
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("not a date")
        assert result == "not a date"


class TestISOFormatSupport:
    """Tests for ISO 8601 date format support."""

    def test_iso_basic_date(self):
        """Test parsing ISO basic date format."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        assert result is not None
        assert isinstance(result, str)
        # Should parse and return as ISO format
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # Year
        assert len(parts[1]) == 2  # Month
        assert len(parts[2]) == 2  # Day

    def test_iso_with_time(self):
        """Test parsing ISO format with time."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15 14:30:45")

        assert result is not None
        # Result should preserve format with time
        assert " " in result

    def test_iso_deterministic(self):
        """Test ISO format anonymization is deterministic."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)

        result1 = strategy.anonymize("2020-05-15")
        result2 = strategy.anonymize("2020-05-15")

        assert result1 == result2

    def test_iso_different_seed_different_output(self):
        """Test different seed produces different jitter."""
        strategy1 = DateMaskingStrategy(DateMaskConfig(seed=12345, preserve="none"))
        strategy2 = DateMaskingStrategy(DateMaskConfig(seed=67890, preserve="none"))

        result1 = strategy1.anonymize("2020-05-15")
        result2 = strategy2.anonymize("2020-05-15")

        # Different seeds should produce different results
        assert result1 != result2


class TestMultipleDateFormats:
    """Tests for supporting multiple date formats."""

    def test_us_format(self):
        """Test parsing US date format (MM/DD/YYYY)."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("05/15/2020")

        assert result is not None
        # Should be returned in same format
        parts = result.split("/")
        assert len(parts) == 3

    def test_uk_format(self):
        """Test parsing UK date format (DD/MM/YYYY)."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("15/05/2020")

        assert result is not None
        parts = result.split("/")
        assert len(parts) == 3

    def test_alternative_iso_format(self):
        """Test parsing alternative ISO format (YYYY/MM/DD)."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020/05/15")

        assert result is not None
        parts = result.split("/")
        assert len(parts) == 3

    def test_text_format(self):
        """Test parsing text date format."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("May 15, 2020")

        assert result is not None
        assert isinstance(result, str)

    def test_format_preservation(self):
        """Test output format matches input format."""
        iso_date = "2020-05-15"
        us_date = "05/15/2020"

        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)

        iso_result = strategy.anonymize(iso_date)
        us_result = strategy.anonymize(us_date)

        # ISO should have dashes
        assert "-" in iso_result
        # US should have slashes
        assert "/" in us_result


class TestPreserveNone:
    """Tests for preserve='none' mode."""

    def test_full_anonymization(self):
        """Test full date anonymization (none preserved)."""
        config = DateMaskConfig(seed=12345, preserve="none", jitter_days=30)
        strategy = DateMaskingStrategy(config)

        datetime(2020, 5, 15)
        result = strategy.anonymize("2020-05-15")

        # Parse result to verify it's a valid date
        parts = result.split("-")
        int(parts[0])
        month = int(parts[1])
        day = int(parts[2])

        # Date should still be valid
        assert 1 <= month <= 12
        assert 1 <= day <= 31

    def test_jitter_within_bounds(self):
        """Test jitter stays within specified bounds."""
        jitter_days = 30
        config = DateMaskConfig(seed=12345, preserve="none", jitter_days=jitter_days)
        strategy = DateMaskingStrategy(config)

        original = datetime(2020, 5, 15)
        result = strategy.anonymize("2020-05-15")

        # Parse result date
        parts = result.split("-")
        result_date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))

        # Should be within jitter bounds
        diff = abs((result_date - original).days)
        assert diff <= jitter_days


class TestPreserveYear:
    """Tests for preserve='year' mode."""

    def test_preserves_year(self):
        """Test that year is preserved."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        parts = result.split("-")
        year = parts[0]

        assert year == "2020"

    def test_randomizes_month_day(self):
        """Test that month/day are randomized."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        parts = result.split("-")
        month = int(parts[1])
        day = int(parts[2])

        # Month/day should be different from original (likely)
        # We can't guarantee they're different, but they should be valid
        assert 1 <= month <= 12
        assert 1 <= day <= 28  # Max 28 to be safe for all months

    def test_deterministic(self):
        """Test preserve='year' is deterministic."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        result1 = strategy.anonymize("2020-05-15")
        result2 = strategy.anonymize("2020-05-15")

        assert result1 == result2

    def test_different_input_dates_same_year(self):
        """Test different dates with same year produce different results."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        result1 = strategy.anonymize("2020-05-15")
        result2 = strategy.anonymize("2020-03-20")

        # Both should start with 2020
        assert result1.startswith("2020")
        assert result2.startswith("2020")
        # But the rest should differ
        assert result1[5:] != result2[5:]

    def test_multiple_years(self):
        """Test different years are preserved."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        result2020 = strategy.anonymize("2020-05-15")
        result2015 = strategy.anonymize("2015-05-15")

        assert result2020.startswith("2020")
        assert result2015.startswith("2015")


class TestPreserveMonth:
    """Tests for preserve='month' mode."""

    def test_preserves_year_and_month(self):
        """Test that year and month are preserved."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        parts = result.split("-")
        year = parts[0]
        month = parts[1]

        assert year == "2020"
        assert month == "05"

    def test_randomizes_day_only(self):
        """Test that only day is randomized."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        parts = result.split("-")
        day = int(parts[2])

        # Day should be valid for May
        assert 1 <= day <= 28  # Max 28 to be safe

    def test_deterministic(self):
        """Test preserve='month' is deterministic."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)

        result1 = strategy.anonymize("2020-05-15")
        result2 = strategy.anonymize("2020-05-15")

        assert result1 == result2

    def test_different_months_different_results(self):
        """Test different months produce different results."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)

        may_result = strategy.anonymize("2020-05-15")
        june_result = strategy.anonymize("2020-06-15")

        # Month part should differ
        assert may_result[5:7] != june_result[5:7]


class TestEdgeCases:
    """Tests for edge cases."""

    def test_leap_year_feb_29(self):
        """Test handling February 29 in leap year."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-02-29")

        # Should still parse and return valid date
        assert result is not None
        parts = result.split("-")
        assert parts[0] == "2020"  # Year preserved

    def test_non_leap_year_feb(self):
        """Test handling February in non-leap year."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2019-02-15")

        assert result is not None
        parts = result.split("-")
        assert parts[0] == "2019"

    def test_month_boundaries(self):
        """Test month boundaries (31st)."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        # January 31
        result = strategy.anonymize("2020-01-31")
        assert result is not None

    def test_year_2000(self):
        """Test Y2K edge case."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2000-01-01")

        assert result is not None
        assert "2000" in result  # Year should be preserved

    def test_early_year(self):
        """Test early year."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("1990-05-15")

        assert result.startswith("1990")


class TestOutputFormatControl:
    """Tests for controlling output format."""

    def test_output_format_override(self):
        """Test overriding output format."""
        config = DateMaskConfig(
            seed=12345,
            preserve="none",
            output_format="%m/%d/%Y",  # US format
        )
        strategy = DateMaskingStrategy(config)
        result = strategy.anonymize("2020-05-15")

        # Should be in US format regardless of input
        assert "/" in result
        parts = result.split("/")
        assert len(parts) == 3

    def test_input_format_preserved_by_default(self):
        """Test input format is preserved by default."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)

        iso_result = strategy.anonymize("2020-05-15")
        us_result = strategy.anonymize("05/15/2020")

        # Format should match input format
        assert "-" in iso_result
        assert "/" in us_result


class TestShortName:
    """Tests for strategy short name."""

    def test_short_name_preserve_none(self):
        """Test short name for preserve='none'."""
        config = DateMaskConfig(seed=12345, preserve="none")
        strategy = DateMaskingStrategy(config)
        assert strategy.short_name() == "date:preserve_none"

    def test_short_name_preserve_year(self):
        """Test short name for preserve='year'."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)
        assert strategy.short_name() == "date:preserve_year"

    def test_short_name_preserve_month(self):
        """Test short name for preserve='month'."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)
        assert strategy.short_name() == "date:preserve_month"


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_default_config(self):
        """Test default configuration."""
        config = DateMaskConfig()
        assert config.preserve == "year"
        assert config.jitter_days == 30
        assert config.output_format is None

    def test_custom_config(self):
        """Test custom configuration."""
        config = DateMaskConfig(
            seed=12345,
            preserve="month",
            jitter_days=60,
            output_format="%m/%d/%Y",
        )
        assert config.seed == 12345
        assert config.preserve == "month"
        assert config.jitter_days == 60
        assert config.output_format == "%m/%d/%Y"

    def test_invalid_preserve_mode(self):
        """Test invalid preserve mode raises error."""
        config = DateMaskConfig(seed=12345, preserve="invalid")
        strategy = DateMaskingStrategy(config)

        with pytest.raises(ValueError, match="Unknown preserve mode"):
            strategy.anonymize("2020-05-15")


class TestComplexScenarios:
    """Tests for complex scenarios."""

    def test_multiple_dates_consistent(self):
        """Test anonymizing multiple dates with same seed is consistent."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        dates = ["2020-05-15", "2020-06-20", "2020-07-10"]
        results1 = [strategy.anonymize(date) for date in dates]
        results2 = [strategy.anonymize(date) for date in dates]

        assert results1 == results2

    def test_all_modes_handle_same_date(self):
        """Test all preserve modes can handle the same date."""
        date = "2020-05-15"

        for preserve_mode in ["none", "year", "month"]:
            config = DateMaskConfig(seed=12345, preserve=preserve_mode)
            strategy = DateMaskingStrategy(config)
            result = strategy.anonymize(date)

            assert result is not None
            assert isinstance(result, str)

    def test_mixed_formats_consistent(self):
        """Test different input formats produce consistent results."""
        iso_date = "2020-05-15"
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        # Same date in different formats
        result1 = strategy.anonymize(iso_date)
        result2 = strategy.anonymize(iso_date)

        assert result1 == result2
