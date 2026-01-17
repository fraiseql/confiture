"""Comprehensive tests for name masking anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.name import (
    FIRST_NAMES,
    LAST_NAMES,
    NameMaskConfig,
    NameMaskingStrategy,
)


class TestNameMaskingStrategy:
    """Tests for NameMaskingStrategy class."""

    @pytest.fixture
    def strategy_firstname_lastname(self):
        """Create strategy with firstname_lastname format."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        return NameMaskingStrategy(config)

    @pytest.fixture
    def strategy_initials(self):
        """Create strategy with initials format."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        return NameMaskingStrategy(config)

    @pytest.fixture
    def strategy_random(self):
        """Create strategy with random format."""
        config = NameMaskConfig(seed=12345, format_type="random")
        return NameMaskingStrategy(config)

    @pytest.fixture
    def strategy_case_preserving(self):
        """Create strategy with case preservation."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname", case_preserving=True)
        return NameMaskingStrategy(config)

    # firstname_lastname format tests
    def test_anonymize_firstname_lastname_basic(self, strategy_firstname_lastname):
        """Test basic firstname_lastname anonymization."""
        result = strategy_firstname_lastname.anonymize("John Doe")
        assert result != "John Doe"
        parts = result.split()
        assert len(parts) == 2
        # Should be valid names from pools
        assert parts[0] in FIRST_NAMES or parts[0].lower() in [n.lower() for n in FIRST_NAMES]

    def test_anonymize_firstname_lastname_deterministic(self, strategy_firstname_lastname):
        """Test same input gives same output."""
        name = "John Doe"
        result1 = strategy_firstname_lastname.anonymize(name)
        result2 = strategy_firstname_lastname.anonymize(name)
        assert result1 == result2

    def test_anonymize_firstname_lastname_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        config2 = NameMaskConfig(seed=67890, format_type="firstname_lastname")
        strategy1 = NameMaskingStrategy(config1)
        strategy2 = NameMaskingStrategy(config2)

        name = "John Doe"
        result1 = strategy1.anonymize(name)
        result2 = strategy2.anonymize(name)
        assert result1 != result2

    def test_anonymize_single_name(self, strategy_firstname_lastname):
        """Test anonymization of single name."""
        result = strategy_firstname_lastname.anonymize("John")
        parts = result.split()
        assert len(parts) == 2  # Still produces first last

    def test_anonymize_three_part_name(self, strategy_firstname_lastname):
        """Test anonymization of name with middle name."""
        result = strategy_firstname_lastname.anonymize("John Michael Doe")
        parts = result.split()
        assert len(parts) == 2  # Outputs first last

    # initials format tests
    def test_anonymize_initials_basic(self, strategy_initials):
        """Test basic initials anonymization."""
        result = strategy_initials.anonymize("John Doe")
        assert result == "J.D."

    def test_anonymize_initials_three_names(self, strategy_initials):
        """Test initials with three names."""
        result = strategy_initials.anonymize("John Michael Doe")
        assert result == "J.M.D."

    def test_anonymize_initials_single_name(self, strategy_initials):
        """Test initials with single name."""
        result = strategy_initials.anonymize("John")
        assert result == "J."

    def test_anonymize_initials_lowercase(self, strategy_initials):
        """Test initials converts to uppercase."""
        result = strategy_initials.anonymize("john doe")
        assert result == "J.D."

    def test_anonymize_initials_deterministic(self, strategy_initials):
        """Test initials are deterministic."""
        result1 = strategy_initials.anonymize("John Doe")
        result2 = strategy_initials.anonymize("John Doe")
        assert result1 == result2

    # random format tests
    def test_anonymize_random_basic(self, strategy_random):
        """Test basic random anonymization."""
        result = strategy_random.anonymize("John Doe")
        assert result != "John Doe"
        # Length should be same as trimmed original
        assert len(result) == len("John Doe")

    def test_anonymize_random_deterministic(self, strategy_random):
        """Test random is deterministic with same seed."""
        name = "John Doe"
        result1 = strategy_random.anonymize(name)
        result2 = strategy_random.anonymize(name)
        assert result1 == result2

    def test_anonymize_random_different_seeds(self):
        """Test random differs with different seeds."""
        config1 = NameMaskConfig(seed=12345, format_type="random")
        config2 = NameMaskConfig(seed=67890, format_type="random")
        strategy1 = NameMaskingStrategy(config1)
        strategy2 = NameMaskingStrategy(config2)

        name = "John Doe"
        result1 = strategy1.anonymize(name)
        result2 = strategy2.anonymize(name)
        assert result1 != result2

    def test_anonymize_random_alphanumeric(self, strategy_random):
        """Test random output is alphanumeric."""
        result = strategy_random.anonymize("John Doe")
        assert result.isalnum()

    # case preservation tests
    def test_case_preserving_lowercase_first(self, strategy_case_preserving):
        """Test lowercase first name is preserved."""
        result = strategy_case_preserving.anonymize("john Doe")
        parts = result.split()
        # First name should be lowercase
        assert parts[0][0].islower()

    def test_case_preserving_lowercase_last(self, strategy_case_preserving):
        """Test lowercase last name is preserved."""
        result = strategy_case_preserving.anonymize("John doe")
        parts = result.split()
        # Last name should be lowercase
        assert parts[1][0].islower()

    def test_case_preserving_uppercase_both(self, strategy_case_preserving):
        """Test uppercase both names preserved."""
        result = strategy_case_preserving.anonymize("John Doe")
        parts = result.split()
        assert parts[0][0].isupper()
        assert parts[1][0].isupper()

    # Unknown format test
    def test_unknown_format_raises(self):
        """Test unknown format raises ValueError."""
        config = NameMaskConfig(seed=12345, format_type="invalid")
        strategy = NameMaskingStrategy(config)

        with pytest.raises(ValueError, match="Unknown format_type"):
            strategy.anonymize("John Doe")

    # Edge cases
    def test_anonymize_none_returns_none(self, strategy_firstname_lastname):
        """Test None input returns None."""
        assert strategy_firstname_lastname.anonymize(None) is None

    def test_anonymize_empty_string(self, strategy_firstname_lastname):
        """Test empty string returns empty string."""
        assert strategy_firstname_lastname.anonymize("") == ""

    def test_anonymize_whitespace_only(self, strategy_firstname_lastname):
        """Test whitespace returns whitespace."""
        assert strategy_firstname_lastname.anonymize("   ") == "   "

    def test_anonymize_initials_empty(self, strategy_initials):
        """Test initials with empty parts returns original."""
        # After strip and split, empty returns original
        result = strategy_initials.anonymize("   ")
        assert result == "   "

    def test_anonymize_random_empty_value(self, strategy_random):
        """Test random with empty value returns original."""
        result = strategy_random.anonymize("")
        assert result == ""

    # Validate method
    def test_validate_string(self, strategy_firstname_lastname):
        """Test validate accepts string."""
        assert strategy_firstname_lastname.validate("John Doe") is True

    def test_validate_none(self, strategy_firstname_lastname):
        """Test validate accepts None."""
        assert strategy_firstname_lastname.validate(None) is True

    def test_validate_non_string(self, strategy_firstname_lastname):
        """Test validate rejects non-string."""
        assert strategy_firstname_lastname.validate(12345) is False
        assert strategy_firstname_lastname.validate(["John", "Doe"]) is False

    # Short name
    def test_short_name_firstname_lastname(self, strategy_firstname_lastname):
        """Test short name for firstname_lastname format."""
        assert strategy_firstname_lastname.short_name() == "name:firstname_lastname"

    def test_short_name_initials(self, strategy_initials):
        """Test short name for initials format."""
        assert strategy_initials.short_name() == "name:initials"

    def test_short_name_random(self, strategy_random):
        """Test short name for random format."""
        assert strategy_random.short_name() == "name:random"

    # Strategy name and config type
    def test_strategy_name(self, strategy_firstname_lastname):
        """Test strategy name is name."""
        assert strategy_firstname_lastname.strategy_name == "name"

    def test_config_type(self, strategy_firstname_lastname):
        """Test config type is NameMaskConfig."""
        assert strategy_firstname_lastname.config_type == NameMaskConfig


