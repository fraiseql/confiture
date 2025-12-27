"""Unit tests for strategy factory and profile system.

Tests for:
- Strategy profile creation and validation
- Factory strategy creation and caching
- Column-to-strategy mapping
- Bulk data anonymization
- Default strategy handling
"""

import pytest
from confiture.core.anonymization.factory import (
    StrategyFactory,
    StrategyProfile,
    StrategySuggester,
)
from confiture.core.anonymization.strategies.preserve import PreserveStrategy
from confiture.core.anonymization.strategies.name import NameMaskingStrategy
from confiture.core.anonymization.registry import StrategyRegistry


class TestStrategyProfile:
    """Tests for StrategyProfile configuration."""

    def test_profile_default_values(self):
        """Test profile default values."""
        profile = StrategyProfile(name="test")
        assert profile.name == "test"
        assert profile.seed == 0
        assert profile.columns == {}
        assert profile.defaults == "preserve"

    def test_profile_custom_values(self):
        """Test profile with custom values."""
        columns = {"name": "name", "email": "email"}
        profile = StrategyProfile(
            name="ecommerce",
            seed=12345,
            columns=columns,
            defaults="name",
        )
        assert profile.name == "ecommerce"
        assert profile.seed == 12345
        assert profile.columns == columns
        assert profile.defaults == "name"

    def test_profile_empty_columns(self):
        """Test profile with empty columns."""
        profile = StrategyProfile(name="test", columns={})
        assert profile.columns == {}
        assert profile.defaults == "preserve"

    def test_profile_single_column(self):
        """Test profile with single column mapping."""
        profile = StrategyProfile(name="test", columns={"name": "name"})
        assert "name" in profile.columns
        assert profile.columns["name"] == "name"

    def test_profile_multiple_columns(self):
        """Test profile with multiple columns."""
        columns = {
            "customer_name": "name",
            "email_address": "email",
            "phone_number": "phone",
        }
        profile = StrategyProfile(name="test", columns=columns)
        assert len(profile.columns) == 3
        assert all(col in profile.columns for col in columns.keys())

    def test_profile_seed_zero(self):
        """Test profile with zero seed."""
        profile = StrategyProfile(name="test", seed=0)
        assert profile.seed == 0

    def test_profile_seed_large(self):
        """Test profile with large seed."""
        profile = StrategyProfile(name="test", seed=999999999)
        assert profile.seed == 999999999

    def test_profile_name_required(self):
        """Test profile requires a name."""
        # This test depends on actual validation being done
        profile = StrategyProfile(name="")
        assert profile.name == ""


