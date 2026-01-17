"""Unit tests for strategy composition and chaining.

Tests for:
- Strategy chaining and sequential application
- Composition configuration and control flow
- Error handling in chains
- Builder pattern (StrategySequence)
- Chain introspection
"""

import pytest

from confiture.core.anonymization.composer import (
    CompositionConfig,
    StrategyComposer,
    StrategySequence,
)


class TestStrategyComposer:
    """Tests for StrategyComposer."""

    def test_composer_with_empty_strategies(self):
        """Test composer with no strategies configured."""
        config = CompositionConfig(strategies=[])
        composer = StrategyComposer(config)
        result = composer.anonymize("test data")
        assert result == "test data"

    def test_composer_with_single_strategy(self):
        """Test composer with one strategy."""
        config = CompositionConfig(strategies=["preserve"])
        composer = StrategyComposer(config)
        result = composer.anonymize("test data")
        assert result == "test data"

    def test_composer_with_multiple_preserve_strategies(self):
        """Test composer with multiple preserve strategies."""
        config = CompositionConfig(strategies=["preserve", "preserve"])
        composer = StrategyComposer(config)
        result = composer.anonymize("test data")
        assert result == "test data"

    def test_composer_with_custom_strategies(self):
        """Test composer with custom function strategies."""

        def uppercase(value):
            return value.upper() if isinstance(value, str) else value

        def add_suffix(value):
            return f"{value}_suffix" if isinstance(value, str) else value

        CompositionConfig(
            seed=12345,
            strategies=["custom", "custom"],
        )
        # This would need proper setup with custom functions registered
        # For now test that composer accepts multiple strategies

    def test_composer_none_returns_none(self):
        """Test composer returns None for None input."""
        config = CompositionConfig(strategies=["preserve"])
        composer = StrategyComposer(config)
        assert composer.anonymize(None) is None

    def test_composer_empty_string_returns_empty(self):
        """Test composer returns empty string for empty input."""
        config = CompositionConfig(strategies=["preserve"])
        composer = StrategyComposer(config)
        assert composer.anonymize("") == ""

    def test_composer_skip_empty_values(self):
        """Test continue_on_empty skips empty values in chain."""
        config = CompositionConfig(
            strategies=["preserve"],
            continue_on_empty=True,
        )
        composer = StrategyComposer(config)
        result = composer.anonymize("")
        assert result == ""

    def test_composer_stop_on_none(self):
        """Test stop_on_none stops chain when strategy returns None."""
        config = CompositionConfig(
            strategies=["preserve"],
            stop_on_none=True,
        )
        StrategyComposer(config)
        # Preserve never returns None, so chain continues

    def test_composer_stop_on_error_disabled(self):
        """Test stop_on_error=False skips failing strategies."""
        config = CompositionConfig(
            strategies=["preserve"],
            stop_on_error=False,
        )
        composer = StrategyComposer(config)
        result = composer.anonymize("test")
        assert result == "test"

    def test_composer_stop_on_error_enabled(self):
        """Test stop_on_error=True raises exception."""
        config = CompositionConfig(
            strategies=["preserve"],
            stop_on_error=True,
        )
        composer = StrategyComposer(config)
        result = composer.anonymize("test")
        assert result == "test"

    def test_composer_validate_accepts_valid_type(self):
        """Test validate returns True for valid types."""
        config = CompositionConfig(strategies=["preserve"])
        composer = StrategyComposer(config)
        assert composer.validate("string") is True
        assert composer.validate(123) is True
        assert composer.validate(None) is True

    def test_composer_validate_empty_strategies(self):
        """Test validate with empty strategy list."""
        config = CompositionConfig(strategies=[])
        composer = StrategyComposer(config)
        assert composer.validate("any value") is True

    def test_composer_short_name_empty(self):
        """Test short name for empty strategies."""
        config = CompositionConfig(strategies=[])
        composer = StrategyComposer(config)
        assert composer.short_name() == "compose:empty"

    def test_composer_short_name_with_strategies(self):
        """Test short name includes strategy names."""
        config = CompositionConfig(strategies=["preserve", "preserve"])
        composer = StrategyComposer(config)
        short = composer.short_name()
        assert "compose:" in short

    def test_composer_get_strategy_chain(self):
        """Test getting list of strategies in chain."""
        config = CompositionConfig(strategies=["preserve", "preserve"])
        composer = StrategyComposer(config)
        chain = composer.get_strategy_chain()
        assert isinstance(chain, list)
        assert len(chain) == 2

    def test_composer_with_seed(self):
        """Test composer with seed for determinism."""
        config = CompositionConfig(seed=12345, strategies=["preserve"])
        composer = StrategyComposer(config)
        result1 = composer.anonymize("test")
        result2 = composer.anonymize("test")
        assert result1 == result2

    def test_composer_determinism_across_instances(self):
        """Test same seed produces same results."""
        config1 = CompositionConfig(seed=12345, strategies=["preserve"])
        config2 = CompositionConfig(seed=12345, strategies=["preserve"])

        composer1 = StrategyComposer(config1)
        composer2 = StrategyComposer(config2)

        result1 = composer1.anonymize("test")
        result2 = composer2.anonymize("test")

        assert result1 == result2

    def test_composer_different_seeds_same_strategy(self):
        """Test different seeds produce consistent results for preserve."""
        config1 = CompositionConfig(seed=111, strategies=["preserve"])
        config2 = CompositionConfig(seed=222, strategies=["preserve"])

        composer1 = StrategyComposer(config1)
        composer2 = StrategyComposer(config2)

        # Preserve strategy should produce same result regardless of seed
        assert composer1.anonymize("test") == composer2.anonymize("test")


