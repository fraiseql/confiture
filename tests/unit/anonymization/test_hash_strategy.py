"""Comprehensive tests for deterministic hash anonymization strategy."""

import pytest

from confiture.core.anonymization.strategies.hash import (
    DeterministicHashConfig,
    DeterministicHashStrategy,
)


class TestDeterministicHashStrategy:
    """Tests for DeterministicHashStrategy class."""

    @pytest.fixture
    def strategy_default(self):
        """Create strategy with default config."""
        config = DeterministicHashConfig(seed=12345)
        return DeterministicHashStrategy(config)

    @pytest.fixture
    def strategy_sha1(self):
        """Create strategy with SHA1 algorithm."""
        config = DeterministicHashConfig(seed=12345, algorithm="sha1")
        return DeterministicHashStrategy(config)

    @pytest.fixture
    def strategy_md5(self):
        """Create strategy with MD5 algorithm."""
        config = DeterministicHashConfig(seed=12345, algorithm="md5")
        return DeterministicHashStrategy(config)

    @pytest.fixture
    def strategy_truncated(self):
        """Create strategy with truncation."""
        config = DeterministicHashConfig(seed=12345, length=16)
        return DeterministicHashStrategy(config)

    @pytest.fixture
    def strategy_prefixed(self):
        """Create strategy with prefix."""
        config = DeterministicHashConfig(seed=12345, prefix="hash_")
        return DeterministicHashStrategy(config)

    # Basic hashing tests
    def test_hash_basic_string(self, strategy_default):
        """Test basic string hashing."""
        result = strategy_default.anonymize("test")
        assert result != "test"
        assert isinstance(result, str)
        # SHA256 produces 64 hex characters
        assert len(result) == 64

    def test_hash_deterministic(self, strategy_default):
        """Test same input gives same output."""
        value = "test"
        result1 = strategy_default.anonymize(value)
        result2 = strategy_default.anonymize(value)
        assert result1 == result2

    def test_hash_different_seeds(self):
        """Test different seeds give different outputs."""
        config1 = DeterministicHashConfig(seed=12345)
        config2 = DeterministicHashConfig(seed=67890)
        strategy1 = DeterministicHashStrategy(config1)
        strategy2 = DeterministicHashStrategy(config2)

        value = "test"
        result1 = strategy1.anonymize(value)
        result2 = strategy2.anonymize(value)
        assert result1 != result2

    def test_hash_different_values_different_outputs(self, strategy_default):
        """Test different values produce different outputs."""
        result1 = strategy_default.anonymize("test1")
        result2 = strategy_default.anonymize("test2")
        assert result1 != result2

    # Algorithm tests
    def test_sha256_algorithm(self, strategy_default):
        """Test SHA256 produces 64 char hash."""
        result = strategy_default.anonymize("test")
        assert len(result) == 64

    def test_sha1_algorithm(self, strategy_sha1):
        """Test SHA1 produces 40 char hash."""
        result = strategy_sha1.anonymize("test")
        assert len(result) == 40

    def test_md5_algorithm(self, strategy_md5):
        """Test MD5 produces 32 char hash."""
        result = strategy_md5.anonymize("test")
        assert len(result) == 32

    def test_invalid_algorithm_raises(self):
        """Test invalid algorithm raises ValueError."""
        config = DeterministicHashConfig(seed=12345, algorithm="invalid")
        with pytest.raises(ValueError, match="Algorithm must be one of"):
            DeterministicHashStrategy(config)

    # Truncation tests
    def test_truncation(self, strategy_truncated):
        """Test hash is truncated to specified length."""
        result = strategy_truncated.anonymize("test")
        assert len(result) == 16

    def test_truncation_deterministic(self, strategy_truncated):
        """Test truncated hash is still deterministic."""
        result1 = strategy_truncated.anonymize("test")
        result2 = strategy_truncated.anonymize("test")
        assert result1 == result2

    def test_no_truncation(self, strategy_default):
        """Test full hash when no truncation."""
        result = strategy_default.anonymize("test")
        # SHA256 full length
        assert len(result) == 64

    # Prefix tests
    def test_prefix(self, strategy_prefixed):
        """Test prefix is applied."""
        result = strategy_prefixed.anonymize("test")
        assert result.startswith("hash_")

    def test_prefix_deterministic(self, strategy_prefixed):
        """Test prefixed hash is deterministic."""
        result1 = strategy_prefixed.anonymize("test")
        result2 = strategy_prefixed.anonymize("test")
        assert result1 == result2

    def test_prefix_and_truncation(self):
        """Test both prefix and truncation."""
        config = DeterministicHashConfig(seed=12345, prefix="h_", length=8)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test")
        assert result.startswith("h_")
        # h_ (2 chars) + 8 char hash = 10 total
        assert len(result) == 10

    # Edge cases
    def test_hash_none_returns_none(self, strategy_default):
        """Test None input returns None."""
        assert strategy_default.anonymize(None) is None

    def test_hash_empty_string(self, strategy_default):
        """Test empty string returns empty string."""
        assert strategy_default.anonymize("") == ""

    def test_hash_integer(self, strategy_default):
        """Test integer is converted and hashed."""
        result = strategy_default.anonymize(12345)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_float(self, strategy_default):
        """Test float is converted and hashed."""
        result = strategy_default.anonymize(123.45)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_list(self, strategy_default):
        """Test list is converted and hashed."""
        result = strategy_default.anonymize([1, 2, 3])
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_dict(self, strategy_default):
        """Test dict is converted and hashed."""
        result = strategy_default.anonymize({"key": "value"})
        assert isinstance(result, str)
        assert len(result) == 64

    # Validate method tests
    def test_validate_always_true(self, strategy_default):
        """Test validate always returns True."""
        assert strategy_default.validate("string") is True
        assert strategy_default.validate(12345) is True
        assert strategy_default.validate(None) is True
        assert strategy_default.validate([1, 2, 3]) is True
        assert strategy_default.validate({"key": "value"}) is True

    # Default config test
    def test_default_config(self):
        """Test strategy works with default config."""
        strategy = DeterministicHashStrategy()
        result = strategy.anonymize("test")
        assert isinstance(result, str)
        assert len(result) == 64


