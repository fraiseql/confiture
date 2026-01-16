"""Comprehensive tests for salted hashing anonymization strategy.

Tests cover:
- SaltedHashingConfig configuration
- SaltedHashingStrategy initialization
- Hash algorithm validation
- Salt retrieval (env var, config, seed)
- HMAC vs plain hashing
- Truncation and prefix options
- Edge cases and error handling
"""

import os
import pytest
from unittest.mock import patch

from confiture.core.anonymization.strategies.salted_hashing import (
    SaltedHashingConfig,
    SaltedHashingStrategy,
)


class TestSaltedHashingConfig:
    """Tests for SaltedHashingConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SaltedHashingConfig()

        assert config.algorithm == "sha256"
        assert config.salt is None
        assert config.salt_env_var == "ANONYMIZATION_SALT"
        assert config.length is None
        assert config.prefix == ""
        assert config.use_hmac is True

    def test_custom_algorithm(self):
        """Test custom algorithm configuration."""
        config = SaltedHashingConfig(algorithm="sha512")
        assert config.algorithm == "sha512"

    def test_custom_salt(self):
        """Test custom static salt configuration."""
        config = SaltedHashingConfig(salt="my-secret-salt")
        assert config.salt == "my-secret-salt"

    def test_custom_salt_env_var(self):
        """Test custom salt environment variable."""
        config = SaltedHashingConfig(salt_env_var="MY_SALT_VAR")
        assert config.salt_env_var == "MY_SALT_VAR"

    def test_custom_length(self):
        """Test custom truncation length."""
        config = SaltedHashingConfig(length=16)
        assert config.length == 16

    def test_custom_prefix(self):
        """Test custom prefix."""
        config = SaltedHashingConfig(prefix="hash_")
        assert config.prefix == "hash_"

    def test_use_hmac_disabled(self):
        """Test disabling HMAC."""
        config = SaltedHashingConfig(use_hmac=False)
        assert config.use_hmac is False


class TestSaltedHashingStrategyInit:
    """Tests for SaltedHashingStrategy initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        strategy = SaltedHashingStrategy()

        assert strategy.config.algorithm == "sha256"
        assert strategy.config.use_hmac is True

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = SaltedHashingConfig(
            algorithm="sha512",
            salt="custom-salt",
            length=32,
            prefix="h_",
        )
        strategy = SaltedHashingStrategy(config)

        assert strategy.config.algorithm == "sha512"
        assert strategy.config.salt == "custom-salt"
        assert strategy.config.length == 32
        assert strategy.config.prefix == "h_"

    def test_init_invalid_algorithm(self):
        """Test error with invalid algorithm."""
        config = SaltedHashingConfig(algorithm="invalid")

        with pytest.raises(ValueError, match="Algorithm must be one of"):
            SaltedHashingStrategy(config)

    def test_init_sha1_algorithm(self):
        """Test SHA1 algorithm is valid."""
        config = SaltedHashingConfig(algorithm="sha1")
        strategy = SaltedHashingStrategy(config)

        assert strategy.config.algorithm == "sha1"

    def test_init_blake2b_algorithm(self):
        """Test blake2b algorithm is valid."""
        config = SaltedHashingConfig(algorithm="blake2b")
        strategy = SaltedHashingStrategy(config)

        assert strategy.config.algorithm == "blake2b"

    def test_init_md5_algorithm(self):
        """Test MD5 algorithm is valid (for legacy compatibility)."""
        config = SaltedHashingConfig(algorithm="md5")
        strategy = SaltedHashingStrategy(config)

        assert strategy.config.algorithm == "md5"


class TestSaltedHashingStrategyAnonymize:
    """Tests for SaltedHashingStrategy.anonymize() method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with custom seed."""
        config = SaltedHashingConfig(seed=12345)
        return SaltedHashingStrategy(config)

    def test_anonymize_none_returns_none(self, strategy):
        """Test None input returns None."""
        result = strategy.anonymize(None)
        assert result is None

    def test_anonymize_empty_string_returns_empty(self, strategy):
        """Test empty string returns empty string."""
        result = strategy.anonymize("")
        assert result == ""

    def test_anonymize_returns_hash(self, strategy):
        """Test anonymization returns hash string."""
        result = strategy.anonymize("test@example.com")

        assert isinstance(result, str)
        # SHA256 hex is 64 characters
        assert len(result) == 64

    def test_anonymize_deterministic(self, strategy):
        """Test same input produces same output."""
        result1 = strategy.anonymize("test@example.com")
        result2 = strategy.anonymize("test@example.com")

        assert result1 == result2

    def test_anonymize_different_inputs_different_outputs(self, strategy):
        """Test different inputs produce different outputs."""
        result1 = strategy.anonymize("test1@example.com")
        result2 = strategy.anonymize("test2@example.com")

        assert result1 != result2

    def test_anonymize_integer_value(self, strategy):
        """Test hashing integer value."""
        result = strategy.anonymize(12345)

        assert isinstance(result, str)
        assert len(result) == 64

    def test_anonymize_float_value(self, strategy):
        """Test hashing float value."""
        result = strategy.anonymize(123.45)

        assert isinstance(result, str)