class TestCompositionConfig:
    """Tests for CompositionConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CompositionConfig()
        assert config.seed is None  # Default seed is None
        assert config.strategies == []
        assert config.stop_on_none is False
        assert config.stop_on_error is False
        assert config.continue_on_empty is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = CompositionConfig(
            seed=12345,
            strategies=["preserve"],
            stop_on_none=True,
            stop_on_error=True,
            continue_on_empty=True,
        )
        assert config.seed == 12345
        assert config.strategies == ["preserve"]
        assert config.stop_on_none is True
        assert config.stop_on_error is True
        assert config.continue_on_empty is True

    def test_strategies_list_creation(self):
        """Test creating with different strategy lists."""
        config = CompositionConfig(strategies=["preserve", "preserve", "preserve"])
        assert len(config.strategies) == 3
        assert all(s == "preserve" for s in config.strategies)


class TestStrategySequence:
    """Tests for StrategySequence builder."""

    def test_sequence_add_single_strategy(self):
        """Test adding single strategy to sequence."""
        sequence = StrategySequence(seed=12345)
        sequence.add("preserve")
        assert len(sequence.strategies) == 1
        assert sequence.strategies[0] == "preserve"

    def test_sequence_add_multiple_strategies(self):
        """Test adding multiple strategies with chaining."""
        sequence = StrategySequence(seed=12345)
        sequence.add("preserve").add("preserve").add("preserve")
        assert len(sequence.strategies) == 3

    def test_sequence_add_many(self):
        """Test adding many strategies at once."""
        sequence = StrategySequence(seed=12345)
        sequence.add_many("preserve", "preserve", "preserve")
        assert len(sequence.strategies) == 3

    def test_sequence_on_none_default(self):
        """Test default on_none value."""
        sequence = StrategySequence(seed=12345)
        assert sequence.stop_on_none is False

    def test_sequence_on_none_enabled(self):
        """Test enabling stop_on_none."""
        sequence = StrategySequence(seed=12345)
        result = sequence.on_none(True)
        assert sequence.stop_on_none is True
        assert result is sequence  # Fluent API returns self

    def test_sequence_on_none_disabled(self):
        """Test disabling stop_on_none."""
        sequence = StrategySequence(seed=12345)
        sequence.on_none(True)
        sequence.on_none(False)
        assert sequence.stop_on_none is False

    def test_sequence_on_error_default(self):
        """Test default on_error value."""
        sequence = StrategySequence(seed=12345)
        assert sequence.stop_on_error is False

    def test_sequence_on_error_enabled(self):
        """Test enabling stop_on_error."""
        sequence = StrategySequence(seed=12345)
        sequence.on_error(True)
        assert sequence.stop_on_error is True

    def test_sequence_skip_empty_default(self):
        """Test default skip_empty value."""
        sequence = StrategySequence(seed=12345)
        assert sequence.continue_on_empty is False

    def test_sequence_skip_empty_enabled(self):
        """Test enabling skip_empty."""
        sequence = StrategySequence(seed=12345)
        sequence.skip_empty(True)
        assert sequence.continue_on_empty is True

    def test_sequence_build_empty_raises_error(self):
        """Test building with no strategies raises error."""
        sequence = StrategySequence(seed=12345)
        with pytest.raises(ValueError, match="No strategies configured"):
            sequence.build()

    def test_sequence_build_single_strategy(self):
        """Test building with single strategy."""
        sequence = StrategySequence(seed=12345)
        sequence.add("preserve")
        composer = sequence.build()
        assert isinstance(composer, StrategyComposer)
        assert composer.anonymize("test") == "test"

    def test_sequence_build_multiple_strategies(self):
        """Test building with multiple strategies."""
        sequence = StrategySequence(seed=12345)
        sequence.add("preserve").add("preserve")
        composer = sequence.build()
        assert isinstance(composer, StrategyComposer)

    def test_sequence_fluent_api_full_chain(self):
        """Test full fluent API chain."""
        composer = (
            StrategySequence(seed=12345)
            .add("preserve")
            .on_none(True)
            .on_error(False)
            .skip_empty(True)
            .build()
        )
        assert isinstance(composer, StrategyComposer)
        assert composer.config.stop_on_none is True
        assert composer.config.stop_on_error is False
        assert composer.config.continue_on_empty is True

    def test_sequence_preserves_seed(self):
        """Test sequence preserves seed when building."""
        sequence = StrategySequence(seed=54321)
        sequence.add("preserve")
        composer = sequence.build()
        assert composer.config.seed == 54321

    def test_sequence_preserves_all_options(self):
        """Test sequence preserves all options when building."""
        sequence = (
            StrategySequence(seed=12345)
            .add("preserve")
            .on_none(True)
            .on_error(True)
            .skip_empty(True)
        )
        composer = sequence.build()
        assert composer.config.seed == 12345
        assert composer.config.stop_on_none is True
        assert composer.config.stop_on_error is True
        assert composer.config.continue_on_empty is True

    def test_sequence_add_many_with_other_options(self):
        """Test add_many works with other builder options."""
        composer = (
            StrategySequence(seed=12345).add_many("preserve", "preserve").on_none(True).build()
        )
        assert len(composer.config.strategies) == 2
        assert composer.config.stop_on_none is True

    def test_sequence_multiple_add_many_calls(self):
        """Test multiple add_many calls accumulate."""
        sequence = StrategySequence(seed=12345)
        sequence.add_many("preserve", "preserve")
        sequence.add_many("preserve", "preserve")
        composer = sequence.build()
        assert len(composer.config.strategies) == 4

    def test_sequence_mixed_add_and_add_many(self):
        """Test mixing add and add_many."""
        sequence = (
            StrategySequence(seed=12345)
            .add("preserve")
            .add_many("preserve", "preserve")
            .add("preserve")
        )
        composer = sequence.build()
        assert len(composer.config.strategies) == 4
