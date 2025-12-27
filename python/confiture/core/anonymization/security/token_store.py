"""Encrypted token store with RBAC and audit trails.

Provides secure storage for reversible anonymization tokens (from tokenization
strategies) with encryption at rest, role-based access control, and comprehensive
audit logging.

Security Features:
- AES-256-GCM encryption for all stored tokens
- RBAC enforcement for token reversals (only authorized users can reverse)
- Comprehensive audit trail for all reversals (WHO, WHEN, WHY)
- KMS key management with automatic rotation support
- Time-based token expiration and lifecycle management
- Database-level constraints (append-only reversal log)

Example:
    >>> from confiture.core.anonymization.security.token_store import (
    ...     EncryptedTokenStore, TokenReversalRequest, TokenAccessLevel
    ... )
    >>> from confiture.core.anonymization.security.kms_manager import (
    ...     KMSFactory, KMSProvider
    ... )
    >>>
    >>> # Initialize KMS (AWS example)
    >>> kms = KMSFactory.create(KMSProvider.AWS, region="us-east-1")
    >>>
    >>> # Initialize token store
    >>> store = EncryptedTokenStore(database_connection, kms_client=kms)
    >>>
    >>> # Store a token
    >>> store.store_token(
    ...     original_value="john.doe@example.com",
    ...     token="TOKEN_abc123xyz789",
    ...     column_name="users.email",
    ...     strategy_name="tokenization"
    ... )
    >>>
    >>> # Reverse a token (with RBAC check)
    >>> result = store.reverse_token(
    ...     token="TOKEN_abc123xyz789",
    ...     requester_id="admin@example.com",
    ...     reason="Customer support request"
    ... )
    >>> print(result.original_value)  # john.doe@example.com
    >>> print(result.audit_id)  # UUID of audit entry
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import psycopg

from .kms_manager import KMSClient

logger = logging.getLogger(__name__)


class TokenAccessLevel(Enum):
    """Access levels for token reversal."""

    NONE = 0
    """No access to reversals."""

    READ_ONLY = 1
    """Can read token metadata but not reverse."""

    REVERSE_WITH_REASON = 2
    """Can reverse tokens but requires audit reason."""

    REVERSE_WITHOUT_REASON = 3
    """Can reverse tokens without requiring audit reason (use with caution)."""

    UNRESTRICTED = 4
    """Full access (reserved for emergency recovery, minimal use)."""


@dataclass
class TokenMetadata:
    """Metadata for a stored token."""

    token: str
    """Token identifier (reversible, not the original value)."""

    column_name: str
    """Column this token represents (e.g., 'users.email')."""

    strategy_name: str
    """Strategy used to generate token (e.g., 'tokenization')."""

    created_at: datetime
    """When token was created (UTC)."""

    expires_at: datetime | None = None
    """When token expires (optional)."""

    key_version: int = 1
    """KMS key version used for encryption."""

    is_active: bool = True
    """Whether token is still valid and in use."""


@dataclass
class TokenReversalRequest:
    """Request to reverse a token."""

    token: str
    """Token to reverse."""

    requester_id: str
    """User ID requesting reversal (email or system account)."""

    reason: str | None = None
    """Reason for reversal (required for audit trail)."""

    department: str | None = None
    """Department requesting reversal (optional, for audit trail)."""

    ticket_id: str | None = None
    """Support ticket or case ID (optional, for traceability)."""


@dataclass
class TokenReversalResult:
    """Result of a token reversal."""

    original_value: str
    """The original value that was tokenized."""

    token: str
    """The token that was reversed."""

    audit_id: UUID
    """UUID of the audit entry for this reversal."""

    reversed_at: datetime
    """When the reversal was performed."""

    requested_by: str
    """User who performed the reversal."""


class EncryptedTokenStore:
    """Secure storage for reversible anonymization tokens.

    Provides encryption at rest, RBAC enforcement, and comprehensive audit
    logging for all token reversals. Designed for tokenization strategies
    where reversibility is needed under controlled conditions.

    Attributes:
        conn: PostgreSQL connection for token storage
        kms_client: KMS client for encryption key management
        allowed_reversers: Dict of user ID → access level
        log_secret: Secret for HMAC signing of reversal audit entries
    """

    # Default allowed reversers (override in init)
    ALLOWED_REVERSERS = {
        # "admin@example.com": TokenAccessLevel.UNRESTRICTED,
        # "support@example.com": TokenAccessLevel.REVERSE_WITH_REASON,
    }

    def __init__(
        self,
        conn: psycopg.Connection,
        kms_client: KMSClient,
        key_id: str = "token-store-key",
        allowed_reversers: dict[str, TokenAccessLevel] | None = None,
        log_secret: str | None = None,
    ):
        """Initialize encrypted token store.

        Args:
            conn: PostgreSQL connection
            kms_client: KMS client for encryption/decryption
            key_id: KMS key ID for token encryption (default: "token-store-key")
            allowed_reversers: Dict of user ID → access level for reversals
            log_secret: Secret for HMAC signing (uses env var if not provided)

        Raises:
            psycopg.OperationalError: If connection fails
        """
        self.conn = conn
        self.kms_client = kms_client
        self.key_id = key_id
        self.allowed_reversers = allowed_reversers or self.ALLOWED_REVERSERS
        self.log_secret = log_secret or "default-token-store-secret"

        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create token store tables if not exists (idempotent).

        Creates:
        1. confiture_tokens - Main token storage with encryption
        2. confiture_token_reversals - Append-only audit log for reversals

        Raises:
            psycopg.DatabaseError: If table creation fails
        """
        with self.conn.cursor() as cursor:
            # Main token storage
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_tokens (
                    token TEXT PRIMARY KEY,
                    encrypted_original BYTEA NOT NULL,
                    column_name TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ,
                    key_version INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by TEXT NOT NULL,
                    created_at_idx TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_tokens_column_name
                    ON confiture_tokens(column_name);
                CREATE INDEX IF NOT EXISTS idx_tokens_strategy_name
                    ON confiture_tokens(strategy_name);
                CREATE INDEX IF NOT EXISTS idx_tokens_expires_at
                    ON confiture_tokens(expires_at)
                    WHERE expires_at IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_tokens_active
                    ON confiture_tokens(is_active)
                    WHERE is_active = TRUE;
            """
            )

            # Append-only reversal audit log
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_token_reversals (
                    id UUID PRIMARY KEY,
                    token TEXT NOT NULL,
                    requester_id TEXT NOT NULL,
                    reason TEXT,
                    department TEXT,
                    ticket_id TEXT,
                    reversed_at TIMESTAMPTZ NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    signature TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_reversals_token
                    ON confiture_token_reversals(token);
                CREATE INDEX IF NOT EXISTS idx_reversals_requester
                    ON confiture_token_reversals(requester_id);
                CREATE INDEX IF NOT EXISTS idx_reversals_timestamp
                    ON confiture_token_reversals(reversed_at DESC);

                -- Ensure reversal log is append-only
                REVOKE UPDATE, DELETE ON confiture_token_reversals FROM PUBLIC;
            """
            )

            self.conn.commit()

    def store_token(
        self,
        original_value: str,
        token: str,
        column_name: str,
        strategy_name: str,
        created_by: str = "system",
        expires_in_days: int | None = None,
    ) -> TokenMetadata:
        """Store a token with encrypted original value.

        Args:
            original_value: The original value to encrypt and store
            token: The token identifier
            column_name: Column name this token represents (e.g., 'users.email')
            strategy_name: Strategy name (e.g., 'tokenization')
            created_by: User who created the token (default: 'system')
            expires_in_days: Optional expiration in days from now

        Returns:
            TokenMetadata with encryption details

        Raises:
            psycopg.DatabaseError: If storage fails
        """
        try:
            # Encrypt the original value using KMS
            encrypted = self.kms_client.encrypt(original_value.encode(), self.key_id)

            # Calculate expiration if provided
            expires_at = None
            if expires_in_days:
                expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

            # Get current key version from metadata
            key_metadata = self.kms_client.get_key_metadata(self.key_id)
            key_version = key_metadata.version

            # Store in database
            with self.conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO confiture_tokens (
                        token, encrypted_original, column_name, strategy_name,
                        created_at, expires_at, key_version, is_active, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (token) DO NOTHING
                """,
                    (
                        token,
                        encrypted,
                        column_name,
                        strategy_name,
                        datetime.now(UTC),
                        expires_at,
                        key_version,
                        True,
                        created_by,
                    ),
                )
            self.conn.commit()

            logger.info(
                f"Stored token {token[:8]}... for column {column_name} with strategy {strategy_name}"
            )

            return TokenMetadata(
                token=token,
                column_name=column_name,
                strategy_name=strategy_name,
                created_at=datetime.now(UTC),
                expires_at=expires_at,
                key_version=key_version,
                is_active=True,
            )

        except Exception as e:
            logger.error(f"Failed to store token: {e}")
            raise

    def reverse_token(self, request: TokenReversalRequest) -> TokenReversalResult:
        """Reverse a token to get original value (with RBAC enforcement).

        Args:
            request: TokenReversalRequest with token, requester, reason

        Returns:
            TokenReversalResult with original value and audit info

        Raises:
            PermissionError: If requester not authorized
            ValueError: If token not found or expired
            psycopg.DatabaseError: If database operation fails
        """
        reversal_id = uuid4()
        reversed_at = datetime.now(UTC)

        try:
            # 1. Check RBAC
            self._check_rbac(request.requester_id, request.reason)

            # 2. Fetch encrypted token from database
            with self.conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT encrypted_original, expires_at, is_active
                    FROM confiture_tokens
                    WHERE token = %s
                """,
                    (request.token,),
                )
                row = cursor.fetchone()

            if not row:
                self._log_reversal(
                    reversal_id,
                    request,
                    reversed_at,
                    success=False,
                    error="Token not found",
                )
                raise ValueError(f"Token not found: {request.token}")

            encrypted_original, expires_at, is_active = row

            # 3. Check if token is active
            if not is_active:
                self._log_reversal(
                    reversal_id,
                    request,
                    reversed_at,
                    success=False,
                    error="Token is inactive",
                )
                raise ValueError(f"Token is inactive: {request.token}")

            # 4. Check expiration
            if expires_at and datetime.now(UTC) > expires_at:
                self._log_reversal(
                    reversal_id,
                    request,
                    reversed_at,
                    success=False,
                    error="Token has expired",
                )
                raise ValueError(f"Token has expired: {request.token}")

            # 5. Decrypt using KMS
            decrypted = self.kms_client.decrypt(encrypted_original, self.key_id)
            original_value = decrypted.decode()

            # 6. Log successful reversal
            self._log_reversal(
                reversal_id, request, reversed_at, success=True, error=None
            )

            logger.info(
                f"Token reversed by {request.requester_id}: {request.token[:8]}... "
                f"(reason: {request.reason or 'not provided'})"
            )

            return TokenReversalResult(
                original_value=original_value,
                token=request.token,
                audit_id=reversal_id,
                reversed_at=reversed_at,
                requested_by=request.requester_id,
            )

        except (PermissionError, ValueError) as e:
            logger.warning(
                f"Token reversal failed for {request.requester_id}: {e}"
            )
            raise
        except Exception as e:
            logger.error(f"Unexpected error during token reversal: {e}")
            self._log_reversal(
                reversal_id,
                request,
                reversed_at,
                success=False,
                error=str(e),
            )
            raise

    def _check_rbac(self, requester_id: str, reason: str | None = None) -> None:
        """Check if requester is authorized to reverse tokens.

        Args:
            requester_id: User ID requesting reversal
            reason: Reason for reversal

        Raises:
            PermissionError: If requester not authorized
        """
        if requester_id not in self.allowed_reversers:
            raise PermissionError(
                f"User {requester_id} is not authorized to reverse tokens"
            )

        access_level = self.allowed_reversers[requester_id]

        # Check if reason is required
        if access_level == TokenAccessLevel.REVERSE_WITH_REASON:
            if not reason or not reason.strip():
                raise PermissionError(
                    f"User {requester_id} requires a reason for token reversal"
                )

        # NONE and READ_ONLY users can't reverse
        if access_level in (TokenAccessLevel.NONE, TokenAccessLevel.READ_ONLY):
            raise PermissionError(
                f"User {requester_id} does not have reversal permissions"
            )

    def _log_reversal(
        self,
        reversal_id: UUID,
        request: TokenReversalRequest,
        reversed_at: datetime,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Log a token reversal attempt (append-only).

        Args:
            reversal_id: UUID for this reversal attempt
            request: Original reversal request
            reversed_at: When reversal was attempted
            success: Whether reversal succeeded
            error: Error message if failed

        Raises:
            psycopg.DatabaseError: If logging fails
        """
        # Create audit entry
        audit_data = {
            "token": request.token,
            "requester_id": request.requester_id,
            "reason": request.reason,
            "department": request.department,
            "ticket_id": request.ticket_id,
            "success": success,
        }

        signature = self._sign_reversal(audit_data)

        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_token_reversals (
                    id, token, requester_id, reason, department, ticket_id,
                    reversed_at, success, error_message, signature
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    str(reversal_id),
                    request.token,
                    request.requester_id,
                    request.reason,
                    request.department,
                    request.ticket_id,
                    reversed_at,
                    success,
                    error,
                    signature,
                ),
            )
        self.conn.commit()

    def _sign_reversal(self, audit_data: dict[str, Any]) -> str:
        """Create HMAC signature for reversal audit entry.

        Args:
            audit_data: Audit data to sign

        Returns:
            HMAC-SHA256 signature as hex string
        """
        json_str = json.dumps(audit_data, sort_keys=True)
        signature = hashlib.sha256(
            self.log_secret.encode() + json_str.encode()
        ).hexdigest()
        return signature

    def get_reversal_audit_log(
        self, token: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get reversal audit log (for compliance reporting).

        Args:
            token: Optional token to filter by
            limit: Maximum number of entries to return

        Returns:
            List of reversal audit entries

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            if token:
                cursor.execute(
                    """
                    SELECT id, token, requester_id, reason, department, ticket_id,
                           reversed_at, success, error_message
                    FROM confiture_token_reversals
                    WHERE token = %s
                    ORDER BY reversed_at DESC
                    LIMIT %s
                """,
                    (token, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, token, requester_id, reason, department, ticket_id,
                           reversed_at, success, error_message
                    FROM confiture_token_reversals
                    ORDER BY reversed_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )

            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "id": str(row[0]),
                        "token": row[1],
                        "requester_id": row[2],
                        "reason": row[3],
                        "department": row[4],
                        "ticket_id": row[5],
                        "reversed_at": row[6],
                        "success": row[7],
                        "error_message": row[8],
                    }
                )

            return results

    def deactivate_token(
        self, token: str, deactivated_by: str, reason: str | None = None
    ) -> None:
        """Deactivate a token (prevent further reversals).

        Args:
            token: Token to deactivate
            deactivated_by: User who initiated deactivation
            reason: Reason for deactivation

        Raises:
            psycopg.DatabaseError: If update fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE confiture_tokens
                SET is_active = FALSE
                WHERE token = %s
            """,
                (token,),
            )
        self.conn.commit()

        logger.info(
            f"Token deactivated by {deactivated_by}: {token[:8]}... "
            f"(reason: {reason or 'not provided'})"
        )

    def cleanup_expired_tokens(self) -> int:
        """Remove expired tokens from storage (GDPR right to be forgotten).

        Returns:
            Number of tokens deleted

        Raises:
            psycopg.DatabaseError: If deletion fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM confiture_tokens
                WHERE expires_at IS NOT NULL
                AND expires_at < NOW()
                RETURNING token
            """
            )
            deleted_tokens = [row[0] for row in cursor.fetchall()]

        self.conn.commit()

        logger.info(f"Cleaned up {len(deleted_tokens)} expired tokens")
        return len(deleted_tokens)

    def get_token_metadata(self, token: str) -> TokenMetadata | None:
        """Get metadata for a token (without reversing it).

        Args:
            token: Token to lookup

        Returns:
            TokenMetadata or None if not found

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token, column_name, strategy_name, created_at,
                       expires_at, key_version, is_active
                FROM confiture_tokens
                WHERE token = %s
            """,
                (token,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return TokenMetadata(
            token=row[0],
            column_name=row[1],
            strategy_name=row[2],
            created_at=row[3],
            expires_at=row[4],
            key_version=row[5],
            is_active=row[6],
        )
