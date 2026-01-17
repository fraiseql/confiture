"""Unit tests for name masking strategy.

Tests:
- Name masking in firstname_lastname format
- Name masking in initials format
- Name masking in random format
- Determinism (seed-based reproducibility)
- NULL and empty string handling
- Case preservation
- Multi-part names (3+ parts)
- Edge cases
"""

import pytest

from confiture.core.anonymization.strategies.name import (
    NameMaskConfig,
    NameMaskingStrategy,
)


class TestNameMaskingBasics:
    """Basic name masking tests."""

    def test_anonymize_none_returns_none(self):
        """Test anonymizing None returns None."""
        config = NameMaskConfig(seed=12345)
        strategy = NameMaskingStrategy(config)
        assert strategy.anonymize(None) is None

    def test_anonymize_empty_string_returns_empty(self):
        """Test anonymizing empty string returns empty."""
        config = NameMaskConfig(seed=12345)
        strategy = NameMaskingStrategy(config)
        assert strategy.anonymize("") == ""

    def test_anonymize_whitespace_returns_whitespace(self):
        """Test anonymizing whitespace returns whitespace."""
        config = NameMaskConfig(seed=12345)
        strategy = NameMaskingStrategy(config)
        assert strategy.anonymize("   ") == "   "

    def test_strategy_name(self):
        """Test strategy has correct name."""
        config = NameMaskConfig(seed=12345)
        strategy = NameMaskingStrategy(config)
        assert strategy.strategy_name == "name"


class TestFirstnameLastnameFormat:
    """Tests for firstname_lastname format."""

    def test_masks_simple_name(self):
        """Test masking simple two-part name."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("John Doe")

        # Should be valid names from pools
        assert result is not None
        assert isinstance(result, str)
        parts = result.split()
        assert len(parts) == 2
        assert parts[0] != "John"
        assert parts[1] != "Doe"

    def test_deterministic_output(self):
        """Test same seed produces same output."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)

        result1 = strategy.anonymize("John Doe")
        result2 = strategy.anonymize("John Doe")

        assert result1 == result2

    def test_different_seed_different_output(self):
        """Test different seed produces different output."""
        strategy1 = NameMaskingStrategy(
            NameMaskConfig(seed=12345, format_type="firstname_lastname")
        )
        strategy2 = NameMaskingStrategy(
            NameMaskConfig(seed=67890, format_type="firstname_lastname")
        )

        result1 = strategy1.anonymize("John Doe")
        result2 = strategy2.anonymize("John Doe")

        assert result1 != result2

    def test_different_input_different_output(self):
        """Test different input produces different output with same seed."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)

        result1 = strategy.anonymize("John Doe")
        result2 = strategy.anonymize("Jane Smith")

        # Different inputs should generally produce different outputs
        # (though theoretically possible to collide with same name pool)
        assert result1 != result2

    def test_single_word_name(self):
        """Test handling single word name."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("Madonna")

        # Should still produce firstname lastname format
        assert " " in result
        parts = result.split()
        assert len(parts) == 2

    def test_three_part_name(self):
        """Test handling three-part name."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("Jean Claude Van Damme")

        # Should produce firstname lastname (only first 2 words of masked name)
        assert " " in result
        parts = result.split()
        assert len(parts) == 2

    def test_case_preserving_lowercase(self):
        """Test case preservation with lowercase input."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname", case_preserving=True)
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("john doe")

        parts = result.split()
        # First character should be lowercase if original was
        assert parts[0][0].islower()
        if len(parts) > 1:
            assert parts[1][0].islower()

    def test_case_preserving_uppercase(self):
        """Test case preservation with uppercase input."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname", case_preserving=True)
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("JOHN DOE")

        parts = result.split()
        # First character should be uppercase if original was
        assert parts[0][0].isupper()
        if len(parts) > 1:
            assert parts[1][0].isupper()

    def test_case_not_preserved(self):
        """Test disabling case preservation."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname", case_preserving=False)
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("john doe")

        parts = result.split()
        # First character should be uppercase regardless of input
        assert parts[0][0].isupper()


