"""Tokenization anonymization strategy (Phase 2.2.2).

Provides reversible anonymization using tokens stored in encrypted token store.
Original values are encrypted and stored securely, enabling reversal when needed.

Features:
- Reversible: Can recover original value with RBAC enforcement
- Deterministic: Same input + seed = same token (for consistency)
- Encrypted storage: Original values encrypted at rest with KMS
- Audit trail: All reversals logged for compliance
- RBAC: Role-based access control for reversals

Use cases:
- Support scenarios (customer service needs to verify identity)
- Legal holds (must be able to access original values)
- Dispute resolution (chargebacks, complaints)
- Data subject rights (GDPR access requests)

Security:
- Tokens are opaque (no information leaked)
- Original values never stored in logs
- KMS controls encryption keys
- Reversal requires authorization + audit trail
"""

from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.security.token_store import (
    EncryptedTokenStore,
    TokenReversalRequest,
)
from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class TokenizationConfig(StrategyConfig):
    """Configuration for TokenizationStrategy.

    Attributes:
        token_prefix: Prefix for generated tokens (e.g., 'TOKEN_')
        token_length: Length of token after prefix
        hash_algorithm: Algorithm for deterministic token generation
        separator: Separator in token (e.g., '_', '-')
        allow_reversals: Whether reversals are allowed (default: True)
        reversal_requires_reason: Whether reversal requires audit reason
    """

    token_prefix: str = "TOKEN_"
    """Prefix for generated tokens (e.g., 'TOKEN_')."""

    token_length: int = 16
    """Length of token hash portion."""

    hash_algorithm: str = "sha256"
    """Hash algorithm for deterministic token generation."""

    separator: str = "_"
    """Separator character (used in token formatting)."""

    allow_reversals: bool = True
    """Whether this strategy allows token reversals."""

    reversal_requires_reason: bool = True
    """Whether reversal requires an audit reason."""


