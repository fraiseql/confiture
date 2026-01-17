"""Comprehensive tests for strategy composition system.

Tests the StrategyComposer and StrategySequence classes for chaining
multiple anonymization strategies sequentially.
"""

from unittest.mock import Mock, patch

import pytest

from confiture.core.anonymization.composer import (
    CompositionConfig,
    StrategyComposer,
    StrategySequence,
)
from confiture.core.anonymization.registry import StrategyRegistry
from confiture.core.anonymization.strategy import AnonymizationStrategy


class TestCompositionConfig:
    """Test CompositionConfig dataclass."""

    def test_default_config(self):
        """Test default composition config initialization."""
        config = CompositionConfig()
        assert config.strategies == []
        assert config.stop_on_none is False
        assert config.stop_on_error is False
        assert config.continue_on_empty is False

    def test_custom_config(self):
        """Test custom composition config."""
        config = CompositionConfig(
            seed=42,
            strategies=["name", "email"],
            stop_on_none=True,
            stop_on_error=True,
            continue_on_empty=True,
        )
        assert config.seed == 42
        assert config.strategies == ["name", "email"]
        assert config.stop_on_none is True
        assert config.stop_on_error is True
        assert config.continue_on_empty is True


class TestStrategyComposerInitialization:
    """Test StrategyComposer initialization."""

    def test_init_with_default_config(self):
        """Test composer initialization with default config."""
        composer = StrategyComposer()
        assert composer.config.strategies == []
        assert composer._strategies == []

    def test_init_with_custom_config(self):
        """Test composer initialization with custom config."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            config = CompositionConfig(
                strategies=["preserve"],
                seed=42,
            )
            composer = StrategyComposer(config)
            assert composer.config == config
            assert composer.config.seed == 42

    def test_init_loads_strategies(self):
        """Test that init loads strategies from registry."""
        with patch.object(StrategyRegistry, 'get') as mock_get:
            mock_strategy = Mock(spec=AnonymizationStrategy)
            mock_get.return_value = mock_strategy

            config = CompositionConfig(strategies=["preserve"])
            composer = StrategyComposer(config)

            assert len(composer._strategies) == 1
            assert composer._strategies[0][0] == mock_strategy


class TestStrategyComposerAnonymize:
    """Test StrategyComposer.anonymize method."""

    def test_anonymize_none_value(self):
        """Test that None values return None."""
        composer = StrategyComposer()
        result = composer.anonymize(None)
        assert result is None

    def test_anonymize_empty_strategies(self):
        """Test anonymize with no strategies loaded."""
        composer = StrategyComposer()
        result = composer.anonymize("test value")
        assert result == "test value"

    def test_anonymize_single_strategy(self):
        """Test anonymize with single strategy in chain."""
        config = CompositionConfig(strategies=["test"])

        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.anonymize.return_value = "anonymized"

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            assert result == "anonymized"
            mock_strategy.anonymize.assert_called_once_with("original")

    def test_anonymize_multiple_strategies(self):
        """Test anonymize with chain of strategies."""
        config = CompositionConfig(strategies=["first", "second"])

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.return_value = "first_result"

        mock_second = Mock(spec=AnonymizationStrategy)
        mock_second.anonymize.return_value = "second_result"

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            assert result == "second_result"
            mock_first.anonymize.assert_called_once_with("original")
            mock_second.anonymize.assert_called_once_with("first_result")

    def test_anonymize_stop_on_none_enabled(self):
        """Test stop_on_none stops chain when strategy returns None."""
        config = CompositionConfig(
            strategies=["first", "second"],
            stop_on_none=True,
        )

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.return_value = None

        mock_second = Mock(spec=AnonymizationStrategy)

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            assert result is None
            mock_first.anonymize.assert_called_once()
            mock_second.anonymize.assert_not_called()

    def test_anonymize_stop_on_none_disabled(self):
        """Test that chain continues when stop_on_none is False."""
        config = CompositionConfig(
            strategies=["first", "second"],
            stop_on_none=False,
        )

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.return_value = None

        mock_second = Mock(spec=AnonymizationStrategy)
        mock_second.anonymize.return_value = "result"

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            assert result == "result"

    def test_anonymize_continue_on_empty_enabled(self):
        """Test continue_on_empty skips empty strings and None."""
        config = CompositionConfig(
            strategies=["first", "second"],
            continue_on_empty=True,
        )

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.return_value = ""

        mock_second = Mock(spec=AnonymizationStrategy)
        mock_second.anonymize.return_value = "result"

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            # First strategy applied, returns empty string
            # Second strategy skipped due to empty result (continue_on_empty=True)
            assert result == ""
            mock_first.anonymize.assert_called_once()
            # Second strategy should not be called
            mock_second.anonymize.assert_not_called()

    def test_anonymize_stop_on_error_enabled(self):
        """Test stop_on_error raises exception when strategy fails."""
        config = CompositionConfig(
            strategies=["first", "second"],
            stop_on_error=True,
        )

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.side_effect = ValueError("Strategy error")

        def get_strategy(name, config):
            return mock_first

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)

            with pytest.raises(Exception, match="Error in strategy 'first'"):
                composer.anonymize("original")

    def test_anonymize_stop_on_error_disabled(self):
        """Test that chain continues when stop_on_error is False."""
        config = CompositionConfig(
            strategies=["first", "second"],
            stop_on_error=False,
        )

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.anonymize.side_effect = ValueError("Strategy error")

        mock_second = Mock(spec=AnonymizationStrategy)
        mock_second.anonymize.return_value = "result"

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("original")

            # First strategy skipped due to error, second applies
            assert result == "result"


class TestStrategyComposerValidate:
    """Test StrategyComposer.validate method."""

    def test_validate_no_strategies(self):
        """Test validate returns True when no strategies loaded."""
        composer = StrategyComposer()
        assert composer.validate("test") is True

    def test_validate_any_strategy_accepts(self):
        """Test validate returns True if any strategy accepts value."""
        config = CompositionConfig(strategies=["first", "second"])

        mock_first = Mock(spec=AnonymizationStrategy)
        mock_first.validate.return_value = False

        mock_second = Mock(spec=AnonymizationStrategy)
        mock_second.validate.return_value = True

        def get_strategy(name, config):
            if name == "first":
                return mock_first
            return mock_second

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            assert composer.validate("test") is True

    def test_validate_no_strategy_accepts(self):
        """Test validate returns False when no strategy accepts value."""
        config = CompositionConfig(strategies=["first", "second"])

        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.validate.return_value = False

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = StrategyComposer(config)
            assert composer.validate("test") is False


class TestStrategyComposerHelpers:
    """Test StrategyComposer helper methods."""

    def test_short_name_empty(self):
        """Test short_name with no strategies."""
        composer = StrategyComposer()
        assert composer.short_name() == "compose:empty"

    def test_short_name_single_strategy(self):
        """Test short_name with single strategy."""
        config = CompositionConfig(strategies=["name"])

        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = StrategyComposer(config)
            assert "compose:" in composer.short_name()
            assert "name" in composer.short_name()

    def test_short_name_multiple_strategies(self):
        """Test short_name with multiple strategies."""
        config = CompositionConfig(strategies=["name", "email", "phone", "address"])

        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = StrategyComposer(config)
            short_name = composer.short_name()
            assert "compose:" in short_name
            # Should truncate to first 3 strategies
            assert "name" in short_name or "email" in short_name

    def test_get_strategy_chain(self):
        """Test get_strategy_chain returns strategy names."""
        config = CompositionConfig(strategies=["name", "email"])

        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = StrategyComposer(config)
            chain = composer.get_strategy_chain()
            assert chain == ["name", "email"]


class TestStrategyComposerStrategyLoading:
    """Test StrategyComposer._load_strategies method."""

    def test_load_strategies_string_spec(self):
        """Test loading strategy from string specification."""
        config = CompositionConfig(strategies=["name"])

        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy) as mock_get:
            composer = StrategyComposer(config)

            mock_get.assert_called()
            assert len(composer._strategies) == 1

    def test_load_strategies_with_config_suffix(self):
        """Test loading strategy with config suffix (e.g., 'name:firstname_lastname')."""
        config = CompositionConfig(strategies=["name:firstname_lastname"])

        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy) as mock_get:
            StrategyComposer(config)

            # Should extract base name 'name' and pass to registry
            mock_get.assert_called()
            call_args = mock_get.call_args
            assert call_args[0][0] == "name"

    def test_load_strategies_invalid_strategy(self):
        """Test that invalid strategy raises ValueError."""
        config = CompositionConfig(strategies=["invalid_strategy"])

        with patch.object(StrategyRegistry, 'get', side_effect=ValueError("Not found")):
            with pytest.raises(ValueError, match="Failed to load strategy"):
                StrategyComposer(config)

    def test_load_strategies_dict_config_not_supported(self):
        """Test that dict config raises ValueError (not yet supported)."""
        config = CompositionConfig(strategies=[{"type": "name"}])

        with pytest.raises(ValueError, match="Failed to load strategy"):
            StrategyComposer(config)


class TestStrategySequence:
    """Test StrategySequence builder class."""

    def test_init_default(self):
        """Test StrategySequence default initialization."""
        seq = StrategySequence()
        assert seq.seed == 0
        assert seq.strategies == []
        assert seq.stop_on_none is False
        assert seq.stop_on_error is False
        assert seq.continue_on_empty is False

    def test_init_with_seed(self):
        """Test StrategySequence initialization with seed."""
        seq = StrategySequence(seed=42)
        assert seq.seed == 42

    def test_add_single_strategy(self):
        """Test adding single strategy."""
        seq = StrategySequence()
        result = seq.add("name")
        assert result is seq  # Should return self for chaining
        assert seq.strategies == ["name"]

    def test_add_multiple_calls(self):
        """Test adding multiple strategies via multiple calls."""
        seq = StrategySequence()
        seq.add("name").add("email").add("phone")
        assert seq.strategies == ["name", "email", "phone"]

    def test_add_many(self):
        """Test adding multiple strategies at once."""
        seq = StrategySequence()
        result = seq.add_many("name", "email", "phone")
        assert result is seq  # Should return self for chaining
        assert seq.strategies == ["name", "email", "phone"]

    def test_on_none_true(self):
        """Test on_none configuration."""
        seq = StrategySequence().on_none(True)
        assert seq.stop_on_none is True

    def test_on_none_false(self):
        """Test on_none(False) configuration."""
        seq = StrategySequence().on_none(False)
        assert seq.stop_on_none is False

    def test_on_error_true(self):
        """Test on_error configuration."""
        seq = StrategySequence().on_error(True)
        assert seq.stop_on_error is True

    def test_on_error_false(self):
        """Test on_error(False) configuration."""
        seq = StrategySequence().on_error(False)
        assert seq.stop_on_error is False

    def test_skip_empty_true(self):
        """Test skip_empty(True) configuration."""
        seq = StrategySequence().skip_empty(True)
        assert seq.continue_on_empty is True

    def test_skip_empty_false(self):
        """Test skip_empty(False) configuration."""
        seq = StrategySequence().skip_empty(False)
        assert seq.continue_on_empty is False

    def test_fluent_chaining(self):
        """Test fluent API chaining."""
        seq = (
            StrategySequence(seed=42)
            .add("name")
            .add_many("email", "phone")
            .on_none(True)
            .on_error(False)
            .skip_empty(True)
        )
        assert seq.seed == 42
        assert seq.strategies == ["name", "email", "phone"]
        assert seq.stop_on_none is True
        assert seq.stop_on_error is False
        assert seq.continue_on_empty is True

    def test_build_empty_raises_error(self):
        """Test that build with no strategies raises ValueError."""
        seq = StrategySequence()
        with pytest.raises(ValueError, match="No strategies configured"):
            seq.build()

    def test_build_creates_composer(self):
        """Test that build creates StrategyComposer."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            seq = StrategySequence(seed=42).add("name")
            composer = seq.build()

            assert isinstance(composer, StrategyComposer)
            assert composer.config.seed == 42
            assert composer.config.strategies == ["name"]

    def test_build_preserves_configuration(self):
        """Test that build preserves all sequence configuration."""
        mock_strategy = Mock(spec=AnonymizationStrategy)

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            seq = (
                StrategySequence(seed=99)
                .add_many("name", "email")
                .on_none(True)
                .on_error(True)
                .skip_empty(True)
            )
            composer = seq.build()

            assert composer.config.seed == 99
            assert composer.config.strategies == ["name", "email"]
            assert composer.config.stop_on_none is True
            assert composer.config.stop_on_error is True
            assert composer.config.continue_on_empty is True


