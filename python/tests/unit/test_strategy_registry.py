"""Unit tests for strategy registry system.

Tests:
- Registration of strategies
- Retrieval by name
- Type validation
- Duplicate registration prevention
- Listing available strategies
- Decorator-based registration
- Configuration conversion
"""

import pytest
from confiture.core.anonymization.registry import (
    StrategyRegistry,
    register_strategy,
)
from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


class DummyStrategy(AnonymizationStrategy):
    """Dummy strategy for testing."""

    config_type = StrategyConfig
    strategy_name = "dummy"

    def anonymize(self, value: str) -> str:
        """Return value as-is."""
        if value is None:
            return None
        return value

    def validate(self, value: str) -> bool:
        """Validate that value is a string."""
        return isinstance(value, str) or value is None


class InvalidStrategy:
    """Invalid strategy (doesn't inherit from AnonymizationStrategy)."""

    pass


class TestStrategyRegistration:
    """Tests for strategy registration."""

    def setup_method(self):
        """Clear registry before each test."""
        StrategyRegistry.reset()

    def test_register_valid_strategy(self):
        """Test registering a valid strategy."""
        StrategyRegistry.register("dummy", DummyStrategy)
        assert StrategyRegistry.is_registered("dummy")

    def test_register_invalid_strategy_type(self):
        """Test registering an invalid strategy raises TypeError."""
        with pytest.raises(TypeError, match="must inherit from AnonymizationStrategy"):
            StrategyRegistry.register("invalid", InvalidStrategy)

    def test_register_duplicate_name(self):
        """Test registering duplicate name raises ValueError."""
        StrategyRegistry.register("dummy", DummyStrategy)
        with pytest.raises(ValueError, match="already registered"):
            StrategyRegistry.register("dummy", DummyStrategy)

    def test_register_multiple_strategies(self):
        """Test registering multiple different strategies."""
        StrategyRegistry.register("dummy1", DummyStrategy)
        StrategyRegistry.register("dummy2", DummyStrategy)
        assert StrategyRegistry.count() == 2

    def test_unregister_strategy(self):
        """Test unregistering a strategy."""
        StrategyRegistry.register("dummy", DummyStrategy)
        StrategyRegistry.unregister("dummy")
        assert not StrategyRegistry.is_registered("dummy")

    def test_unregister_nonexistent_strategy(self):
        """Test unregistering nonexistent strategy raises ValueError."""
        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry.unregister("nonexistent")

    def test_reset_registry(self):
        """Test resetting registry clears all strategies."""
        StrategyRegistry.register("dummy1", DummyStrategy)
        StrategyRegistry.register("dummy2", DummyStrategy)
        StrategyRegistry.reset()
        assert StrategyRegistry.count() == 0


class TestStrategyRetrieval:
    """Tests for retrieving strategies."""

    def setup_method(self):
        """Clear registry before each test."""
        StrategyRegistry.reset()
        StrategyRegistry.register("dummy", DummyStrategy)

    def test_get_strategy_by_name(self):
        """Test getting strategy instance by name."""
        strategy = StrategyRegistry.get("dummy")
        assert isinstance(strategy, DummyStrategy)

    def test_get_with_dict_config(self):
        """Test getting strategy with dict configuration."""
        config_dict = {"seed": 12345}
        strategy = StrategyRegistry.get("dummy", config_dict)
        assert strategy.config.seed == 12345

    def test_get_with_config_object(self):
        """Test getting strategy with StrategyConfig object."""
        config = StrategyConfig(seed=12345)
        strategy = StrategyRegistry.get("dummy", config)
        assert strategy.config.seed == 12345

    def test_get_with_none_config(self):
        """Test getting strategy with None config creates default."""
        strategy = StrategyRegistry.get("dummy", None)
        assert isinstance(strategy, DummyStrategy)

    def test_get_nonexistent_strategy(self):
        """Test getting nonexistent strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            StrategyRegistry.get("nonexistent")

    def test_get_nonexistent_shows_available(self):
        """Test error message includes available strategies."""
        StrategyRegistry.register("other", DummyStrategy)
        with pytest.raises(ValueError, match="Available:.*dummy.*other"):
            StrategyRegistry.get("nonexistent")

    def test_get_strategy_class(self):
        """Test getting strategy class (not instance)."""
        strategy_class = StrategyRegistry.get_strategy_class("dummy")
        assert strategy_class is DummyStrategy

    def test_get_strategy_class_nonexistent(self):
        """Test getting nonexistent strategy class raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            StrategyRegistry.get_strategy_class("nonexistent")


