"""Comprehensive tests for preserve (no-op) anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.preserve import (
    PreserveConfig,
    PreserveStrategy,
)


class TestPreserveStrategy:
    """Tests for PreserveStrategy class."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with default config."""
        config = PreserveConfig(seed=12345)
        return PreserveStrategy(config)

    # Basic preserve tests
    def test_preserve_string(self, strategy):
        """Test preserving a string."""
        result = strategy.anonymize("test@example.com")
        assert result == "test@example.com"

    def test_preserve_integer(self, strategy):
        """Test preserving an integer."""
        result = strategy.anonymize(12345)
        assert result == 12345

    def test_preserve_float(self, strategy):
        """Test preserving a float."""
        result = strategy.anonymize(123.45)
        assert result == 123.45

    def test_preserve_boolean_true(self, strategy):
        """Test preserving True."""
        result = strategy.anonymize(True)
        assert result is True

    def test_preserve_boolean_false(self, strategy):
        """Test preserving False."""
        result = strategy.anonymize(False)
        assert result is False

    def test_preserve_list(self, strategy):
        """Test preserving a list."""
        original = [1, 2, 3]
        result = strategy.anonymize(original)
        assert result == [1, 2, 3]
        assert result is original  # Same object

    def test_preserve_dict(self, strategy):
        """Test preserving a dict."""
        original = {"key": "value"}
        result = strategy.anonymize(original)
        assert result == {"key": "value"}
        assert result is original  # Same object

    def test_preserve_tuple(self, strategy):
        """Test preserving a tuple."""
        original = (1, 2, 3)
        result = strategy.anonymize(original)
        assert result == (1, 2, 3)
        assert result is original

    # None handling tests
    def test_preserve_none(self, strategy):
        """Test preserving None."""
        result = strategy.anonymize(None)
        assert result is None

    # Empty value tests
    def test_preserve_empty_string(self, strategy):
        """Test preserving empty string."""
        result = strategy.anonymize("")
        assert result == ""

    def test_preserve_empty_list(self, strategy):
        """Test preserving empty list."""
        result = strategy.anonymize([])
        assert result == []

    def test_preserve_empty_dict(self, strategy):
        """Test preserving empty dict."""
        result = strategy.anonymize({})
        assert result == {}

    # Validate method tests
    def test_validate_always_true(self, strategy):
        """Test validate always returns True."""
        assert strategy.validate("string") is True
        assert strategy.validate(12345) is True
        assert strategy.validate(None) is True
        assert strategy.validate([1, 2, 3]) is True
        assert strategy.validate({"key": "value"}) is True
        assert strategy.validate(True) is True

    # Short name test
    def test_short_name(self, strategy):
        """Test short name is 'preserve'."""
        assert strategy.short_name() == "preserve"

    # Strategy name and config type
    def test_strategy_name(self, strategy):
        """Test strategy name is preserve."""
        assert strategy.strategy_name == "preserve"

    def test_config_type(self, strategy):
        """Test config type is PreserveConfig."""
        assert strategy.config_type == PreserveConfig

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        config = PreserveConfig()
        strategy = PreserveStrategy(config)
        result = strategy.anonymize("test")
        assert result == "test"

    # Identity operation tests
    def test_is_identity_operation(self, strategy):
        """Test preserve is a true identity operation."""
        values = ["string", 123, 123.45, True, None, [1, 2], {"a": 1}]
        for value in values:
            result = strategy.anonymize(value)
            if value is not None and not isinstance(value, (int, float, bool, str)):
                # For mutable objects, should be same object
                assert result is value
            else:
                # For immutable objects, should be equal
                assert result == value

    def test_multiple_calls_same_result(self, strategy):
        """Test multiple calls return same result."""
        original = "test data"
        result1 = strategy.anonymize(original)
        result2 = strategy.anonymize(original)
        assert result1 == result2 == original


class TestPreserveConfig:
    """Tests for PreserveConfig dataclass."""

    def test_default_values(self):
        """Test PreserveConfig has no extra fields."""
        config = PreserveConfig(seed=12345)
        assert config.seed == 12345

    def test_config_inheritance(self):
        """Test PreserveConfig inherits from StrategyConfig."""
        from confiture.core.anonymization.strategy import StrategyConfig

        config = PreserveConfig(seed=12345)
        assert isinstance(config, StrategyConfig)


class TestPreserveEdgeCases:
    """Edge case tests for preserve strategy."""

    def test_seed_does_not_affect_output(self):
        """Test seed has no effect on preserve output."""
        config1 = PreserveConfig(seed=12345)
        config2 = PreserveConfig(seed=67890)
        strategy1 = PreserveStrategy(config1)
        strategy2 = PreserveStrategy(config2)

        value = "test"
        result1 = strategy1.anonymize(value)
        result2 = strategy2.anonymize(value)
        assert result1 == result2 == value

    def test_special_characters(self):
        """Test preserving special characters."""
        config = PreserveConfig(seed=12345)
        strategy = PreserveStrategy(config)

        special_values = [
            "test\n",
            "test\t",
            "test\r\n",
            "<script>alert('xss')</script>",
            "'; DROP TABLE users;--",
            "日本語テスト",
        ]

        for value in special_values:
            result = strategy.anonymize(value)
            assert result == value

    def test_nested_structures(self):
        """Test preserving nested data structures."""
        config = PreserveConfig(seed=12345)
        strategy = PreserveStrategy(config)

        nested = {"level1": {"level2": {"level3": [1, 2, 3]}}}

        result = strategy.anonymize(nested)
        assert result == nested
        assert result is nested  # Same object reference

    def test_callable(self):
        """Test preserving a callable."""
        config = PreserveConfig(seed=12345)
        strategy = PreserveStrategy(config)

        def my_func():
            return "test"

        result = strategy.anonymize(my_func)
        assert result is my_func
        assert result() == "test"

    def test_class_instance(self):
        """Test preserving a class instance."""
        config = PreserveConfig(seed=12345)
        strategy = PreserveStrategy(config)

        class MyClass:
            def __init__(self, value):
                self.value = value

        obj = MyClass("test")
        result = strategy.anonymize(obj)
        assert result is obj
        assert result.value == "test"