class TestStrategyComposerIntegration:
    """Integration tests for StrategyComposer."""

    def test_composer_with_sequence_builder(self):
        """Test creating composer via StrategySequence builder."""
        mock_strategy = Mock(spec=AnonymizationStrategy)
        mock_strategy.anonymize.side_effect = lambda x: f"anonymized_{x}"

        with patch.object(StrategyRegistry, 'get', return_value=mock_strategy):
            composer = (
                StrategySequence(seed=42)
                .add("name")
                .build()
            )

            result = composer.anonymize("John")
            assert "anonymized_" in result

    def test_complex_chain_scenario(self):
        """Test complex scenario with multiple strategies."""
        config = CompositionConfig(
            seed=42,
            strategies=["mask", "hash", "preserve"],
            stop_on_none=False,
            stop_on_error=False,
            continue_on_empty=False,
        )

        strategies = []
        for i in range(3):
            mock_strategy = Mock(spec=AnonymizationStrategy)
            mock_strategy.anonymize.side_effect = lambda x, i=i: f"step{i}_{x}"
            mock_strategy.validate.return_value = True
            strategies.append(mock_strategy)

        call_count = [0]

        def get_strategy(name, config):
            result = strategies[call_count[0]]
            call_count[0] += 1
            return result

        with patch.object(StrategyRegistry, 'get', side_effect=get_strategy):
            composer = StrategyComposer(config)
            result = composer.anonymize("data")

            # Should have applied all strategies
            assert "step" in result
