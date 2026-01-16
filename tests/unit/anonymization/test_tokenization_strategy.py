"""Comprehensive tests for tokenization anonymization strategy.

Tests cover:
- TokenizationConfig configuration
- TokenizationStrategy initialization
- Token generation
- Token reversal with RBAC
- Validation methods
- Edge cases and error handling
"""

import pytest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass

from confiture.core.anonymization.strategies.tokenization import (
    TokenizationConfig,
    TokenizationStrategy,
)


class TestTokenizationConfig:
    """Tests for TokenizationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TokenizationConfig()

        assert config.token_prefix == "TOKEN_"
        assert config.token_length == 16
        assert config.hash_algorithm == "sha256"
        assert config.separator == "_"
        assert config.allow_reversals is True
        assert config.reversal_requires_reason is True

    def test_custom_token_prefix(self):
        """Test custom token prefix."""
        config = TokenizationConfig(token_prefix="TOK_")
        assert config.token_prefix == "TOK_"

    def test_custom_token_length(self):
        """Test custom token length."""
        config = TokenizationConfig(token_length=32)
        assert config.token_length == 32

    def test_custom_hash_algorithm(self):
        """Test custom hash algorithm."""
        config = TokenizationConfig(hash_algorithm="sha512")
        assert config.hash_algorithm == "sha512"

    def test_custom_separator(self):
        """Test custom separator."""
        config = TokenizationConfig(separator="-")
        assert config.separator == "-"

    def test_allow_reversals_disabled(self):
        """Test disabling reversals."""
        config = TokenizationConfig(allow_reversals=False)
        assert config.allow_reversals is False

    def test_reversal_requires_reason_disabled(self):
        """Test disabling reason requirement."""
        config = TokenizationConfig(reversal_requires_reason=False)
        assert config.reversal_requires_reason is False


class TestTokenizationStrategyInit:
    """Tests for TokenizationStrategy initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        strategy = TokenizationStrategy()

        assert strategy.config.token_prefix == "TOKEN_"
        assert strategy.token_store is None
        assert strategy.column_name == ""
        assert strategy.is_reversible is True
        assert strategy.requires_kms is True

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = TokenizationConfig(
            token_prefix="TK_",
            token_length=8,
            seed=12345,
        )
        strategy = TokenizationStrategy(config)

        assert strategy.config.token_prefix == "TK_"
        assert strategy.config.token_length == 8

    def test_init_with_token_store(self):
        """Test initialization with token store."""
        mock_store = Mock()
        strategy = TokenizationStrategy(token_store=mock_store)

        assert strategy.token_store is mock_store

    def test_init_with_column_name(self):
        """Test initialization with column name."""
        strategy = TokenizationStrategy(column_name="email")

        assert strategy.column_name == "email"