class TestDeterministicHashConfig:
    """Tests for DeterministicHashConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DeterministicHashConfig(seed=12345)
        assert config.algorithm == "sha256"
        assert config.length is None
        assert config.prefix == ""

    def test_custom_algorithm(self):
        """Test custom algorithm."""
        config = DeterministicHashConfig(seed=12345, algorithm="sha1")
        assert config.algorithm == "sha1"

    def test_custom_length(self):
        """Test custom length."""
        config = DeterministicHashConfig(seed=12345, length=16)
        assert config.length == 16

    def test_custom_prefix(self):
        """Test custom prefix."""
        config = DeterministicHashConfig(seed=12345, prefix="hash_")
        assert config.prefix == "hash_"

    def test_all_custom_values(self):
        """Test all custom values together."""
        config = DeterministicHashConfig(
            seed=12345,
            algorithm="md5",
            length=8,
            prefix="h_",
        )
        assert config.algorithm == "md5"
        assert config.length == 8
        assert config.prefix == "h_"

    def test_validate_algorithm_sha256(self):
        """Test validate_algorithm accepts sha256."""
        config = DeterministicHashConfig(seed=12345, algorithm="sha256")
        config.validate_algorithm()  # Should not raise

    def test_validate_algorithm_sha1(self):
        """Test validate_algorithm accepts sha1."""
        config = DeterministicHashConfig(seed=12345, algorithm="sha1")
        config.validate_algorithm()  # Should not raise

    def test_validate_algorithm_md5(self):
        """Test validate_algorithm accepts md5."""
        config = DeterministicHashConfig(seed=12345, algorithm="md5")
        config.validate_algorithm()  # Should not raise

    def test_validate_algorithm_invalid(self):
        """Test validate_algorithm rejects invalid."""
        config = DeterministicHashConfig(seed=12345, algorithm="invalid")
        with pytest.raises(ValueError):
            config.validate_algorithm()


class TestHashEdgeCases:
    """Edge case tests for hash anonymization."""

    def test_hash_uniqueness(self):
        """Test hash uniqueness for similar values."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        # Very similar values should produce different hashes
        result1 = strategy.anonymize("test1")
        result2 = strategy.anonymize("test2")
        assert result1 != result2

    def test_hash_consistency_across_instances(self):
        """Test hash consistency across strategy instances."""
        config = DeterministicHashConfig(seed=12345)
        strategy1 = DeterministicHashStrategy(config)
        strategy2 = DeterministicHashStrategy(config)

        result1 = strategy1.anonymize("test")
        result2 = strategy2.anonymize("test")
        assert result1 == result2

    def test_hash_unicode(self):
        """Test hashing unicode strings."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("日本語テスト")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_long_string(self):
        """Test hashing very long string."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        long_string = "a" * 10000
        result = strategy.anonymize(long_string)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_is_hex(self):
        """Test hash output is valid hexadecimal."""
        config = DeterministicHashConfig(seed=12345)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test")
        # Should be valid hex
        int(result, 16)  # Should not raise

    def test_truncation_longer_than_hash(self):
        """Test truncation longer than hash length."""
        config = DeterministicHashConfig(seed=12345, algorithm="md5", length=100)
        strategy = DeterministicHashStrategy(config)

        result = strategy.anonymize("test")
        # MD5 is only 32 chars, so truncation to 100 gives full 32
        assert len(result) == 32