class TestInitialsFormat:
    """Tests for initials format."""

    def test_masks_to_initials(self):
        """Test masking converts to initials."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("John Doe")

        assert result == "J.D."

    def test_initials_single_name(self):
        """Test initials with single name."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("Madonna")

        assert result == "M."

    def test_initials_three_names(self):
        """Test initials with three names."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("Jean Claude Van")

        assert result == "J.C.V."

    def test_initials_always_uppercase(self):
        """Test initials are always uppercase."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("john doe")

        assert result == "J.D."
        assert result == result.upper()

    def test_initials_deterministic(self):
        """Test initials format is deterministic."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)

        result1 = strategy.anonymize("John Doe")
        result2 = strategy.anonymize("John Doe")

        assert result1 == result2 == "J.D."

    def test_initials_with_spaces(self):
        """Test handling extra whitespace in initials."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("  John   Doe  ")

        assert result == "J.D."

    def test_initials_empty_name(self):
        """Test initials with empty name."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("")

        assert result == ""


class TestRandomFormat:
    """Tests for random format."""

    def test_masks_to_random_string(self):
        """Test masking converts to random string."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("John Doe")

        # Result should be same length as input (minus spaces)
        assert len(result) == len("John Doe".strip())
        assert result != "John Doe"

    def test_random_preserves_length(self):
        """Test random format preserves input length."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)

        name = "Alexander"
        result = strategy.anonymize(name)

        assert len(result) == len(name)

    def test_random_deterministic(self):
        """Test random format is deterministic with same seed."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)

        result1 = strategy.anonymize("John Doe")
        result2 = strategy.anonymize("John Doe")

        assert result1 == result2

    def test_random_different_seed_different_output(self):
        """Test random format differs with different seed."""
        strategy1 = NameMaskingStrategy(NameMaskConfig(seed=12345, format_type="random"))
        strategy2 = NameMaskingStrategy(NameMaskConfig(seed=67890, format_type="random"))

        result1 = strategy1.anonymize("John Doe")
        result2 = strategy2.anonymize("John Doe")

        assert result1 != result2

    def test_random_uses_alphanumeric(self):
        """Test random format uses alphanumeric characters."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)
        result = strategy.anonymize("John Doe")

        # All characters should be alphanumeric
        assert all(c.isalnum() for c in result)

    def test_random_long_name(self):
        """Test random format with long name."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)
        name = "Aleksandr Maximilian Constantine"
        result = strategy.anonymize(name)

        assert len(result) == len(name.strip())


class TestShortName:
    """Tests for strategy short name."""

    def test_short_name_firstname_lastname(self):
        """Test short name for firstname_lastname format."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)
        assert strategy.short_name() == "name:firstname_lastname"

    def test_short_name_initials(self):
        """Test short name for initials format."""
        config = NameMaskConfig(seed=12345, format_type="initials")
        strategy = NameMaskingStrategy(config)
        assert strategy.short_name() == "name:initials"

    def test_short_name_random(self):
        """Test short name for random format."""
        config = NameMaskConfig(seed=12345, format_type="random")
        strategy = NameMaskingStrategy(config)
        assert strategy.short_name() == "name:random"


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_default_config(self):
        """Test default configuration."""
        config = NameMaskConfig()
        assert config.format_type == "firstname_lastname"
        assert config.preserve_initial is False
        assert config.case_preserving is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = NameMaskConfig(
            seed=12345,
            format_type="initials",
            preserve_initial=True,
            case_preserving=False,
        )
        assert config.seed == 12345
        assert config.format_type == "initials"
        assert config.preserve_initial is True
        assert config.case_preserving is False

    def test_invalid_format_raises_error(self):
        """Test invalid format type raises error."""
        config = NameMaskConfig(seed=12345, format_type="invalid_format")
        strategy = NameMaskingStrategy(config)

        with pytest.raises(ValueError, match="Unknown format_type"):
            strategy.anonymize("John Doe")


class TestComplexScenarios:
    """Tests for complex scenarios."""

    def test_multiple_names_consistent(self):
        """Test anonymizing multiple names with same seed is consistent."""
        config = NameMaskConfig(seed=12345, format_type="firstname_lastname")
        strategy = NameMaskingStrategy(config)

        names = ["John Doe", "Jane Smith", "Bob Johnson"]
        results1 = [strategy.anonymize(name) for name in names]
        results2 = [strategy.anonymize(name) for name in names]

        assert results1 == results2

    def test_all_formats_handle_same_name(self):
        """Test all formats can handle the same name."""
        name = "John Doe"

        for format_type in ["firstname_lastname", "initials", "random"]:
            config = NameMaskConfig(seed=12345, format_type=format_type)
            strategy = NameMaskingStrategy(config)
            result = strategy.anonymize(name)

            assert result is not None
            assert isinstance(result, str)

    def test_format_switching_deterministic(self):
        """Test each format produces consistent results regardless of order."""
        name = "John Doe"

        # First strategy with seed A uses format X
        config1 = NameMaskConfig(seed=12345, format_type="initials")
        strategy1 = NameMaskingStrategy(config1)
        result1 = strategy1.anonymize(name)

        # Second strategy with same seed A uses same format X
        config2 = NameMaskConfig(seed=12345, format_type="initials")
        strategy2 = NameMaskingStrategy(config2)
        result2 = strategy2.anonymize(name)

        assert result1 == result2
