"""Unit tests for anonymization strategies.

Tests cover:
    - Seed resolution (env var, hardcoded, default)
    - Deterministic hashing with HMAC
    - NULL handling
    - Empty string handling
    - Unicode handling
    - Type validation
"""

import os

import pytest

from confiture.core.anonymization.strategies.hash import (
    DeterministicHashConfig,
    DeterministicHashStrategy,
)
from confiture.core.anonymization.strategy import (
    StrategyConfig,
    resolve_seed,
)


class TestSeedResolution:
    """Test seed resolution from environment variables and config."""

    def test_seed_from_environment_variable(self):
        """Seed is loaded from environment variable."""
        os.environ["TEST_SEED"] = "54321"
        try:
            config = StrategyConfig(seed_env_var="TEST_SEED")
            assert resolve_seed(config) == 54321
        finally:
            del os.environ["TEST_SEED"]

    def test_seed_fallback_to_hardcoded(self):
        """Fallback to hardcoded seed if env var not set."""
        config = StrategyConfig(seed=99999, seed_env_var="NONEXISTENT_VAR")
        assert resolve_seed(config) == 99999

    def test_seed_default_zero(self):
        """Default seed is 0 if nothing provided."""
        config = StrategyConfig()
        assert resolve_seed(config) == 0

    def test_env_var_takes_precedence(self):
        """Environment variable takes precedence over hardcoded seed."""
        os.environ["PRIORITY_TEST"] = "11111"
        try:
            config = StrategyConfig(seed=22222, seed_env_var="PRIORITY_TEST")
            assert resolve_seed(config) == 11111  # Env var, not hardcoded
        finally:
            del os.environ["PRIORITY_TEST"]

    def test_invalid_env_var_raises_error(self):
        """Invalid integer in env var raises ValueError."""
        os.environ["BAD_SEED"] = "not_a_number"
        try:
            config = StrategyConfig(seed_env_var="BAD_SEED")
            with pytest.raises(ValueError, match="Invalid integer"):
                resolve_seed(config)
        finally:
            del os.environ["BAD_SEED"]

    def test_empty_env_var_falls_back(self):
        """Empty env var falls back to hardcoded seed."""
        os.environ["EMPTY_SEED"] = ""
        try:
            config = StrategyConfig(seed=77777, seed_env_var="EMPTY_SEED")
            assert resolve_seed(config) == 77777  # Empty env, use hardcoded
        finally:
            del os.environ["EMPTY_SEED"]