class TestTokenizationStrategyAnonymize:
    """Tests for TokenizationStrategy.anonymize() method."""

    @pytest.fixture
    def mock_store(self):
        """Create mock token store."""
        return Mock()

    @pytest.fixture
    def strategy(self, mock_store):
        """Create strategy with mock store."""
        config = TokenizationConfig(seed=12345)
        return TokenizationStrategy(config, token_store=mock_store)

    def test_anonymize_requires_token_store(self):
        """Test anonymize raises error when no token store."""
        strategy = TokenizationStrategy()  # No store

        with pytest.raises(ValueError, match="requires token_store"):
            strategy.anonymize("test@example.com")

    def test_anonymize_none_returns_none(self, strategy):
        """Test None input returns None."""
        result = strategy.anonymize(None)
        assert result is None

    def test_anonymize_empty_string_returns_empty(self, strategy):
        """Test empty string returns empty string."""
        result = strategy.anonymize("")
        assert result == ""

    def test_anonymize_whitespace_only_returns_empty(self, strategy):
        """Test whitespace-only returns empty string."""
        result = strategy.anonymize("   ")
        assert result == ""

    def test_anonymize_returns_token(self, strategy):
        """Test anonymization returns token with prefix."""
        result = strategy.anonymize("test@example.com")

        assert result.startswith("TOKEN_")

    def test_anonymize_token_correct_length(self, strategy):
        """Test token has correct length."""
        result = strategy.anonymize("test@example.com")

        # PREFIX (6) + hash (16) = 22
        expected_length = len("TOKEN_") + 16
        assert len(result) == expected_length

    def test_anonymize_calls_store_token(self, strategy, mock_store):
        """Test anonymize stores token in token store."""
        strategy.anonymize("test@example.com")

        mock_store.store_token.assert_called_once()
        call_kwargs = mock_store.store_token.call_args.kwargs
        assert call_kwargs["original_value"] == "test@example.com"
        assert call_kwargs["token"].startswith("TOKEN_")

    def test_anonymize_deterministic(self, mock_store):
        """Test same input produces same token."""
        config = TokenizationConfig(seed=12345)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        token1 = strategy.anonymize("test@example.com")
        token2 = strategy.anonymize("test@example.com")

        assert token1 == token2

    def test_anonymize_different_inputs_different_tokens(self, mock_store):
        """Test different inputs produce different tokens."""
        config = TokenizationConfig(seed=12345)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        token1 = strategy.anonymize("test1@example.com")
        token2 = strategy.anonymize("test2@example.com")

        assert token1 != token2

    def test_anonymize_different_seeds_different_tokens(self, mock_store):
        """Test different seeds produce different tokens."""
        config1 = TokenizationConfig(seed=12345)
        config2 = TokenizationConfig(seed=67890)

        strategy1 = TokenizationStrategy(config1, token_store=mock_store)
        strategy2 = TokenizationStrategy(config2, token_store=mock_store)

        token1 = strategy1.anonymize("test@example.com")
        token2 = strategy2.anonymize("test@example.com")

        assert token1 != token2

    def test_anonymize_integer_value(self, strategy):
        """Test tokenizing integer value."""
        result = strategy.anonymize(12345)

        assert result.startswith("TOKEN_")

    def test_anonymize_stores_column_name(self, strategy, mock_store):
        """Test column name is passed to store."""
        strategy.column_name = "email"
        strategy.anonymize("test@example.com")

        call_kwargs = mock_store.store_token.call_args.kwargs
        assert call_kwargs["column_name"] == "email"


class TestTokenizationStrategyReverseToken:
    """Tests for TokenizationStrategy.reverse_token() method."""

    @pytest.fixture
    def mock_store(self):
        """Create mock token store with reversal capability."""
        store = Mock()
        # Create a mock result for reverse_token
        mock_result = Mock()
        mock_result.original_value = "original@example.com"
        store.reverse_token.return_value = mock_result
        return store

    @pytest.fixture
    def strategy(self, mock_store):
        """Create strategy with mock store."""
        config = TokenizationConfig(seed=12345, allow_reversals=True)
        return TokenizationStrategy(config, token_store=mock_store)

    def test_reverse_token_requires_token_store(self):
        """Test reverse_token raises error when no token store."""
        strategy = TokenizationStrategy()  # No store

        with pytest.raises(ValueError, match="requires token_store"):
            strategy.reverse_token("TOKEN_abc", "admin", "reason")

    def test_reverse_token_not_allowed(self, mock_store):
        """Test reverse_token raises error when reversals disabled."""
        config = TokenizationConfig(allow_reversals=False)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        with pytest.raises(PermissionError, match="not allowed"):
            strategy.reverse_token("TOKEN_abc", "admin", "reason")

    def test_reverse_token_returns_original(self, strategy):
        """Test reverse_token returns original value."""
        result = strategy.reverse_token(
            "TOKEN_abc123",
            requester_id="admin@example.com",
            reason="Customer support",
        )

        assert result == "original@example.com"

    def test_reverse_token_calls_store(self, strategy, mock_store):
        """Test reverse_token calls token store."""
        strategy.reverse_token(
            "TOKEN_abc123",
            requester_id="admin@example.com",
            reason="Customer support",
        )

        mock_store.reverse_token.assert_called_once()

    def test_reverse_token_passes_request(self, strategy, mock_store):
        """Test reverse_token passes request object to store."""
        strategy.reverse_token(
            "TOKEN_abc123",
            requester_id="admin@example.com",
            reason="Customer support",
        )

        call_args = mock_store.reverse_token.call_args
        request = call_args[0][0]  # First positional arg

        assert request.token == "TOKEN_abc123"
        assert request.requester_id == "admin@example.com"
        assert request.reason == "Customer support"

    def test_reverse_token_without_reason(self, strategy, mock_store):
        """Test reverse_token with no reason."""
        strategy.reverse_token(
            "TOKEN_abc123",
            requester_id="admin@example.com",
            reason=None,
        )

        call_args = mock_store.reverse_token.call_args
        request = call_args[0][0]
        assert request.reason is None


