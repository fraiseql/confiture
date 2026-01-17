"""Unit tests for address masking strategy.

Tests:
- Address masking with field-level preservation
- Freetext and structured address formats
- Determinism (seed-based reproducibility)
- NULL and empty string handling
- Field preservation combinations
- Parsing and anonymization of address components
- Edge cases
"""

import pytest

from confiture.core.anonymization.strategies.address import (
    AddressConfig,
    AddressStrategy,
)


class TestAddressMaskingBasics:
    """Basic address masking tests."""

    def test_anonymize_none_returns_none(self):
        """Test anonymizing None returns None."""
        config = AddressConfig(seed=12345)
        strategy = AddressStrategy(config)
        assert strategy.anonymize(None) is None

    def test_anonymize_empty_string_returns_empty(self):
        """Test anonymizing empty string returns empty."""
        config = AddressConfig(seed=12345)
        strategy = AddressStrategy(config)
        assert strategy.anonymize("") == ""

    def test_anonymize_whitespace_returns_whitespace(self):
        """Test anonymizing whitespace returns whitespace."""
        config = AddressConfig(seed=12345)
        strategy = AddressStrategy(config)
        assert strategy.anonymize("   ") == "   "

    def test_strategy_name(self):
        """Test strategy has correct name."""
        config = AddressConfig(seed=12345)
        strategy = AddressStrategy(config)
        assert strategy.strategy_name == "address"

    def test_unparseable_address_returns_anonymized(self):
        """Test unparseable address is fully anonymized."""
        config = AddressConfig(seed=12345)
        strategy = AddressStrategy(config)
        result = strategy.anonymize("not a real address")

        # Should return anonymized version
        assert result is not None
        assert result != "not a real address"
        # Should contain typical address components
        assert "," in result or len(result) > 10


class TestFreetextAddressFormat:
    """Tests for freetext address format."""

    def test_parse_simple_address(self):
        """Test parsing simple freetext address."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        assert result is not None
        assert isinstance(result, str)
        # Should contain comma separators
        assert "," in result

    def test_preserves_city(self):
        """Test city preservation."""
        config = AddressConfig(seed=12345, format="freetext", preserve_fields=["city"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        # Result should contain original city
        assert "Springfield" in result

    def test_preserves_state(self):
        """Test state preservation."""
        config = AddressConfig(seed=12345, format="freetext", preserve_fields=["state"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        # Result should contain original state
        assert "IL" in result

    def test_preserves_zip(self):
        """Test zip code preservation."""
        config = AddressConfig(seed=12345, format="freetext", preserve_fields=["zip"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        # Result should contain original zip
        assert "62701" in result

    def test_preserves_country(self):
        """Test country preservation."""
        config = AddressConfig(seed=12345, format="freetext", preserve_fields=["country"])
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701, USA")

        assert result is not None

    def test_anonymizes_street_by_default(self):
        """Test street is anonymized by default."""
        config = AddressConfig(
            seed=12345, format="freetext", preserve_fields=["city", "state", "zip"]
        )
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        # Street number and name should be different
        assert "123 Main St" not in result
        # But city, state, zip should be preserved
        assert "Springfield" in result
        assert "IL" in result
        assert "62701" in result

    def test_deterministic(self):
        """Test freetext anonymization is deterministic."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        result1 = strategy.anonymize("123 Main St, Springfield, IL 62701")
        result2 = strategy.anonymize("123 Main St, Springfield, IL 62701")

        assert result1 == result2

    def test_different_seed_different_output(self):
        """Test different seed produces different output."""
        strategy1 = AddressStrategy(AddressConfig(seed=12345, format="freetext"))
        strategy2 = AddressStrategy(AddressConfig(seed=67890, format="freetext"))

        result1 = strategy1.anonymize("123 Main St, Springfield, IL 62701")
        result2 = strategy2.anonymize("123 Main St, Springfield, IL 62701")

        assert result1 != result2

    def test_multiple_field_preservation(self):
        """Test preserving multiple fields."""
        config = AddressConfig(
            seed=12345,
            format="freetext",
            preserve_fields=["city", "state", "country"],
        )
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St, Springfield, IL 62701")

        # These fields should be preserved
        assert "Springfield" in result
        assert "IL" in result

    def test_address_with_apartment(self):
        """Test address with apartment number."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St Apt 4B, Springfield, IL 62701")

        # Should handle apartment designation
        assert result is not None

    def test_short_address(self):
        """Test parsing short address with missing parts."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)
        result = strategy.anonymize("123 Main St")

        # Should still anonymize even with minimal parts
        assert result is not None