class TestStrategyListing:
    """Tests for listing available strategies."""

    def setup_method(self):
        """Clear registry before each test."""
        StrategyRegistry.reset()

    def test_list_available_empty(self):
        """Test listing when registry is empty."""
        assert StrategyRegistry.list_available() == []

    def test_list_available_sorted(self):
        """Test listing returns sorted strategy names."""
        StrategyRegistry.register("zebra", DummyStrategy)
        StrategyRegistry.register("apple", DummyStrategy)
        StrategyRegistry.register("banana", DummyStrategy)
        assert StrategyRegistry.list_available() == ["apple", "banana", "zebra"]

    def test_count_empty(self):
        """Test counting strategies when empty."""
        assert StrategyRegistry.count() == 0

    def test_count_multiple(self):
        """Test counting multiple registered strategies."""
        StrategyRegistry.register("dummy1", DummyStrategy)
        StrategyRegistry.register("dummy2", DummyStrategy)
        StrategyRegistry.register("dummy3", DummyStrategy)
        assert StrategyRegistry.count() == 3


class TestDecoratorRegistration:
    """Tests for @register_strategy decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        StrategyRegistry.reset()

    def test_decorator_registers_strategy(self):
        """Test decorator automatically registers strategy."""

        @register_strategy("decorated")
        class DecoratedStrategy(AnonymizationStrategy):
            config_type = StrategyConfig
            strategy_name = "decorated"

            def anonymize(self, value: str) -> str:
                return value

            def validate(self, value: str) -> bool:
                return isinstance(value, str) or value is None

        assert StrategyRegistry.is_registered("decorated")
        strategy = StrategyRegistry.get("decorated")
        assert isinstance(strategy, DecoratedStrategy)

    def test_decorator_returns_class(self):
        """Test decorator returns the original class."""

        @register_strategy("decorated")
        class DecoratedStrategy(AnonymizationStrategy):
            config_type = StrategyConfig
            strategy_name = "decorated"

            def anonymize(self, value: str) -> str:
                return value

            def validate(self, value: str) -> bool:
                return isinstance(value, str) or value is None

        # Can still use the class directly
        instance = DecoratedStrategy(StrategyConfig())
        assert isinstance(instance, AnonymizationStrategy)


class TestStrategyInstantiation:
    """Tests for strategy instantiation."""

    def setup_method(self):
        """Clear registry before each test."""
        StrategyRegistry.reset()
        StrategyRegistry.register("dummy", DummyStrategy)

    def test_instantiated_strategy_works(self):
        """Test getting and using strategy works end-to-end."""
        strategy = StrategyRegistry.get("dummy", {"seed": 12345})
        result = strategy.anonymize("test")
        assert result == "test"

    def test_instantiated_strategy_deterministic(self):
        """Test same config produces same instance behavior."""
        config = {"seed": 12345}
        strategy1 = StrategyRegistry.get("dummy", config)
        strategy2 = StrategyRegistry.get("dummy", config)

        result1 = strategy1.anonymize("test")
        result2 = strategy2.anonymize("test")

        assert result1 == result2 == "test"

    def test_different_config_same_behavior(self):
        """Test strategy returns same value regardless of config for dummy."""
        strategy1 = StrategyRegistry.get("dummy", {"seed": 12345})
        strategy2 = StrategyRegistry.get("dummy", {"seed": 67890})

        # Dummy strategy always returns value as-is
        assert strategy1.anonymize("test") == "test"
        assert strategy2.anonymize("test") == "test"