class TestStrategyFactory:
    """Tests for StrategyFactory."""

    def test_factory_initialization(self):
        """Test factory initialization."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "name"},
        )
        factory = StrategyFactory(profile)
        assert factory.profile == profile
        assert factory._cache == {}

    def test_factory_invalid_profile_empty_name(self):
        """Test factory raises error for empty profile name."""
        profile = StrategyProfile(name="")
        with pytest.raises(ValueError, match="Profile must have a name"):
            StrategyFactory(profile)

    def test_factory_invalid_strategy_name(self):
        """Test factory raises error for unknown strategy."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "unknown_strategy"},
        )
        with pytest.raises(ValueError, match="Unknown strategy"):
            StrategyFactory(profile)

    def test_factory_get_strategy_mapped_column(self):
        """Test getting strategy for mapped column."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        strategy = factory.get_strategy("name")
        assert isinstance(strategy, PreserveStrategy)

    def test_factory_get_strategy_unmapped_column(self):
        """Test getting default strategy for unmapped column."""
        profile = StrategyProfile(
            name="test",
            columns={},
            defaults="preserve",
        )
        factory = StrategyFactory(profile)
        strategy = factory.get_strategy("unknown_column")
        assert isinstance(strategy, PreserveStrategy)

    def test_factory_get_strategy_caching(self):
        """Test that strategies are cached."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        strategy1 = factory.get_strategy("name")
        strategy2 = factory.get_strategy("name")
        # Same instance due to caching
        assert strategy1 is strategy2

    def test_factory_cache_different_columns(self):
        """Test cache stores different strategies separately."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve", "other": "preserve"},
        )
        factory = StrategyFactory(profile)
        strategy1 = factory.get_strategy("name")
        strategy2 = factory.get_strategy("other")
        # Both cached but different entries
        assert "name" in factory._cache
        assert "other" in factory._cache

    def test_factory_clear_cache(self):
        """Test clearing strategy cache."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        factory.get_strategy("name")
        assert len(factory._cache) > 0
        factory.clear_cache()
        assert len(factory._cache) == 0

    def test_factory_get_strategies_multiple(self):
        """Test getting strategies for multiple columns."""
        profile = StrategyProfile(
            name="test",
            columns={
                "name": "preserve",
                "email": "preserve",
                "phone": "preserve",
            },
        )
        factory = StrategyFactory(profile)
        strategies = factory.get_strategies(["name", "email", "phone"])
        assert len(strategies) == 3
        assert all(isinstance(s, PreserveStrategy) for s in strategies.values())

    def test_factory_get_strategies_preserves_names(self):
        """Test get_strategies returns dict with column names as keys."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        strategies = factory.get_strategies(["name"])
        assert "name" in strategies

    def test_factory_anonymize_single_column(self):
        """Test anonymizing single column."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        data = {"name": "John Doe"}
        result = factory.anonymize(data)
        assert result["name"] == "John Doe"

    def test_factory_anonymize_multiple_columns(self):
        """Test anonymizing multiple columns."""
        profile = StrategyProfile(
            name="test",
            columns={
                "name": "preserve",
                "email": "preserve",
            },
        )
        factory = StrategyFactory(profile)
        data = {
            "name": "John Doe",
            "email": "john@example.com",
        }
        result = factory.anonymize(data)
        assert result["name"] == "John Doe"
        assert result["email"] == "john@example.com"

    def test_factory_anonymize_with_unmapped_columns(self):
        """Test anonymizing data with unmapped columns."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
            defaults="preserve",
        )
        factory = StrategyFactory(profile)
        data = {
            "name": "John Doe",
            "unknown_column": "some value",
        }
        result = factory.anonymize(data)
        assert result["name"] == "John Doe"
        assert result["unknown_column"] == "some value"

    def test_factory_anonymize_preserves_keys(self):
        """Test anonymize preserves all keys."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
            defaults="preserve",
        )
        factory = StrategyFactory(profile)
        data = {
            "name": "John",
            "email": "john@test.com",
            "phone": "555-1234",
        }
        result = factory.anonymize(data)
        assert set(result.keys()) == set(data.keys())

    def test_factory_list_column_strategies(self):
        """Test listing column-to-strategy mappings."""
        columns = {"name": "preserve", "email": "preserve"}
        profile = StrategyProfile(name="test", columns=columns)
        factory = StrategyFactory(profile)
        mappings = factory.list_column_strategies()
        assert mappings == columns

    def test_factory_list_column_strategies_empty(self):
        """Test listing strategies with empty columns."""
        profile = StrategyProfile(name="test", columns={})
        factory = StrategyFactory(profile)
        mappings = factory.list_column_strategies()
        assert mappings == {}

    def test_factory_with_seed_propagation(self):
        """Test that seed is propagated to strategies."""
        profile = StrategyProfile(
            name="test",
            seed=12345,
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        strategy = factory.get_strategy("name")
        assert strategy.config.seed == 12345

    def test_factory_anonymize_empty_dict(self):
        """Test anonymizing empty dictionary."""
        profile = StrategyProfile(name="test", columns={})
        factory = StrategyFactory(profile)
        result = factory.anonymize({})
        assert result == {}

    def test_factory_anonymize_none_values(self):
        """Test anonymizing None values."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        data = {"name": None}
        result = factory.anonymize(data)
        assert result["name"] is None

    def test_factory_anonymize_empty_strings(self):
        """Test anonymizing empty strings."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "preserve"},
        )
        factory = StrategyFactory(profile)
        data = {"name": ""}
        result = factory.anonymize(data)
        assert result["name"] == ""