class TestDeterministicHashStrategy:
    """Test DeterministicHashStrategy (HMAC-based)."""

    def test_deterministic_hashing(self):
        """Same value + seed = same hash."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        hash1 = strategy.anonymize("test@example.com")
        hash2 = strategy.anonymize("test@example.com")

        assert hash1 == hash2  # Deterministic!
        assert hash1 is not None
        assert len(hash1) > 0

    def test_different_values_different_hashes(self):
        """Different values produce different hashes."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        hash1 = strategy.anonymize("alice@example.com")
        hash2 = strategy.anonymize("bob@example.com")

        assert hash1 != hash2

    def test_different_seeds_different_hashes(self):
        """Different seeds produce different hashes for same value."""
        config1 = DeterministicHashConfig(seed=11111)
        config2 = DeterministicHashConfig(seed=22222)

        strategy1 = DeterministicHashStrategy(config1)
        strategy2 = DeterministicHashStrategy(config2)

        value = "test@example.com"
        hash1 = strategy1.anonymize(value)
        hash2 = strategy2.anonymize(value)

        assert hash1 != hash2

    def test_null_handling(self):
        """NULL values return NULL."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        assert strategy.anonymize(None) is None

    def test_empty_string_handling(self):
        """Empty strings return empty strings."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("")
        assert result == ""

    def test_unicode_handling(self):
        """Unicode characters are handled correctly."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        # Test various unicode strings
        result1 = strategy.anonymize("école@example.com")  # French
        result2 = strategy.anonymize("北京@example.com")  # Chinese
        result3 = strategy.anonymize("🎉@example.com")  # Emoji

        # All should hash successfully
        assert result1 is not None
        assert result2 is not None
        assert result3 is not None

        # Same value should hash to same result (deterministic)
        assert strategy.anonymize("école@example.com") == result1

    def test_length_truncation(self):
        """Hash length can be truncated."""
        config = DeterministicHashConfig(seed=12345, length=8)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test@example.com")
        assert len(result) == 8

    def test_prefix_addition(self):
        """Optional prefix is added to hash."""
        config = DeterministicHashConfig(seed=12345, prefix="user_")
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test@example.com")
        assert result.startswith("user_")

    def test_prefix_and_length_combined(self):
        """Prefix and length work together."""
        config = DeterministicHashConfig(seed=12345, prefix="hash_", length=8)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test@example.com")
        assert result.startswith("hash_")
        assert len(result) == len("hash_") + 8  # prefix + truncated hash

    def test_algorithm_validation(self):
        """Invalid algorithm raises error."""
        config = DeterministicHashConfig(algorithm="invalid_algo")
        with pytest.raises(ValueError, match="must be one of"):
            DeterministicHashStrategy(config)

    def test_supported_algorithms(self):
        """SHA256, SHA1, MD5 are all supported."""
        for algo in ["sha256", "sha1", "md5"]:
            config = DeterministicHashConfig(seed=12345, algorithm=algo)
            strategy = DeterministicHashStrategy(config)

            result = strategy.anonymize("test")
            assert result is not None
            assert len(result) > 0

    def test_validate_accepts_any_type(self):
        """Validate method accepts any value type."""
        config = DeterministicHashConfig()
        strategy = DeterministicHashStrategy(config)

        assert strategy.validate("string") is True
        assert strategy.validate(12345) is True
        assert strategy.validate(None) is True
        assert strategy.validate(["list"]) is True
        assert strategy.validate({"key": "value"}) is True

    def test_integer_hashing(self):
        """Integers can be hashed."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        result1 = strategy.anonymize(12345)
        result2 = strategy.anonymize(12345)

        assert result1 == result2  # Deterministic
        assert isinstance(result1, str)

    def test_float_hashing(self):
        """Floats can be hashed."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        result1 = strategy.anonymize(3.14159)
        result2 = strategy.anonymize(3.14159)

        assert result1 == result2  # Deterministic
        assert isinstance(result1, str)

    def test_hmac_with_secret(self):
        """HMAC uses secret key for rainbow-table resistance."""
        os.environ["ANONYMIZATION_SECRET"] = "my-secret"
        try:
            config = DeterministicHashConfig(seed=12345)
            strategy = DeterministicHashStrategy(config)

            result1 = strategy.anonymize("test")

            # Change secret
            os.environ["ANONYMIZATION_SECRET"] = "different-secret"

            # Same seed, different secret = different hash
            result2 = strategy.anonymize("test")

            assert result1 != result2
        finally:
            if "ANONYMIZATION_SECRET" in os.environ:
                del os.environ["ANONYMIZATION_SECRET"]

    def test_strategy_name_short(self):
        """Strategy short name is correct."""
        config = DeterministicHashConfig()
        strategy = DeterministicHashStrategy(config)

        assert strategy.name_short() == "deterministichash"

    def test_strategy_repr(self):
        """String representation for debugging."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        repr_str = repr(strategy)
        assert "DeterministicHashStrategy" in repr_str
        assert "12345" in repr_str


class TestHashStrategyConfiguration:
    """Test DeterministicHashConfig validation."""

    def test_config_defaults(self):
        """Default configuration values."""
        config = DeterministicHashConfig()
        assert config.algorithm == "sha256"
        assert config.length is None
        assert config.prefix == ""
        assert config.seed is None
        assert config.seed_env_var is None

    def test_config_custom_values(self):
        """Custom configuration values."""
        config = DeterministicHashConfig(
            algorithm="sha1",
            length=16,
            prefix="hash_",
            seed=99999,
            seed_env_var="MY_SEED",
        )
        assert config.algorithm == "sha1"
        assert config.length == 16
        assert config.prefix == "hash_"
        assert config.seed == 99999
        assert config.seed_env_var == "MY_SEED"

    def test_invalid_algorithm_in_config(self):
        """Invalid algorithm in config raises error."""
        config = DeterministicHashConfig(algorithm="unknown")
        with pytest.raises(ValueError):
            config.validate_algorithm()
