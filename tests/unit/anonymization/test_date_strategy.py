"""Comprehensive tests for date masking anonymization strategy."""

from datetime import datetime

import pytest

from confiture.core.anonymization.strategies.date import (
    DateMaskConfig,
    DateMaskingStrategy,
)


class TestDateMaskingStrategy:
    """Tests for DateMaskingStrategy class."""

    @pytest.fixture
    def strategy_preserve_year(self):
        """Create strategy that preserves year."""
        config = DateMaskConfig(seed=12345, preserve="year")
        return DateMaskingStrategy(config)

    @pytest.fixture
    def strategy_preserve_month(self):
        """Create strategy that preserves year and month."""
        config = DateMaskConfig(seed=12345, preserve="month")
        return DateMaskingStrategy(config)

    @pytest.fixture
    def strategy_preserve_none(self):
        """Create strategy that fully anonymizes."""
        config = DateMaskConfig(seed=12345, preserve="none", jitter_days=30)
        return DateMaskingStrategy(config)

    @pytest.fixture
    def strategy_custom_format(self):
        """Create strategy with custom output format."""
        config = DateMaskConfig(seed=12345, preserve="year", output_format="%d/%m/%Y")
        return DateMaskingStrategy(config)

    # Basic ISO 8601 format tests
    def test_anonymize_iso_format(self, strategy_preserve_year):
        """Test ISO 8601 format anonymization."""
        result = strategy_preserve_year.anonymize("2020-05-15")
        assert result != "2020-05-15"
        # Should still be valid ISO format
        datetime.strptime(result, "%Y-%m-%d")

    def test_anonymize_preserves_year(self, strategy_preserve_year):
        """Test year is preserved when configured."""
        result = strategy_preserve_year.anonymize("2020-05-15")
        assert result.startswith("2020-")

    def test_anonymize_preserves_month(self, strategy_preserve_month):
        """Test year and month are preserved when configured."""
        result = strategy_preserve_month.anonymize("2020-05-15")
        assert result.startswith("2020-05-")
        # Day should be different
        assert result != "2020-05-15"

    def test_anonymize_full_anonymization(self, strategy_preserve_none):
        """Test full anonymization changes the date."""
        result = strategy_preserve_none.anonymize("2020-05-15")
        # Date should be different
        assert result != "2020-05-15"

    def test_anonymize_deterministic(self, strategy_preserve_year):
        """Test same input gives same output."""
        date = "2020-05-15"
        result1 = strategy_preserve_year.anonymize(date)
        result2 = strategy_preserve_year.anonymize(date)
        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = DateMaskConfig(seed=12345, preserve="year")
        config2 = DateMaskConfig(seed=67890, preserve="year")
        strategy1 = DateMaskingStrategy(config1)
        strategy2 = DateMaskingStrategy(config2)

        date = "2020-05-15"
        result1 = strategy1.anonymize(date)
        result2 = strategy2.anonymize(date)
        assert result1 != result2

    # Multiple format tests
    def test_anonymize_us_format(self, strategy_preserve_year):
        """Test US format (MM/DD/YYYY)."""
        result = strategy_preserve_year.anonymize("05/15/2020")
        # Should preserve format
        parts = result.split("/")
        assert len(parts) == 3
        assert len(parts[2]) == 4  # Year at end

    def test_anonymize_uk_format(self, strategy_preserve_year):
        """Test UK format (DD/MM/YYYY)."""
        result = strategy_preserve_year.anonymize("15/05/2020")
        parts = result.split("/")
        assert len(parts) == 3

    def test_anonymize_iso_with_time(self, strategy_preserve_year):
        """Test ISO format with time."""
        result = strategy_preserve_year.anonymize("2020-05-15 14:30:00")
        assert ":" in result  # Time preserved
        assert result.startswith("2020-")

    def test_anonymize_us_with_time(self, strategy_preserve_year):
        """Test US format with time."""
        result = strategy_preserve_year.anonymize("05/15/2020 14:30:00")
        assert ":" in result

    def test_anonymize_long_month_name(self, strategy_preserve_year):
        """Test format with full month name."""
        result = strategy_preserve_year.anonymize("May 15, 2020")
        # Format should be preserved
        assert "2020" in result

    def test_anonymize_short_month_name(self, strategy_preserve_year):
        """Test format with short month name."""
        result = strategy_preserve_year.anonymize("May 15, 2020")
        assert "2020" in result

    # Custom output format tests
    def test_custom_output_format(self, strategy_custom_format):
        """Test custom output format."""
        result = strategy_custom_format.anonymize("2020-05-15")
        # Output should be in DD/MM/YYYY format
        parts = result.split("/")
        assert len(parts) == 3
        assert parts[2] == "2020"  # Year preserved and at end

    # Edge cases
    def test_anonymize_none_returns_none(self, strategy_preserve_year):
        """Test None input returns None."""
        assert strategy_preserve_year.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_preserve_year):
        """Test empty string returns empty string."""
        assert strategy_preserve_year.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_preserve_year):
        """Test whitespace returns whitespace."""
        assert strategy_preserve_year.anonymize("   ") == "   "

    def test_anonymize_invalid_date_returns_unchanged(self, strategy_preserve_year):
        """Test invalid date returns unchanged."""
        result = strategy_preserve_year.anonymize("not-a-date")
        assert result == "not-a-date"

    def test_anonymize_invalid_format_returns_unchanged(self, strategy_preserve_year):
        """Test unrecognized format returns unchanged."""
        result = strategy_preserve_year.anonymize("2020.05.15")  # Not supported format
        assert result == "2020.05.15"

    def test_anonymize_unknown_preserve_mode_raises(self):
        """Test unknown preserve mode raises ValueError."""
        config = DateMaskConfig(seed=12345, preserve="invalid")
        strategy = DateMaskingStrategy(config)

        with pytest.raises(ValueError, match="Unknown preserve mode"):
            strategy.anonymize("2020-05-15")

    # Jitter tests
    def test_jitter_within_bounds(self):
        """Test jitter stays within configured bounds."""
        config = DateMaskConfig(seed=12345, preserve="none", jitter_days=7)
        strategy = DateMaskingStrategy(config)

        original = datetime.strptime("2020-05-15", "%Y-%m-%d")
        result_str = strategy.anonymize("2020-05-15")
        result = datetime.strptime(result_str, "%Y-%m-%d")

        # Difference should be within jitter_days
        diff = abs((result - original).days)
        assert diff <= 7

    # Validate method
    def test_validate_string(self, strategy_preserve_year):
        """Test validate accepts string."""
        assert strategy_preserve_year.validate("2020-05-15") is True

    def test_validate_none(self, strategy_preserve_year):
        """Test validate accepts None."""
        assert strategy_preserve_year.validate(None) is True

    def test_validate_non_string(self, strategy_preserve_year):
        """Test validate rejects non-string."""
        assert strategy_preserve_year.validate(12345) is False
        assert strategy_preserve_year.validate(datetime.now()) is False

    # Short name
    def test_short_name_preserve_year(self, strategy_preserve_year):
        """Test short name for preserve year mode."""
        assert strategy_preserve_year.short_name() == "date:preserve_year"

    def test_short_name_preserve_month(self, strategy_preserve_month):
        """Test short name for preserve month mode."""
        assert strategy_preserve_month.short_name() == "date:preserve_month"

    def test_short_name_preserve_none(self, strategy_preserve_none):
        """Test short name for full anonymization mode."""
        assert strategy_preserve_none.short_name() == "date:preserve_none"

    # Strategy name and config type
    def test_strategy_name(self, strategy_preserve_year):
        """Test strategy name is date."""
        assert strategy_preserve_year.strategy_name == "date"

    def test_config_type(self, strategy_preserve_year):
        """Test config type is DateMaskConfig."""
        assert strategy_preserve_year.config_type == DateMaskConfig