class TestNameMaskConfig:
    """Tests for NameMaskConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = NameMaskConfig(seed=12345)
        assert config.format_type == "firstname_lastname"
        assert config.preserve_initial is False
        assert config.case_preserving is True

    def test_custom_format_type(self):
        """Test custom format_type."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        assert config.format_type == "initials"

    def test_custom_preserve_initial(self):
        """Test custom preserve_initial."""
        config = NameMaskConfig(seed=12345, preserve_initial=True)
        assert config.preserve_initial is True

    def test_custom_case_preserving(self):
        """Test custom case_preserving."""
        config = NameMaskConfig(seed=12345, case_preserving=False)
        assert config.case_preserving is False

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = NameMaskConfig(
            seed=12345,
            format_type="random",
            preserve_initial=True,
            case_preserving=False,
        )
        assert config.format_type == "random"
        assert config.preserve_initial is True
        assert config.case_preserving is False


class TestNameConstants:
    """Tests for name constants."""

    def test_first_names_not_empty(self):
        """Test FIRST_NAMES is not empty."""
        assert len(FIRST_NAMES) > 0

    def test_last_names_not_empty(self):
        """Test LAST_NAMES is not empty."""
        assert len(LAST_NAMES) > 0

    def test_first_names_are_strings(self):
        """Test all first names are strings."""
        assert all(isinstance(name, str) for name in FIRST_NAMES)

    def test_last_names_are_strings(self):
        """Test all last names are strings."""
        assert all(isinstance(name, str) for name in LAST_NAMES)

    def test_first_names_diversity(self):
        """Test sufficient diversity in first names."""
        assert len(FIRST_NAMES) >= 50

    def test_last_names_diversity(self):
        """Test sufficient diversity in last names."""
        assert len(LAST_NAMES) >= 50


class TestNameEdgeCases:
    """Edge case tests for name anonymization."""

    def test_various_names(self):
        """Test various name formats."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)

        names = [
            "John Doe",
            "Mary Jane Watson",
            "Smith",
            "O'Brien",
            "Van Der Berg",
        ]

        for name in names:
            result = strategy.anonymize(name)
            assert result != name
            assert len(result.split()) == 2  # Always outputs first last

    def test_special_characters_in_name(self):
        """Test name with special characters."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)

        # Name with apostrophe
        result = strategy.anonymize("O'Brien")
        assert result == "O."

    def test_hyphenated_name_initials(self):
        """Test hyphenated name with initials format."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)

        # Hyphenated name is one "part"
        result = strategy.anonymize("Mary-Jane Watson")
        assert result == "M.W."

    def test_names_with_many_parts(self):
        """Test name with many parts."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)

        result = strategy.anonymize("Juan Carlos De La Cruz Martinez")
        assert result == "J.C.D.L.C.M."

    def test_random_preserves_length(self):
        """Test random format preserves length."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)

        names = ["John", "John Doe", "Mary Jane Watson"]
        for name in names:
            result = strategy.anonymize(name)
            # Length matches stripped original
            assert len(result) == len(name.strip())