class TestTokenGenerationMethod:
    """Tests for _generate_token method."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for token generation tests."""
        config = TokenizationConfig(seed=12345)
        mock_store = Mock()
        return TokenizationStrategy(config, token_store=mock_store)

    def test_generate_token_has_prefix(self, strategy):
        """Test generated token has prefix."""
        token = strategy._generate_token("test")

        assert token.startswith("TOKEN_")

    def test_generate_token_correct_length(self, strategy):
        """Test generated token has correct length."""
        token = strategy._generate_token("test")

        # PREFIX (6) + hash portion (16)
        assert len(token) == 22

    def test_generate_token_deterministic(self, strategy):
        """Test token generation is deterministic."""
        token1 = strategy._generate_token("test")
        token2 = strategy._generate_token("test")

        assert token1 == token2

    def test_generate_token_different_inputs(self, strategy):
        """Test different inputs produce different tokens."""
        token1 = strategy._generate_token("test1")
        token2 = strategy._generate_token("test2")

        assert token1 != token2

    def test_generate_token_custom_prefix(self):
        """Test custom token prefix in generation."""
        config = TokenizationConfig(token_prefix="TK_", seed=12345)
        mock_store = Mock()
        strategy = TokenizationStrategy(config, token_store=mock_store)

        token = strategy._generate_token("test")

        assert token.startswith("TK_")

    def test_generate_token_custom_length(self):
        """Test custom token length in generation."""
        config = TokenizationConfig(token_length=8, seed=12345)
        mock_store = Mock()
        strategy = TokenizationStrategy(config, token_store=mock_store)

        token = strategy._generate_token("test")

        # PREFIX (6) + hash (8) = 14
        assert len(token) == 14


class TestTokenizationValidation:
    """Tests for validation methods."""

    @pytest.fixture
    def strategy(self):
        """Create strategy for validation tests."""
        return TokenizationStrategy()

    def test_validate_string(self, strategy):
        """Test validate accepts string."""
        assert strategy.validate("hello") is True

    def test_validate_int(self, strategy):
        """Test validate accepts int."""
        assert strategy.validate(12345) is True

    def test_validate_float(self, strategy):
        """Test validate accepts float."""
        assert strategy.validate(123.45) is True

    def test_validate_comprehensive_valid_with_store(self):
        """Test comprehensive validation with token store."""
        mock_store = Mock()
        strategy = TokenizationStrategy(token_store=mock_store)

        is_valid, errors = strategy.validate_comprehensive("test", "email", "users")

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_comprehensive_no_token_store(self):
        """Test comprehensive validation without token store."""
        strategy = TokenizationStrategy()  # No store

        is_valid, errors = strategy.validate_comprehensive("test", "email", "users")

        assert is_valid is False
        assert "requires token_store" in errors[0]

    def test_validate_comprehensive_empty_string(self):
        """Test comprehensive validation with empty string."""
        mock_store = Mock()
        strategy = TokenizationStrategy(token_store=mock_store)

        is_valid, errors = strategy.validate_comprehensive("", "email", "users")

        assert is_valid is False
        assert "Empty string" in errors[0]

    def test_validate_comprehensive_whitespace_only(self):
        """Test comprehensive validation with whitespace only."""
        mock_store = Mock()
        strategy = TokenizationStrategy(token_store=mock_store)

        is_valid, errors = strategy.validate_comprehensive("   ", "email", "users")

        assert is_valid is False
        assert "Empty string" in errors[0]


