"""Comprehensive tests for custom anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.custom import (
    CustomConfig,
    CustomStrategy,
    CustomLambdaStrategy,
)


class TestCustomStrategy:
    """Tests for CustomStrategy class."""

    @pytest.fixture
    def uppercase_func(self):
        """Create a simple uppercase function."""
        def func(value):
            return value.upper() if isinstance(value, str) else value
        return func

    @pytest.fixture
    def hash_func(self):
        """Create a simple hash function."""
        def func(value):
            return f"hash_{hash(str(value)) % 10000}"
        return func

    @pytest.fixture
    def seeded_func(self):
        """Create a function that uses seed."""
        def func(value, seed):
            return f"{seed}_{value}"
        return func

    @pytest.fixture
    def strategy_uppercase(self, uppercase_func):
        """Create strategy with uppercase function."""
        config = CustomConfig(seed=12345, func=uppercase_func, name="uppercase")
        return CustomStrategy(config)

    @pytest.fixture
    def strategy_hash(self, hash_func):
        """Create strategy with hash function."""
        config = CustomConfig(seed=12345, func=hash_func, name="hash")
        return CustomStrategy(config)

    @pytest.fixture
    def strategy_seeded(self, seeded_func):
        """Create strategy with seeded function."""
        config = CustomConfig(
            seed=12345, func=seeded_func, name="seeded", accepts_seed=True
        )
        return CustomStrategy(config)

    # Basic anonymization tests
    def test_anonymize_uppercase(self, strategy_uppercase):
        """Test custom uppercase function."""
        result = strategy_uppercase.anonymize("test")
        assert result == "TEST"

    def test_anonymize_hash(self, strategy_hash):
        """Test custom hash function."""
        result = strategy_hash.anonymize("test")
        assert result.startswith("hash_")

    def test_anonymize_seeded(self, strategy_seeded):
        """Test custom function with seed."""
        result = strategy_seeded.anonymize("test")
        assert result == "12345_test"

    def test_anonymize_non_string(self, strategy_uppercase):
        """Test custom function with non-string value."""
        result = strategy_uppercase.anonymize(12345)
        assert result == 12345  # Unchanged because not a string

    # No function configured tests
    def test_no_func_raises_error(self):
        """Test missing function raises RuntimeError."""
        config = CustomConfig(seed=12345, func=None)
        strategy = CustomStrategy(config)

        with pytest.raises(RuntimeError, match="requires 'func' to be configured"):
            strategy.anonymize("test")

    # Function error tests
    def test_func_error_wrapped(self):
        """Test function errors are wrapped with context."""
        def error_func(value):
            raise ValueError("Test error")

        config = CustomConfig(seed=12345, func=error_func, name="error_func")
        strategy = CustomStrategy(config)

        with pytest.raises(Exception, match="Error in custom anonymization function"):
            strategy.anonymize("test")

    # Validate method tests
    def test_validate_always_true(self, strategy_uppercase):
        """Test validate always returns True."""
        assert strategy_uppercase.validate("string") is True
        assert strategy_uppercase.validate(12345) is True
        assert strategy_uppercase.validate(None) is True
        assert strategy_uppercase.validate([1, 2, 3]) is True

    # Short name tests
    def test_short_name(self, strategy_uppercase):
        """Test short name includes custom name."""
        assert strategy_uppercase.short_name() == "custom:uppercase"

    def test_short_name_hash(self, strategy_hash):
        """Test short name for hash function."""
        assert strategy_hash.short_name() == "custom:hash"

    # Strategy name and config type
    def test_strategy_name(self, strategy_uppercase):
        """Test strategy name is custom."""
        assert strategy_uppercase.strategy_name == "custom"

    def test_config_type(self, strategy_uppercase):
        """Test config type is CustomConfig."""
        assert strategy_uppercase.config_type == CustomConfig


class TestCustomLambdaStrategy:
    """Tests for CustomLambdaStrategy class."""

    @pytest.fixture
    def lambda_uppercase(self):
        """Create strategy with lambda function."""
        config = CustomConfig(
            seed=12345,
            func=lambda x: x.upper() if isinstance(x, str) else x,
            name="uppercase_lambda"
        )
        return CustomLambdaStrategy(config)

    @pytest.fixture
    def lambda_prefix(self):
        """Create strategy with prefix lambda."""
        config = CustomConfig(
            seed=12345,
            func=lambda x: f"anon_{x}",
            name="prefix"
        )
        return CustomLambdaStrategy(config)

    # Basic lambda tests
    def test_lambda_uppercase(self, lambda_uppercase):
        """Test lambda uppercase function."""
        result = lambda_uppercase.anonymize("test")
        assert result == "TEST"

    def test_lambda_prefix(self, lambda_prefix):
        """Test lambda prefix function."""
        result = lambda_prefix.anonymize("value")
        assert result == "anon_value"

    # No function configured tests
    def test_no_func_raises_error(self):
        """Test missing function raises RuntimeError."""
        config = CustomConfig(seed=12345, func=None)
        strategy = CustomLambdaStrategy(config)

        with pytest.raises(RuntimeError, match="requires 'func' to be configured"):
            strategy.anonymize("test")

    # Function error tests
    def test_lambda_error_wrapped(self):
        """Test lambda errors are wrapped."""
        config = CustomConfig(
            seed=12345,
            func=lambda x: x.upper(),  # Will fail on non-string
            name="error_lambda"
        )
        strategy = CustomLambdaStrategy(config)

        with pytest.raises(Exception, match="Error in lambda anonymization"):
            strategy.anonymize(12345)  # int has no .upper()

    # Validate method tests
    def test_validate_always_true(self, lambda_uppercase):
        """Test validate always returns True."""
        assert lambda_uppercase.validate("string") is True
        assert lambda_uppercase.validate(12345) is True
        assert lambda_uppercase.validate(None) is True

    # Short name tests
    def test_short_name(self, lambda_uppercase):
        """Test short name includes custom name."""
        assert lambda_uppercase.short_name() == "custom_lambda:uppercase_lambda"

    # Strategy name and config type
    def test_strategy_name(self, lambda_uppercase):
        """Test strategy name is custom_lambda."""
        assert lambda_uppercase.strategy_name == "custom_lambda"

    def test_config_type(self, lambda_uppercase):
        """Test config type is CustomConfig."""
        assert lambda_uppercase.config_type == CustomConfig


class TestCustomConfig:
    """Tests for CustomConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CustomConfig(seed=12345)
        assert config.func is None
        assert config.name == "custom"
        assert config.accepts_seed is False

    def test_custom_func(self):
        """Test custom function."""
        func = lambda x: x
        config = CustomConfig(seed=12345, func=func)
        assert config.func is func

    def test_custom_name(self):
        """Test custom name."""
        config = CustomConfig(seed=12345, name="my_function")
        assert config.name == "my_function"

    def test_accepts_seed_true(self):
        """Test accepts_seed True."""
        config = CustomConfig(seed=12345, accepts_seed=True)
        assert config.accepts_seed is True

    def test_all_custom_values(self):
        """Test all custom values together."""
        func = lambda x, seed: f"{seed}_{x}"
        config = CustomConfig(
            seed=12345,
            func=func,
            name="seeded_func",
            accepts_seed=True,
        )
        assert config.func is func
        assert config.name == "seeded_func"
        assert config.accepts_seed is True


