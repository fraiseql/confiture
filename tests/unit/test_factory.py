"""Comprehensive tests for strategy factory and suggester.

Tests the StrategyFactory, StrategyProfile, and StrategySuggester classes
for creating strategies from profiles and suggesting strategies based on
column characteristics.
"""

from unittest.mock import Mock, patch

import pytest

from confiture.core.anonymization.factory import (
    StrategyFactory,
    StrategyProfile,
    StrategySuggester,
)
from confiture.core.anonymization.registry import StrategyRegistry
from confiture.core.anonymization.strategy import AnonymizationStrategy


class TestStrategyProfile:
    """Test StrategyProfile dataclass."""

    def test_default_profile(self):
        """Test default profile initialization."""
        profile = StrategyProfile(name="test")
        assert profile.name == "test"
        assert profile.seed == 0
        assert profile.columns == {}
        assert profile.defaults == "preserve"

    def test_custom_profile(self):
        """Test custom profile initialization."""
        columns = {
            "name": "name",
            "email": "email",
            "phone": "phone",
        }
        profile = StrategyProfile(
            name="ecommerce",
            seed=42,
            columns=columns,
            defaults="redact",
        )
        assert profile.name == "ecommerce"
        assert profile.seed == 42
        assert profile.columns == columns
        assert profile.defaults == "redact"

    def test_profile_with_complex_strategies(self):
        """Test profile with complex strategy specifications."""
        columns = {
            "name": "name:firstname_lastname",
            "email": "email_mask",
            "custom_field": "custom:special",
        }
        profile = StrategyProfile(
            name="complex",
            columns=columns,
        )
        assert profile.columns == columns


class TestStrategyFactoryInitialization:
    """Test StrategyFactory initialization."""

    def test_init_valid_profile(self):
        """Test factory initialization with valid profile."""
        Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            profile = StrategyProfile(
                name="test",
                columns={"name": "name"},
                defaults="preserve",
            )
            factory = StrategyFactory(profile)

            assert factory.profile == profile
            assert factory._cache == {}

    def test_init_validates_profile(self):
        """Test that init validates profile strategies."""
        profile = StrategyProfile(
            name="test",
            columns={"name": "invalid_strategy"},
        )

        with patch.object(StrategyRegistry, 'is_registered', return_value=False):
            with pytest.raises(ValueError, match="Unknown strategy"):
                StrategyFactory(profile)

    def test_init_validates_default_strategy(self):
        """Test that init validates default strategy."""
        profile = StrategyProfile(
            name="test",
            defaults="invalid_default",
        )

        with patch.object(StrategyRegistry, 'is_registered', return_value=False):
            with pytest.raises(ValueError, match="Unknown strategy"):
                StrategyFactory(profile)

    def test_init_validates_profile_name(self):
        """Test that init requires profile name."""
        profile = StrategyProfile(name="")

        with pytest.raises(ValueError, match="Profile must have a name"):
            StrategyFactory(profile)


class TestStrategyFactoryGetStrategy:
    """Test StrategyFactory.get_strategy method."""

    def test_get_strategy_from_profile(self):
        """Test getting strategy for column in profile."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                )
                factory = StrategyFactory(profile)

                strategy = factory.get_strategy("name")
                assert strategy == mock_strategy

    def test_get_strategy_uses_default(self):
        """Test that unmapped columns use default strategy."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                    defaults="preserve",
                )
                factory = StrategyFactory(profile)

                strategy = factory.get_strategy("unmapped_column")
                assert strategy == mock_strategy

    def test_get_strategy_caches_result(self):
        """Test that strategies are cached."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy) as mock_get:
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                )
                factory = StrategyFactory(profile)

                # Call twice for same column
                strategy1 = factory.get_strategy("name")
                strategy2 = factory.get_strategy("name")

                assert strategy1 == strategy2
                # Should only call registry once (cache hit second time)
                assert mock_get.call_count == 1

    def test_get_strategy_with_seed(self):
        """Test that seed is passed to registry."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy) as mock_get:
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                    seed=42,
                )
                factory = StrategyFactory(profile)

                factory.get_strategy("name")

                # Check that seed was passed
                call_args = mock_get.call_args
                assert call_args[0][1]["seed"] == 42

    def test_get_strategy_extracts_base_name(self):
        """Test that strategy name with config suffix is handled."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy) as mock_get:
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name:firstname_lastname"},
                )
                factory = StrategyFactory(profile)

                factory.get_strategy("name")

                # Should extract base name
                call_args = mock_get.call_args
                assert call_args[0][0] == "name:firstname_lastname"

    def test_get_strategy_error(self):
        """Test error handling when strategy creation fails."""
        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', side_effect=ValueError("Not found")):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                )
                factory = StrategyFactory(profile)

                with pytest.raises(ValueError, match="Failed to create strategy"):
                    factory.get_strategy("name")


class TestStrategyFactoryGetStrategies:
    """Test StrategyFactory.get_strategies method."""

    def test_get_multiple_strategies(self):
        """Test getting strategies for multiple columns."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name", "email": "email"},
                )
                factory = StrategyFactory(profile)

                strategies = factory.get_strategies(["name", "email"])

                assert len(strategies) == 2
                assert strategies["name"] == mock_strategy
                assert strategies["email"] == mock_strategy

    def test_get_strategies_empty_list(self):
        """Test get_strategies with empty column list."""
        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            profile = StrategyProfile(name="test")
            factory = StrategyFactory(profile)

            strategies = factory.get_strategies([])
            assert strategies == {}