class TestTokenizationProperties:
    """Tests for strategy properties."""

    def test_is_reversible_true(self):
        """Test tokenization is reversible."""
        strategy = TokenizationStrategy()

        assert strategy.is_reversible is True

    def test_requires_kms_true(self):
        """Test tokenization requires KMS."""
        strategy = TokenizationStrategy()

        assert strategy.requires_kms is True


class TestTokenizationEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def strategy(self):
        """Create strategy with mock store."""
        mock_store = Mock()
        config = TokenizationConfig(seed=12345)
        return TokenizationStrategy(config, token_store=mock_store)

    def test_tokenize_single_char(self, strategy):
        """Test tokenizing single character."""
        result = strategy.anonymize("x")

        assert result.startswith("TOKEN_")

    def test_tokenize_long_string(self, strategy):
        """Test tokenizing very long string."""
        long_string = "x" * 10000
        result = strategy.anonymize(long_string)

        # Token should be fixed length regardless of input
        assert len(result) == 22

    def test_tokenize_unicode(self, strategy):
        """Test tokenizing unicode string."""
        result = strategy.anonymize("héllo wörld 日本語")

        assert result.startswith("TOKEN_")

    def test_tokenize_special_characters(self, strategy):
        """Test tokenizing special characters."""
        result = strategy.anonymize("!@#$%^&*()_+-=[]{}|;':\",./<>?")

        assert result.startswith("TOKEN_")

    def test_tokenize_email_format(self, strategy):
        """Test tokenizing email address."""
        result = strategy.anonymize("user@domain.org")

        assert result.startswith("TOKEN_")
        # Token should not contain email
        assert "@" not in result

    def test_multiple_tokenizations_use_store(self, strategy):
        """Test multiple tokenizations all use store."""
        mock_store = strategy.token_store

        strategy.anonymize("test1")
        strategy.anonymize("test2")
        strategy.anonymize("test3")

        assert mock_store.store_token.call_count == 3

    def test_tokenize_numeric_string(self, strategy):
        """Test tokenizing numeric string."""
        result = strategy.anonymize("1234567890")

        assert result.startswith("TOKEN_")


class TestTokenizationIntegration:
    """Integration-style tests for tokenization workflow."""

    def test_full_workflow_tokenize_and_reverse(self):
        """Test complete tokenize -> reverse workflow."""
        # Create mock store that tracks stored tokens
        stored_tokens = {}

        mock_store = Mock()

        def store_token(original_value, token, **kwargs):
            stored_tokens[token] = original_value

        mock_store.store_token.side_effect = store_token

        def reverse_token(request):
            result = Mock()
            result.original_value = stored_tokens.get(request.token, None)
            return result

        mock_store.reverse_token.side_effect = reverse_token

        # Create strategy
        config = TokenizationConfig(seed=12345)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        # Tokenize
        token = strategy.anonymize("sensitive@email.com")

        # Verify token was stored
        assert token in stored_tokens

        # Reverse
        original = strategy.reverse_token(token, "admin", "testing")

        assert original == "sensitive@email.com"

    def test_same_value_same_token(self):
        """Test same value always produces same token."""
        mock_store = Mock()
        config = TokenizationConfig(seed=12345)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        tokens = [strategy.anonymize("same@email.com") for _ in range(5)]

        # All tokens should be identical
        assert len(set(tokens)) == 1

    def test_different_values_different_tokens(self):
        """Test different values produce different tokens."""
        mock_store = Mock()
        config = TokenizationConfig(seed=12345)
        strategy = TokenizationStrategy(config, token_store=mock_store)

        emails = [f"user{i}@example.com" for i in range(5)]
        tokens = [strategy.anonymize(email) for email in emails]

        # All tokens should be unique
        assert len(set(tokens)) == 5