class TestCustomEdgeCases:
    """Edge case tests for custom strategy."""

    def test_none_handling(self):
        """Test handling None value."""
        config = CustomConfig(
            seed=12345,
            func=lambda x: x if x is None else x.upper(),
            name="none_handler"
        )
        strategy = CustomStrategy(config)

        result = strategy.anonymize(None)
        assert result is None

    def test_complex_function(self):
        """Test complex multi-step function."""
        def complex_func(value):
            if value is None:
                return None
            if isinstance(value, str):
                # Reverse and uppercase
                return value[::-1].upper()
            return str(value)

        config = CustomConfig(seed=12345, func=complex_func, name="complex")
        strategy = CustomStrategy(config)

        assert strategy.anonymize("hello") == "OLLEH"
        assert strategy.anonymize(123) == "123"
        assert strategy.anonymize(None) is None

    def test_closure_function(self):
        """Test function with closure."""
        prefix = "anon"
        suffix = "_end"

        def closure_func(value):
            return f"{prefix}_{value}{suffix}"

        config = CustomConfig(seed=12345, func=closure_func, name="closure")
        strategy = CustomStrategy(config)

        result = strategy.anonymize("test")
        assert result == "anon_test_end"

    def test_seeded_determinism(self):
        """Test seeded function is deterministic."""
        import hashlib

        def seeded_hash(value, seed):
            return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()[:8]

        config = CustomConfig(
            seed=12345, func=seeded_hash, name="seeded_hash", accepts_seed=True
        )
        strategy = CustomStrategy(config)

        result1 = strategy.anonymize("test")
        result2 = strategy.anonymize("test")
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Test different seeds produce different results."""
        def seeded_func(value, seed):
            return f"{seed}_{value}"

        config1 = CustomConfig(
            seed=12345, func=seeded_func, name="seeded", accepts_seed=True
        )
        config2 = CustomConfig(
            seed=67890, func=seeded_func, name="seeded", accepts_seed=True
        )
        strategy1 = CustomStrategy(config1)
        strategy2 = CustomStrategy(config2)

        result1 = strategy1.anonymize("test")
        result2 = strategy2.anonymize("test")
        assert result1 != result2
        assert result1 == "12345_test"
        assert result2 == "67890_test"