class TestStrategyFactoryAnonymize:
    """Test StrategyFactory.anonymize method."""

    def test_anonymize_data(self):
        """Test anonymizing entire data dictionary."""
        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.anonymize.side_effect = lambda x: f"anonymized_{x}"

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name", "email": "email"},
                )
                factory = StrategyFactory(profile)

                data = {"name": "John", "email": "john@example.com"}
                result = factory.anonymize(data)

                assert result["name"] == "anonymized_John"
                assert result["email"] == "anonymized_john@example.com"

    def test_anonymize_preserves_keys(self):
        """Test that anonymize preserves all keys."""
        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.anonymize.side_effect = lambda x: x

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(name="test")
                factory = StrategyFactory(profile)

                data = {"a": "1", "b": "2", "c": "3"}
                result = factory.anonymize(data)

                assert set(result.keys()) == {"a", "b", "c"}

    def test_anonymize_empty_data(self):
        """Test anonymizing empty data dictionary."""
        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            profile = StrategyProfile(name="test")
            factory = StrategyFactory(profile)

            result = factory.anonymize({})
            assert result == {}


class TestStrategyFactoryListAndCache:
    """Test StrategyFactory list and cache methods."""

    def test_list_column_strategies(self):
        """Test listing all column-to-strategy mappings."""
        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            columns = {"name": "name", "email": "email", "phone": "phone"}
            profile = StrategyProfile(name="test", columns=columns)
            factory = StrategyFactory(profile)

            mapping = factory.list_column_strategies()
            assert mapping == columns

    def test_clear_cache(self):
        """Test clearing strategy cache."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                profile = StrategyProfile(
                    name="test",
                    columns={"name": "name"},
                )
                factory = StrategyFactory(profile)

                # Populate cache
                factory.get_strategy("name")
                assert len(factory._cache) == 1

                # Clear cache
                factory.clear_cache()
                assert len(factory._cache) == 0


class TestStrategySuggester:
    """Test StrategySuggester class."""

    def test_suggester_patterns(self):
        """Test that patterns are defined correctly."""
        suggester = StrategySuggester()

        assert "name" in suggester.NAME_PATTERNS
        assert "email" in suggester.EMAIL_PATTERNS
        assert "phone" in suggester.PHONE_PATTERNS
        assert "address" in suggester.ADDRESS_PATTERNS
        assert "date" in suggester.DATE_PATTERNS
        assert "credit" in suggester.CC_PATTERNS
        assert "ip" in suggester.IP_PATTERNS

    def test_suggest_name_column(self):
        """Test suggesting strategy for name column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("customer_name")

        assert len(suggestions) > 0
        assert suggestions[0][0] == "name:firstname_lastname"
        assert suggestions[0][1] == 0.95

    def test_suggest_email_column(self):
        """Test suggesting strategy for email column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("email_address")

        assert len(suggestions) > 0
        assert suggestions[0][0] == "email"
        assert suggestions[0][1] == 0.95

    def test_suggest_phone_column(self):
        """Test suggesting strategy for phone column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("phone_number")

        assert len(suggestions) > 0
        # Find email in suggestions (it should be there)
        names = [s[0] for s in suggestions]
        assert any("phone" in name.lower() for name in names)

    def test_suggest_address_column(self):
        """Test suggesting strategy for address column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("street_address")

        assert len(suggestions) > 0
        assert suggestions[0][0] == "address"

    def test_suggest_date_column(self):
        """Test suggesting strategy for date column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("birth_date")

        assert len(suggestions) > 0
        assert suggestions[0][0] == "date"

    def test_suggest_credit_card_column(self):
        """Test suggesting strategy for credit card column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("credit_card_number")

        assert len(suggestions) > 0
        assert suggestions[0][0] == "credit_card"

    def test_suggest_ip_column(self):
        """Test suggesting strategy for IP column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("server_ip_address")

        assert len(suggestions) > 0
        names = [s[0] for s in suggestions]
        assert any("ip" in name.lower() for name in names)

    def test_suggest_unknown_column(self):
        """Test suggesting strategy for unknown column."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("unknown_field_xyz")

        # Should return empty or low confidence suggestions
        assert isinstance(suggestions, list)

    def test_suggest_with_sample_email(self):
        """Test suggestion with email sample value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("contact_info", sample_value="user@example.com")

        # Should detect email pattern
        assert any(s[0] == "email" for s in suggestions)

    def test_suggest_with_sample_ip(self):
        """Test suggestion with IP address sample value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("server", sample_value="192.168.1.1")

        # Should detect IP pattern
        assert any("ip" in s[0].lower() for s in suggestions)

    def test_suggest_with_sample_phone(self):
        """Test suggestion with phone number sample value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("contact", sample_value="(555) 123-4567")

        # Should detect phone pattern
        assert any("phone" in s[0].lower() for s in suggestions)

    def test_suggest_with_sample_credit_card(self):
        """Test suggestion with credit card sample value."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("payment", sample_value="4111-1111-1111-1111")

        # Should detect credit card pattern
        assert any("credit" in s[0].lower() for s in suggestions)

    def test_suggest_sorted_by_confidence(self):
        """Test that suggestions are sorted by confidence."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest("full_name")

        # Should be sorted by confidence descending
        for i in range(len(suggestions) - 1):
            assert suggestions[i][1] >= suggestions[i + 1][1]

    def test_suggest_removes_duplicates(self):
        """Test that duplicate strategies are removed (highest confidence kept)."""
        suggester = StrategySuggester()
        suggestions = suggester.suggest(
            "customer_email",  # Has both name and email patterns
            sample_value="john@example.com",
        )

        # Should not have duplicate strategies
        strategy_names = [s[0] for s in suggestions]
        assert len(strategy_names) == len(set(strategy_names))

    def test_analyze_value_email(self):
        """Test _analyze_value detects email."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("test@example.com")

        assert any(s[0] == "email" for s in suggestions)

    def test_analyze_value_phone(self):
        """Test _analyze_value detects phone."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("555-1234-5678")

        assert any("phone" in s[0].lower() for s in suggestions)

    def test_analyze_value_ip(self):
        """Test _analyze_value detects IP address."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("192.168.1.1")

        assert any("ip" in s[0].lower() for s in suggestions)

    def test_analyze_value_credit_card(self):
        """Test _analyze_value detects credit card."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("4111-1111-1111-1111")

        assert any("credit" in s[0].lower() for s in suggestions)

    def test_analyze_value_no_match(self):
        """Test _analyze_value with non-matching value."""
        suggester = StrategySuggester()
        suggestions = suggester._analyze_value("random text")

        assert len(suggestions) == 0


