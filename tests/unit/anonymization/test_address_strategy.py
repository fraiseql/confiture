"""Comprehensive tests for address anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.address import (
    AddressConfig,
    AddressStrategy,
    SAMPLE_CITIES,
    SAMPLE_STREETS,
    STREET_TYPES,
    US_STATES,
)


class TestAddressStrategy:
    """Tests for AddressStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = AddressConfig(seed=12345)
        return AddressStrategy(config)

    @pytest.fixture
    def strategy_preserve_all(self):
        """Create strategy preserving all fields."""
        config = AddressConfig(
            seed=12345,
            preserve_fields=["city", "state", "zip", "country"],
            redact_street=True,
        )
        return AddressStrategy(config)

    @pytest.fixture
    def strategy_preserve_none(self):
        """Create strategy preserving no fields."""
        config = AddressConfig(
            seed=12345,
            preserve_fields=[],
            redact_street=True,
        )
        return AddressStrategy(config)

    # Basic anonymization tests
    def test_anonymize_basic_address(self, strategy_default):
        """Test basic address anonymization."""
        result = strategy_default.anonymize("123 Main St, Springfield, IL 62701")
        assert result != "123 Main St, Springfield, IL 62701"
        assert isinstance(result, str)

    def test_anonymize_none_returns_none(self, strategy_default):
        """Test None input returns None."""
        assert strategy_default.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_default):
        """Test empty string returns empty string."""
        assert strategy_default.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_default):
        """Test whitespace returns whitespace."""
        assert strategy_default.anonymize("   ") == "   "

    def test_anonymize_deterministic(self, strategy_default):
        """Test same input gives same output."""
        address = "123 Main St, Springfield, IL 62701"
        result1 = strategy_default.anonymize(address)
        result2 = strategy_default.anonymize(address)
        assert result1 == result2

    def test_anonymize_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = AddressConfig(seed=12345, preserve_fields=[])
        config2 = AddressConfig(seed=67890, preserve_fields=[])
        strategy1 = AddressStrategy(config1)
        strategy2 = AddressStrategy(config2)

        address = "123 Main St, Springfield, IL 62701"
        result1 = strategy1.anonymize(address)
        result2 = strategy2.anonymize(address)
        assert result1 != result2

    # Preserve fields tests
    def test_preserve_city(self):
        """Test preserving city field."""
        config = AddressConfig(seed=12345, preserve_fields=["city"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")
        assert "Springfield" in result

    def test_preserve_state(self):
        """Test preserving state field."""
        config = AddressConfig(seed=12345, preserve_fields=["state"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")
        assert "IL" in result

    def test_preserve_zip(self):
        """Test preserving zip field."""
        config = AddressConfig(seed=12345, preserve_fields=["zip"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")
        assert "62701" in result

    # Structured format tests
    def test_structured_format(self):
        """Test structured address format."""
        config = AddressConfig(seed=12345, format="structured", preserve_fields=["city"])
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }
        result = strategy.anonymize(address)

        assert isinstance(result, dict)
        assert result["city"] == "Springfield"  # Preserved
        assert result["street"] != "123 Main St"  # Anonymized

    def test_structured_format_none_field(self):
        """Test structured format with None field."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {"street": "123 Main St", "city": None}
        result = strategy.anonymize(address)
        assert result["city"] is None

    def test_structured_format_postal_code(self):
        """Test structured format with postal_code field."""
        config = AddressConfig(seed=12345, format="structured", preserve_fields=[])
        strategy = AddressStrategy(config)

        address = {"postal_code": "62701"}
        result = strategy.anonymize(address)
        assert result["postal_code"] != "62701"

    # Invalid format test
    def test_invalid_format_raises_error(self):
        """Test invalid format raises ValueError."""
        config = AddressConfig(seed=12345, format="invalid")
        strategy = AddressStrategy(config)

        with pytest.raises(ValueError, match="Unknown format"):
            strategy.anonymize("123 Main St")

    # Simple address (cannot parse)
    def test_simple_address_cannot_parse(self, strategy_default):
        """Test address that cannot be parsed."""
        result = strategy_default.anonymize("Some Random Address")
        assert result != "Some Random Address"
        assert isinstance(result, str)

    # Validate method
    def test_validate_string(self, strategy_default):
        """Test validate accepts string."""
        assert strategy_default.validate("123 Main St") is True

    def test_validate_dict(self, strategy_default):
        """Test validate accepts dict."""
        assert strategy_default.validate({"street": "123 Main"}) is True

    def test_validate_none(self, strategy_default):
        """Test validate accepts None."""
        assert strategy_default.validate(None) is True

    def test_validate_non_string_or_dict(self, strategy_default):
        """Test validate rejects other types."""
        assert strategy_default.validate(12345) is False

    # Short name
    def test_short_name_with_preserved_fields(self):
        """Test short name includes preserved fields."""
        config = AddressConfig(seed=12345, preserve_fields=["city", "state"])
        strategy = AddressStrategy(config)
        assert strategy.short_name() == "address:city_state"

    def test_short_name_no_preserved_fields(self):
        """Test short name when no fields preserved."""
        config = AddressConfig(seed=12345, preserve_fields=[])
        strategy = AddressStrategy(config)
        assert strategy.short_name() == "address:none"


class TestAddressConfig:
    """Tests for AddressConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AddressConfig(seed=12345)
        assert config.preserve_fields == ["city", "country"]
        assert config.redact_street is True
        assert config.format == "freetext"

    def test_custom_preserve_fields(self):
        """Test custom preserve fields."""
        config = AddressConfig(seed=12345, preserve_fields=["state", "zip"])
        assert config.preserve_fields == ["state", "zip"]


class TestAddressConstants:
    """Tests for address constants."""

    def test_sample_streets_not_empty(self):
        """Test SAMPLE_STREETS is not empty."""
        assert len(SAMPLE_STREETS) > 0

    def test_street_types_not_empty(self):
        """Test STREET_TYPES is not empty."""
        assert len(STREET_TYPES) > 0

    def test_sample_cities_not_empty(self):
        """Test SAMPLE_CITIES is not empty."""
        assert len(SAMPLE_CITIES) > 0

    def test_us_states_count(self):
        """Test US_STATES has 50 states."""
        assert len(US_STATES) == 50