class TokenizationStrategy(AnonymizationStrategy):
    """Reversible tokenization using encrypted storage.

    This strategy generates opaque tokens for PII values and stores
    the original values encrypted in a KMS-managed token store.
    Authorized users can reverse tokens with full audit trail.

    Features:
        - Reversible: Recover original with RBAC enforcement
        - Deterministic: Same input = same token (for consistency)
        - Encrypted storage: Values encrypted at rest
        - Audit trail: All reversals logged
        - RBAC: Role-based access control

    Security:
        - NOT reversible without token store access
        - Original values encrypted with KMS
        - Tokens are opaque (no information)
        - Reversals require authorization
        - All reversals logged for audit

    Architecture:
        ┌─────────────────────────────────┐
        │ Original Value                  │
        │ john.doe@example.com            │
        └────────────┬────────────────────┘
                     │
        ┌────────────▼──────────────────┐
        │ Generate Deterministic Token  │
        │ TOKEN_a1b2c3d4e5f6g7h8i9j0   │
        └────────────┬──────────────────┘
                     │
        ┌────────────▼──────────────────────────┐
        │ Store in Token Store                   │
        │ token_store.store_token(                │
        │   original="john.doe@example.com",    │
        │   token="TOKEN_a1b2c3d4e5f6g7h8i9j0"  │
        │ )                                      │
        └────────────┬──────────────────────────┘
                     │
        ┌────────────▼───────────────────────┐
        │ Return Token to User                │
        │ TOKEN_a1b2c3d4e5f6g7h8i9j0         │
        │                                     │
        │ Original encrypted at rest in DB   │
        └─────────────────────────────────────┘

    Later, reversal (with RBAC):
        ┌────────────────────────────────┐
        │ Check RBAC Authorization        │
        │ (is user allowed to reverse?)   │
        └────────────┬───────────────────┘
                     │
        ┌────────────▼──────────────────────────┐
        │ Decrypt Original from Token Store      │
        │ token_store.reverse_token(             │
        │   token="TOKEN_a1b2c3d4e5f6g7h8i9j0",  │
        │   requester_id="admin@example.com",    │
        │   reason="Customer support"            │
        │ )                                      │
        └────────────┬──────────────────────────┘
                     │
        ┌────────────▼────────────────────────┐
        │ Return Original Value + Audit ID     │
        │ john.doe@example.com                 │
        │ (Reversal logged in immutable trail) │
        └──────────────────────────────────────┘

    Example:
        >>> from confiture.core.anonymization.security.token_store import (
        ...     EncryptedTokenStore
        ... )
        >>> from confiture.core.anonymization.security.kms_manager import (
        ...     KMSFactory, KMSProvider
        ... )
        >>>
        >>> # Initialize with KMS and token store
        >>> kms = KMSFactory.create(KMSProvider.LOCAL)
        >>> token_store = EncryptedTokenStore(conn, kms_client=kms)
        >>> config = TokenizationConfig(seed=12345)
        >>> strategy = TokenizationStrategy(config, token_store=token_store)
        >>>
        >>> # Anonymize (returns token)
        >>> token = strategy.anonymize('john@example.com')
        >>> # TOKEN_a1b2c3d4e5f6g7h8
        >>>
        >>> # Reverse (returns original, logs in audit trail)
        >>> original = strategy.reverse_token(
        ...     token,
        ...     requester_id='admin@example.com',
        ...     reason='Customer support'
        ... )
        >>> original  # 'john@example.com'
    """

    def __init__(
        self,
        config: TokenizationConfig | None = None,
        token_store: EncryptedTokenStore | None = None,
        column_name: str = "",
    ):
        """Initialize tokenization strategy.

        Args:
            config: TokenizationConfig instance
            token_store: EncryptedTokenStore for storing tokens
            column_name: Column name (for token store metadata)

        Raises:
            ValueError: If token_store is required but not provided
        """
        config = config or TokenizationConfig()
        super().__init__(config)
        self.config: TokenizationConfig = config
        self.token_store = token_store
        self.column_name = column_name
        self.is_reversible = True
        self.requires_kms = True

    def anonymize(self, value: Any) -> Any:
        """Generate token for value and store original encrypted.

        Args:
            value: Value to tokenize

        Returns:
            Token identifier (opaque)

        Raises:
            ValueError: If token_store not configured
            Exception: If token storage fails
        """
        if self.token_store is None:
            raise ValueError(
                "TokenizationStrategy requires token_store to be configured"
            )

        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        value_str = str(value).strip()
        if not value_str:
            return ""

        # Generate deterministic token
        token = self._generate_token(value_str)

        # Store original value encrypted in token store
        self.token_store.store_token(
            original_value=value_str,
            token=token,
            column_name=self.column_name,
            strategy_name=self.name_short(),
        )

        return token

    def _generate_token(self, value: str) -> str:
        """Generate deterministic token for value.

        Args:
            value: Value to tokenize

        Returns:
            Token identifier
        """
        # Create deterministic hash
        hash_input = f"{self._seed}:{value}".encode()
        hash_obj = __import__("hashlib").sha256(hash_input)
        hash_hex = hash_obj.hexdigest()[: self.config.token_length]

        # Format with prefix
        token = f"{self.config.token_prefix}{hash_hex}"

        return token

    def reverse_token(
        self,
        token: str,
        requester_id: str,
        reason: str | None = None,
    ) -> str:
        """Reverse token to original value (with RBAC enforcement).

        Args:
            token: Token to reverse
            requester_id: User requesting reversal (for RBAC)
            reason: Business reason for reversal (for audit trail)

        Returns:
            Original value

        Raises:
            PermissionError: If requester not authorized
            ValueError: If token not found or invalid
            Exception: If reversal fails
        """
        if self.token_store is None:
            raise ValueError(
                "TokenizationStrategy requires token_store to be configured"
            )

        if not self.config.allow_reversals:
            raise PermissionError(
                f"Reversals are not allowed for {self.name_short()} strategy"
            )

        # Request reversal from token store (handles RBAC)
        request = TokenReversalRequest(
            token=token,
            requester_id=requester_id,
            reason=reason,
        )

        result = self.token_store.reverse_token(request)
        return result.original_value

    def validate(self, value: Any) -> bool:
        """Tokenization works for any value type.

        Args:
            value: Value to validate

        Returns:
            True if value can be converted to string
        """
        try:
            str(value)
            return True
        except (TypeError, ValueError):
            return False

    def validate_comprehensive(
        self,
        value: Any,
        column_name: str = "",
        table_name: str = "",
    ) -> tuple[bool, list[str]]:
        """Comprehensive validation for tokenization.

        Args:
            value: Value to validate
            column_name: Column name (for error context)
            table_name: Table name (for error context)

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []

        # Check token store is configured
        if self.token_store is None:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"TokenizationStrategy requires token_store to be configured"
            )

        # Check value is string-like
        try:
            value_str = str(value).strip()
            if not value_str:
                errors.append(
                    f"Column {table_name}.{column_name}: "
                    f"Empty string cannot be tokenized"
                )
        except Exception as e:
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"Cannot convert to string: {e}"
            )

        return len(errors) == 0, errors