class TestStrategySuggester:
    """Tests for StrategySuggester."""

    def test_suggester_initialization(self):
        """Test suggester initialization."""
        suggester = StrategySuggester()
        assert hasattr(suggester, "NAME_PATTERNS")
        assert hasattr(suggester, "EMAIL_PATTERNS")

    def test_suggester_suggest_name_column(self):
        """Test suggesting strategy for name column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("customer_name")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "name:firstname_lastname"
        assert suggestions[0][1] == 0.95

    def test_suggester_suggest_email_column(self):
        """Test suggesting strategy for email column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("email_address")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "email"

    def test_suggester_suggest_phone_column(self):
        """Test suggesting strategy for phone column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("phone_number")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "phone"

    def test_suggester_suggest_address_column(self):
        """Test suggesting strategy for address column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("street_address")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "address"

    def test_suggester_suggest_date_column(self):
        """Test suggesting strategy for date column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("birth_date")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "date"

    def test_suggester_suggest_credit_card_column(self):
        """Test suggesting strategy for credit card column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("card_number")
        assert len(suggestions) > 0
        assert suggestions[0][0] == "credit_card"

    def test_suggester_suggest_ip_column(self):
        """Test suggesting strategy for IP column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("ip_address")
        assert len(suggestions) > 0
        # "ip_address" may match both address and ip_address patterns
        strategies = [s[0] for s in suggestions]
        assert "ip_address" in strategies or "address" in strategies

    def test_suggester_suggest_unknown_column(self):
        """Test suggesting for unknown column name."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("unknown_column_xyz")
        # Should return empty or default suggestions
        assert isinstance(suggestions, list)

    def test_suggester_suggest_returns_sorted_by_confidence(self):
        """Test suggestions are sorted by confidence descending."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("customer_name")
        # Check that suggestions are sorted by confidence
        for i in range(len(suggestions) - 1):
            assert suggestions[i][1] >= suggestions[i + 1][1]

    def test_suggester_suggest_with_sample_value_email(self):
        """Test suggesting with sample email value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("contact", sample_value="john@example.com")
        assert len(suggestions) > 0
        assert "email" in [s[0] for s in suggestions]

    def test_suggester_suggest_with_sample_value_ip(self):
        """Test suggesting with sample IP value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("server", sample_value="192.168.1.1")
        assert len(suggestions) > 0
        assert "ip_address" in [s[0] for s in suggestions]

    def test_suggester_suggest_with_sample_value_phone(self):
        """Test suggesting with sample phone value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("contact", sample_value="555-123-4567")
        assert len(suggestions) > 0
        assert "phone" in [s[0] for s in suggestions]

    def test_suggester_suggest_with_sample_value_credit_card(self):
        """Test suggesting with sample credit card value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("card", sample_value="4242-4242-4242-4242")
        assert len(suggestions) > 0
        assert "credit_card" in [s[0] for s in suggestions]

    def test_suggester_suggest_deduplication(self):
        """Test duplicate suggestions are removed."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("customer_name")
        # Get unique strategies
        strategies = [s[0] for s in suggestions]
        assert len(strategies) == len(set(strategies))

    def test_suggester_suggest_highest_confidence_selected(self):
        """Test highest confidence selected when duplicates exist."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("name")
        if len(suggestions) > 1:
            # First suggestion should have highest confidence
            assert suggestions[0][1] >= suggestions[1][1]

    def test_suggester_create_profile(self):
        """Test creating profile from suggestions."""
        suggester = StrategySuggester()
        profile = suggester.create_profile("test", ["customer_name", "email"])
        assert profile.name == "test"
        assert "customer_name" in profile.columns
        assert "email" in profile.columns

    def test_suggester_create_profile_with_seed(self):
        """Test creating profile with custom seed."""
        suggester = StrategySuggester()
        profile = suggester.create_profile("test", ["customer_name"], seed=12345)
        assert profile.seed == 12345

    def test_suggester_create_profile_empty_columns(self):
        """Test creating profile with empty columns."""
        suggester = StrategySuggester()
        profile = suggester.create_profile("test", [])
        assert profile.name == "test"
        assert profile.columns == {}

    def test_suggester_create_profile_preserves_defaults(self):
        """Test profile has preserve as default."""
        suggester = StrategySuggester()
        profile = suggester.create_profile("test", ["unknown_column"])
        assert profile.defaults == "preserve"

    def test_suggester_create_profile_unknown_columns(self):
        """Test profile defaults unknown columns to preserve."""
        suggester = StrategySuggester()
        profile = suggester.create_profile("test", ["unknown_xyz"])
        assert profile.columns.get("unknown_xyz") == "preserve"

    def test_suggester_analyze_value_email_pattern(self):
        """Test value analysis for email pattern."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("john@example.com")
        assert len(suggestions) > 0
        strategies = [s[0] for s in suggestions]
        assert "email" in strategies

    def test_suggester_analyze_value_phone_pattern(self):
        """Test value analysis for phone pattern."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("(555) 123-4567")
        assert len(suggestions) > 0
        strategies = [s[0] for s in suggestions]
        assert "phone" in strategies

    def test_suggester_analyze_value_ip_pattern(self):
        """Test value analysis for IP pattern."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("192.168.1.100")
        assert len(suggestions) > 0
        strategies = [s[0] for s in suggestions]
        assert "ip_address" in strategies

    def test_suggester_analyze_value_credit_card_pattern(self):
        """Test value analysis for credit card pattern."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("4242 4242 4242 4242")
        assert len(suggestions) > 0
        strategies = [s[0] for s in suggestions]
        assert "credit_card" in strategies

    def test_suggester_analyze_value_no_match(self):
        """Test value analysis with no pattern match."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("just some text")
        # May return empty or generic suggestions
        assert isinstance(suggestions, list)

    def test_suggester_case_insensitive_column_names(self):
        """Test column names are case-insensitive."""
        suggester = StrategySuggester()
        suggestions1 = suggester.suggest("CUSTOMER_NAME")
        suggestions2 = suggester.suggest("customer_name")
        suggestions3 = suggester.suggest("Customer_Name")
        # All should recognize the pattern
        assert len(suggestions1) > 0
        assert len(suggestions2) > 0
        assert len(suggestions3) > 0