class TestDateMaskConfig:
    """Tests for DateMaskConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DateMaskConfig(seed=12345)
        assert config.preserve == "year"
        assert config.jitter_days == 30
        assert config.output_format is None

    def test_custom_preserve(self):
        """Test custom preserve value."""
        config = DateMaskConfig(seed=12345, preserve="month")
        assert config.preserve == "month"

    def test_custom_jitter_days(self):
        """Test custom jitter days."""
        config = DateMaskConfig(seed=12345, jitter_days=90)
        assert config.jitter_days == 90

    def test_custom_output_format(self):
        """Test custom output format."""
        config = DateMaskConfig(seed=12345, output_format="%d/%m/%Y")
        assert config.output_format == "%d/%m/%Y"

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = DateMaskConfig(
            seed=12345,
            preserve="none",
            jitter_days=7,
            output_format="%Y-%m-%d",
        )
        assert config.preserve == "none"
        assert config.jitter_days == 7
        assert config.output_format == "%Y-%m-%d"


class TestDateFormats:
    """Tests for various date formats."""

    @pytest.fixture
    def strategy(self):
        """Create default strategy."""
        config = DateMaskConfig(seed=12345, preserve="year")
        return DateMaskingStrategy(config)

    @pytest.mark.parametrize(
        "date_input,expected_format",
        [
            ("2020-05-15", "%Y-%m-%d"),
            ("05/15/2020", "%m/%d/%Y"),
            ("15/05/2020", "%d/%m/%Y"),
            ("2020/05/15", "%Y/%m/%d"),
            ("15-05-2020", "%d-%m-%Y"),
        ],
    )
    def test_format_detection(self, strategy, date_input, expected_format):
        """Test correct format detection for various inputs."""
        result = strategy.anonymize(date_input)
        # Try to parse result with expected format
        try:
            datetime.strptime(result, expected_format)
            format_preserved = True
        except ValueError:
            format_preserved = False
        assert format_preserved, f"Format not preserved for {date_input}"

    def test_all_date_formats_constant(self, strategy):
        """Test DATE_FORMATS constant exists and is not empty."""
        assert len(strategy.DATE_FORMATS) > 0
        assert all(isinstance(fmt, str) for fmt in strategy.DATE_FORMATS)


class TestDateEdgeCases:
    """Edge case tests for date anonymization."""

    def test_leap_year_date(self):
        """Test handling leap year dates."""
        config = DateMaskConfig(seed=12345, preserve="month")
        strategy = DateMaskingStrategy(config)

        # Feb 29 in leap year
        result = strategy.anonymize("2020-02-29")
        # Result should be valid February date
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.month == 2
        assert parsed.year == 2020

    def test_year_boundary(self):
        """Test dates near year boundaries."""
        config = DateMaskConfig(seed=12345, preserve="none", jitter_days=60)
        strategy = DateMaskingStrategy(config)

        # Date near year end
        result = strategy.anonymize("2020-12-31")
        # Should be valid date
        datetime.strptime(result, "%Y-%m-%d")

    def test_whitespace_around_date(self):
        """Test date with leading/trailing whitespace."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        # Date with whitespace should still parse
        result = strategy.anonymize("  2020-05-15  ")
        assert result != "  2020-05-15  "
        # Should parse as valid date
        datetime.strptime(result, "%Y-%m-%d")

    def test_different_years(self):
        """Test various years."""
        config = DateMaskConfig(seed=12345, preserve="year")
        strategy = DateMaskingStrategy(config)

        years = ["1990", "2000", "2020", "2030"]
        for year in years:
            date = f"{year}-05-15"
            result = strategy.anonymize(date)
            assert result.startswith(f"{year}-")