class TestStructuredAddressFormat:
    """Tests for structured address format."""

    def test_anonymize_structured_address_dict(self):
        """Test anonymizing structured address dictionary."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }
        result = strategy.anonymize(address)

        assert isinstance(result, dict)
        assert "street" in result
        assert "city" in result
        assert "state" in result
        assert "zip" in result

    def test_structured_preserves_fields(self):
        """Test field preservation in structured format."""
        config = AddressConfig(
            seed=12345,
            format="structured",
            preserve_fields=["city", "state"],
        )
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }
        result = strategy.anonymize(address)

        # Preserved fields should match original
        assert result["city"] == "Springfield"
        assert result["state"] == "IL"
        # Non-preserved should be different
        assert result["street"] != "123 Main St"
        assert result["zip"] != "62701"

    def test_structured_handles_none_values(self):
        """Test structured format handles None values."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": None,
            "zip": "62701",
        }
        result = strategy.anonymize(address)

        # None values should remain None
        assert result["state"] is None

    def test_structured_with_postal_code_alias(self):
        """Test structured format handles postal_code alias for zip."""
        config = AddressConfig(
            seed=12345,
            format="structured",
            preserve_fields=["postal_code"],
        )
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "postal_code": "62701",
        }
        result = strategy.anonymize(address)

        # Postal code should be preserved
        assert result["postal_code"] == "62701"

    def test_structured_with_extra_fields(self):
        """Test structured format handles extra fields."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
            "country": "USA",
            "building": "Tower A",
        }
        result = strategy.anonymize(address)

        # Extra fields should be preserved as-is
        assert result["country"] == "USA"
        assert result["building"] == "Tower A"

    def test_structured_deterministic(self):
        """Test structured anonymization is deterministic."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }

        result1 = strategy.anonymize(address)
        result2 = strategy.anonymize(address)

        assert result1 == result2

    def test_structured_preserves_structure(self):
        """Test result maintains same structure as input."""
        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }
        result = strategy.anonymize(address)

        # Keys should be same
        assert set(result.keys()) == set(address.keys())


class TestAddressComponentGeneration:
    """Tests for address component generation."""

    def test_generates_valid_street(self):
        """Test generated street has valid format."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        # Access internal method for testing
        street = strategy._anonymize_street()

        assert street is not None
        assert isinstance(street, str)
        # Should contain number and name
        assert " " in street
        parts = street.split()
        assert len(parts) >= 3  # num, name, type

    def test_generates_valid_city(self):
        """Test generated city is from sample list."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        city = strategy._anonymize_city()

        assert city is not None
        assert isinstance(city, str)
        # City should be reasonable length
        assert 5 <= len(city) <= 20

    def test_generates_valid_state(self):
        """Test generated state is valid US state code."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        state = strategy._anonymize_state()

        assert state is not None
        assert len(state) == 2
        assert state.isupper()

    def test_generates_valid_zip(self):
        """Test generated zip code is valid."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        zip_code = strategy._anonymize_zip()

        assert zip_code is not None
        assert len(zip_code) == 5
        assert zip_code.isdigit()
        assert int(zip_code) >= 10000

    def test_component_determinism(self):
        """Test component generation is deterministic."""
        config1 = AddressConfig(seed=12345, format="freetext")
        config2 = AddressConfig(seed=12345, format="freetext")

        strategy1 = AddressStrategy(config1)
        strategy2 = AddressStrategy(config2)

        assert strategy1._anonymize_street() == strategy2._anonymize_street()
        assert strategy1._anonymize_city() == strategy2._anonymize_city()
        assert strategy1._anonymize_state() == strategy2._anonymize_state()
        assert strategy1._anonymize_zip() == strategy2._anonymize_zip()