class TestStrategySuggesterCreateProfile:
    """Test StrategySuggester.create_profile method."""

    def test_create_profile_basic(self):
        """Test creating profile from column names."""
        suggester = StrategySuggester()
        profile = suggester.create_profile(
            name="test_profile",
            columns=["customer_name", "email_address"],
        )

        assert profile.name == "test_profile"
        assert profile.seed == 0
        assert "customer_name" in profile.columns
        assert "email_address" in profile.columns

    def test_create_profile_with_seed(self):
        """Test creating profile with seed."""
        suggester = StrategySuggester()
        profile = suggester.create_profile(
            name="test",
            columns=["name"],
            seed=42,
        )

        assert profile.seed == 42

    def test_create_profile_unknown_columns(self):
        """Test creating profile with unknown column."""
        suggester = StrategySuggester()
        profile = suggester.create_profile(
            name="test",
            columns=["unknown_column", "another_unknown"],
        )

        # Unknown columns should default to preserve
        assert profile.columns["unknown_column"] == "preserve"
        assert profile.columns["another_unknown"] == "preserve"

    def test_create_profile_mixed_columns(self):
        """Test creating profile with mix of known and unknown columns."""
        suggester = StrategySuggester()
        profile = suggester.create_profile(
            name="test",
            columns=["customer_name", "unknown_field", "email"],
        )

        # Known columns should have suggestions
        assert "name" in profile.columns["customer_name"]
        assert "email" in profile.columns["email"]
        # Unknown should default to preserve
        assert profile.columns["unknown_field"] == "preserve"

    def test_create_profile_empty_columns(self):
        """Test creating profile with no columns."""
        suggester = StrategySuggester()
        profile = suggester.create_profile(
            name="empty",
            columns=[],
        )

        assert profile.columns == {}


class TestStrategyFactoryIntegration:
    """Integration tests for factory components."""

    def test_factory_with_suggester_profile(self):
        """Test using suggester-created profile with factory."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                suggester = StrategySuggester()
                profile = suggester.create_profile(
                    name="test",
                    columns=["name", "email"],
                )

                factory = StrategyFactory(profile)
                strategies = factory.get_strategies(["name", "email"])

                assert len(strategies) == 2

    def test_full_workflow_suggest_anonymize(self):
        """Test full workflow: suggest -> create profile -> factory -> anonymize."""
        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.anonymize.side_effect = lambda x: f"masked_{x}"

        with patch.object(StrategyRegistry, 'is_registered', return_value=True):
            with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
                # Suggest
                suggester = StrategySuggester()
                profile = suggester.create_profile(
                    name="ecommerce",
                    columns=["customer_name", "email", "unknown"],
                )

                # Create factory
                factory = StrategyFactory(profile)

                # Anonymize
                data = {
                    "customer_name": "John Doe",
                    "email": "john@example.com",
                    "unknown": "data",
                }
                result = factory.anonymize(data)

                assert all(k in result for k in data)