class TestSaltedHashingTruncation:
    """Tests for hash truncation."""

    def test_truncation_16_chars(self):
        """Test truncation to 16 characters."""
        config = SaltedHashingConfig(length=16, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 16

    def test_truncation_8_chars(self):
        """Test truncation to 8 characters."""
        config = SaltedHashingConfig(length=8, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 8

    def test_truncation_32_chars(self):
        """Test truncation to 32 characters."""
        config = SaltedHashingConfig(length=32, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 32

    def test_no_truncation(self):
        """Test without truncation (full hash)."""
        config = SaltedHashingConfig(length=None, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        # SHA256 = 64 hex chars
        assert len(result) == 64


class TestSaltedHashingPrefix:
    """Tests for hash prefix."""

    def test_prefix_added(self):
        """Test prefix is added to hash."""
        config = SaltedHashingConfig(prefix="hash_", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert result.startswith("hash_")

    def test_prefix_with_truncation(self):
        """Test prefix with truncation."""
        config = SaltedHashingConfig(prefix="h_", length=16, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        # Prefix (2) + truncated hash (16) = 18
        assert result.startswith("h_")
        assert len(result) == 18

    def test_empty_prefix(self):
        """Test empty prefix."""
        config = SaltedHashingConfig(prefix="", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        # No prefix, just hash
        assert len(result) == 64


class TestSaltedHashingSaltRetrieval:
    """Tests for salt retrieval logic."""

    def test_salt_from_env_var(self):
        """Test salt from environment variable."""
        with patch.dict(os.environ, {"ANONYMIZATION_SALT": "env-salt-value"}):
            config = SaltedHashingConfig(seed=12345)
            strategy = SaltedHashingStrategy(config)

            salt = strategy._get_salt()

            assert salt == "env-salt-value"

    def test_salt_from_config_when_no_env(self):
        """Test salt from config when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            config = SaltedHashingConfig(salt="config-salt", salt_env_var="", seed=12345)
            strategy = SaltedHashingStrategy(config)

            salt = strategy._get_salt()

            assert salt == "config-salt"

    def test_salt_from_seed_as_fallback(self):
        """Test salt falls back to seed."""
        # Ensure no env var or config salt
        with patch.dict(os.environ, {}, clear=True):
            config = SaltedHashingConfig(
                salt=None,
                salt_env_var="NONEXISTENT_VAR",
                seed=99999,
            )
            strategy = SaltedHashingStrategy(config)

            salt = strategy._get_salt()

            assert salt == "99999"

    def test_env_var_takes_precedence(self):
        """Test env var takes precedence over config salt."""
        with patch.dict(os.environ, {"MY_SALT": "from-env"}):
            config = SaltedHashingConfig(
                salt="from-config",
                salt_env_var="MY_SALT",
                seed=12345,
            )
            strategy = SaltedHashingStrategy(config)

            salt = strategy._get_salt()

            assert salt == "from-env"


class TestSaltedHashingHMAC:
    """Tests for HMAC vs plain hashing."""

    def test_hmac_produces_different_hash(self):
        """Test HMAC and plain hash produce different results."""
        config_hmac = SaltedHashingConfig(use_hmac=True, seed=12345)
        config_plain = SaltedHashingConfig(use_hmac=False, seed=12345)

        strategy_hmac = SaltedHashingStrategy(config_hmac)
        strategy_plain = SaltedHashingStrategy(config_plain)

        result_hmac = strategy_hmac.anonymize("test")
        result_plain = strategy_plain.anonymize("test")

        assert result_hmac != result_plain

    def test_hmac_deterministic(self):
        """Test HMAC hashing is deterministic."""
        config = SaltedHashingConfig(use_hmac=True, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result1 = strategy.anonymize("test")
        result2 = strategy.anonymize("test")

        assert result1 == result2

    def test_plain_hash_deterministic(self):
        """Test plain hashing is deterministic."""
        config = SaltedHashingConfig(use_hmac=False, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result1 = strategy.anonymize("test")
        result2 = strategy.anonymize("test")

        assert result1 == result2


class TestSaltedHashingAlgorithms:
    """Tests for different hash algorithms."""

    def test_sha256_hash_length(self):
        """Test SHA256 produces 64 hex chars."""
        config = SaltedHashingConfig(algorithm="sha256", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 64

    def test_sha512_hash_length(self):
        """Test SHA512 produces 128 hex chars."""
        config = SaltedHashingConfig(algorithm="sha512", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 128

    def test_sha1_hash_length(self):
        """Test SHA1 produces 40 hex chars."""
        config = SaltedHashingConfig(algorithm="sha1", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 40

    def test_md5_hash_length(self):
        """Test MD5 produces 32 hex chars."""
        config = SaltedHashingConfig(algorithm="md5", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 32

    def test_blake2b_hash_length(self):
        """Test blake2b produces 128 hex chars."""
        config = SaltedHashingConfig(algorithm="blake2b", seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("test")

        assert len(result) == 128


class TestSaltedHashingValidation:
    """Tests for validation methods."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for validation tests."""
        return SaltedHashingStrategy()

    def test_validate_string(self, strategy):
        """Test validate accepts string."""
        assert strategy.validate("hello") is True

    def test_validate_int(self, strategy):
        """Test validate accepts int."""
        assert strategy.validate(12345) is True

    def test_validate_float(self, strategy):
        """Test validate accepts float."""
        assert strategy.validate(123.45) is True

    def test_validate_comprehensive_valid_with_salt(self):
        """Test comprehensive validation with salt configured."""
        config = SaltedHashingConfig(salt="test-salt", seed=12345)
        strategy = SaltedHashingStrategy(config)

        is_valid, errors = strategy.validate_comprehensive("test", "email", "users")

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_comprehensive_no_salt_warning(self):
        """Test comprehensive validation warns when no salt configured."""
        with patch.dict(os.environ, {}, clear=True):
            config = SaltedHashingConfig(salt=None, salt_env_var="NONEXISTENT", seed=12345)
            strategy = SaltedHashingStrategy(config)

            is_valid, errors = strategy.validate_comprehensive("test", "email", "users")

            assert is_valid is False
            assert "No salt configured" in errors[0]

    def test_validate_comprehensive_empty_string_warning(self):
        """Test comprehensive validation warns about empty string."""
        config = SaltedHashingConfig(salt="test-salt", seed=12345)
        strategy = SaltedHashingStrategy(config)

        is_valid, errors = strategy.validate_comprehensive("", "email", "users")

        # Should warn about empty string
        assert len(errors) > 0


class TestSaltedHashingProperties:
    """Tests for strategy properties."""

    def test_is_reversible_false(self):
        """Test salted hashing is not reversible."""
        strategy = SaltedHashingStrategy()

        assert strategy.is_reversible is False


class TestSaltedHashingEdgeCases:
    """Tests for edge cases."""

    def test_hash_unicode_string(self):
        """Test hashing unicode string."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("héllo wörld")

        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_long_string(self):
        """Test hashing very long string."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        long_string = "x" * 10000
        result = strategy.anonymize(long_string)

        assert isinstance(result, str)
        assert len(result) == 64  # Hash is always same length

    def test_hash_special_characters(self):
        """Test hashing string with special characters."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy.anonymize("!@#$%^&*()_+-=[]{}|;':\",./<>?")

        assert isinstance(result, str)

    def test_hash_whitespace(self):
        """Test hashing whitespace strings."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        # Non-empty whitespace should hash
        result = strategy.anonymize("   ")

        assert isinstance(result, str)
        assert len(result) == 64

    def test_different_seeds_different_hashes(self):
        """Test different seeds produce different hashes."""
        config1 = SaltedHashingConfig(seed=12345)
        config2 = SaltedHashingConfig(seed=67890)

        strategy1 = SaltedHashingStrategy(config1)
        strategy2 = SaltedHashingStrategy(config2)

        result1 = strategy1.anonymize("test")
        result2 = strategy2.anonymize("test")

        assert result1 != result2

    def test_hash_consistent_across_sessions(self):
        """Test hash is consistent with same config."""
        config = SaltedHashingConfig(salt="fixed-salt", seed=12345)

        strategy1 = SaltedHashingStrategy(config)
        result1 = strategy1.anonymize("test@example.com")

        strategy2 = SaltedHashingStrategy(config)
        result2 = strategy2.anonymize("test@example.com")

        assert result1 == result2


class TestComputeHash:
    """Tests for _compute_hash method."""

    def test_compute_hash_hmac(self):
        """Test _compute_hash with HMAC."""
        config = SaltedHashingConfig(use_hmac=True, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy._compute_hash("test", "salt")

        assert isinstance(result, str)
        assert len(result) == 64

    def test_compute_hash_plain(self):
        """Test _compute_hash without HMAC."""
        config = SaltedHashingConfig(use_hmac=False, seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy._compute_hash("test", "salt")

        assert isinstance(result, str)
        assert len(result) == 64

    def test_compute_hash_different_salts(self):
        """Test _compute_hash with different salts."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        result1 = strategy._compute_hash("test", "salt1")
        result2 = strategy._compute_hash("test", "salt2")

        assert result1 != result2

    def test_compute_hash_empty_salt(self):
        """Test _compute_hash with empty salt."""
        config = SaltedHashingConfig(seed=12345)
        strategy = SaltedHashingStrategy(config)

        result = strategy._compute_hash("test", "")

        assert isinstance(result, str)