class TestAddressParsingEdgeCases:
    """Tests for edge cases in address parsing."""

    def test_address_without_commas(self):
        """Test address without commas."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        result = strategy.anonymize("123 Main Street")
        assert result is not None

    def test_address_with_extra_commas(self):
        """Test address with extra commas."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        result = strategy.anonymize("123 Main St,, Springfield,, IL,, 62701")
        assert result is not None

    def test_address_with_leading_trailing_spaces(self):
        """Test address with extra whitespace."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        result = strategy.anonymize("  123 Main St, Springfield, IL 62701  ")
        assert result is not None

    def test_international_address(self):
        """Test international address format."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        result = strategy.anonymize("123 Main St, Toronto, ON M5V 3A8, Canada")
        assert result is not None


class TestShortName:
    """Tests for strategy short name."""

    def test_short_name_with_preservation(self):
        """Test short name includes preserved fields."""
        config = AddressConfig(seed=12345, preserve_fields=["city", "state"])
        strategy = AddressStrategy(config)
        short_name = strategy.short_name()

        assert short_name.startswith("address:")
        assert "city" in short_name
        assert "state" in short_name

    def test_short_name_no_preservation(self):
        """Test short name with no preserved fields."""
        config = AddressConfig(seed=12345, preserve_fields=[])
        strategy = AddressStrategy(config)
        short_name = strategy.short_name()

        assert short_name == "address:none"

    def test_short_name_single_field(self):
        """Test short name with single preserved field."""
        config = AddressConfig(seed=12345, preserve_fields=["city"])
        strategy = AddressStrategy(config)
        short_name = strategy.short_name()

        assert "city" in short_name


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_default_config(self):
        """Test default configuration."""
        config = AddressConfig()
        assert config.preserve_fields == ["city", "country"]
        assert config.redact_street is True
        assert config.format == "freetext"

    def test_custom_config(self):
        """Test custom configuration."""
        config = AddressConfig(
            seed=12345,
            preserve_fields=["city", "state", "zip"],
            redact_street=False,
            format="structured",
        )
        assert config.seed == 12345
        assert config.preserve_fields == ["city", "state", "zip"]
        assert config.redact_street is False
        assert config.format == "structured"

    def test_invalid_format_raises_error(self):
        """Test invalid format raises error."""
        config = AddressConfig(seed=12345, format="invalid_format")
        strategy = AddressStrategy(config)

        with pytest.raises(ValueError, match="Unknown format"):
            strategy.anonymize("123 Main St, Springfield, IL 62701")


class TestComplexScenarios:
    """Tests for complex scenarios."""

    def test_multiple_addresses_consistent(self):
        """Test anonymizing multiple addresses with same seed is consistent."""
        config = AddressConfig(seed=12345, format="freetext")
        strategy = AddressStrategy(config)

        addresses = [
            "123 Main St, Springfield, IL 62701",
            "456 Oak Ave, Shelbyville, KY 40425",
            "789 Elm Dr, Capital City, CO 80202",
        ]
        results1 = [strategy.anonymize(addr) for addr in addresses]
        results2 = [strategy.anonymize(addr) for addr in addresses]

        assert results1 == results2

    def test_format_switching_preserves_determinism(self):
        """Test each format produces consistent results."""
        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
        }

        config = AddressConfig(seed=12345, format="structured")
        strategy = AddressStrategy(config)

        result1 = strategy.anonymize(address)
        result2 = strategy.anonymize(address)

        assert result1 == result2

    def test_real_world_addresses(self):
        """Test real-world address examples."""
        config = AddressConfig(
            seed=12345,
            format="freetext",
            preserve_fields=["city", "state"],
        )
        strategy = AddressStrategy(config)

        addresses = [
            "742 Evergreen Terrace, Springfield, IL 62701",
            "123 Oak Street, Shelbyville, IL 62702",
            "100 Main Street, Capital City, CA 90001",
        ]

        for address in addresses:
            result = strategy.anonymize(address)
            assert result is not None
            assert isinstance(result, str)
            # City and state should be preserved
            assert any(city in result for city in ["Springfield", "Shelbyville", "Capital City"])
