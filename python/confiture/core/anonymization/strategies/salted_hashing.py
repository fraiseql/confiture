"""Salted hashing anonymization strategy.

Provides irreversible anonymization using salted HMAC hashing. One-way
operation that cannot be reversed, suitable for final anonymization.

Features:
- Irreversible: Cannot recover original value
- Deterministic: Same input + salt = same hash
- Rainbow-table resistant: Salt prevents precomputation attacks
- Unique-preserving: Preserves uniqueness for referential integrity
- Configurable: Algorithm, salt, truncation

Use cases:
- Final anonymization (no need for reversal)
- Referential integrity (need same value to hash the same)
- PII masking (email, SSN, etc.)
- Data deduplication
- Privacy by design

Example hashes:
    john@example.com → a1b2c3d4e5f6g7h8 (salted HMAC-SHA256)
    john@example.com → a1b2c3d4 (truncated to 8 chars)
    john@example.com → hash_a1b2c3d4 (with prefix)

Security:
- Irreversible (no decryption possible)
- Salt prevents rainbow tables
- HMAC prevents precomputation
- Deterministic preserves relationships
- Slow hash (bcrypt, scrypt) for passwords

Comparison with other strategies:
    ┌──────────────┬────────────┬──────────────┬────────────┐
    │ Strategy     │ Reversible │ Format-Pres. │ Speed      │
    ├──────────────┼────────────┼──────────────┼────────────┤
    │ Masking      │ No         │ Yes          │ Fast       │
    │ Tokenization │ Yes (RBAC) │ No           │ Fast       │
    │ FPE          │ Yes        │ Yes          │ Slow       │
    │ Salted Hash  │ No         │ No           │ Fast       │
    │ Diff Privacy │ No         │ Depends      │ Moderate   │
    └──────────────┴────────────┴──────────────┴────────────┘
"""

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
)


@dataclass
class SaltedHashingConfig(StrategyConfig):
    """Configuration for SaltedHashingStrategy.

    Attributes:
        algorithm: Hash algorithm (sha256, sha512, sha1, blake2b)
        salt: Static salt value (or uses ANONYMIZATION_SALT env var)
        salt_env_var: Environment variable containing salt
        length: Optional truncation length
        prefix: Optional prefix for output
        use_hmac: Use HMAC (recommended, more secure)
    """

    algorithm: str = "sha256"
    """Hash algorithm: sha256, sha512, sha1, blake2b."""

    salt: str | None = None
    """Static salt value (not recommended for production)."""

    salt_env_var: str = "ANONYMIZATION_SALT"
    """Environment variable containing salt."""

    length: int | None = None
    """Optional truncation length."""

    prefix: str = ""
    """Optional prefix for output (e.g., 'hash_')."""

    use_hmac: bool = True
    """Use HMAC for additional security (recommended)."""


class SaltedHashingStrategy(AnonymizationStrategy):
    """Irreversible salted hashing anonymization.

    Provides one-way hashing with salt and HMAC to prevent rainbow table
    attacks. Deterministic (same input = same output) which preserves
    relationships in data.

    Features:
        - Irreversible: No decryption possible
        - Deterministic: Same input = same hash
        - Rainbow-table resistant: Salt prevents precomputation
        - Unique-preserving: Preserves uniqueness for FK relationships
        - Configurable: Algorithm, salt, truncation

    Security:
        - Irreversible (no reversal possible)
        - HMAC-SHA256 resists offline attacks
        - Salt randomizes hash for same input across databases
        - Deterministic allows relationship preservation
        - Better than unsalted hashing (prevents rainbow tables)

    Use Cases:
        - Final anonymization (no need for reversal)
        - Referential integrity (same email = same hash)
        - PII redaction (phone, SSN, addresses)
        - Data deduplication (find duplicates by hash)
        - Privacy by design (PII never stored)

    Implementation Note:
        Uses HMAC-SHA256 by default (not plain SHA256) because:
        1. HMAC prevents precomputation attacks
        2. Secret key (from env or seed) adds security
        3. Salt + HMAC = strong rainbow-table resistance
        4. Deterministic for relationship preservation

    Example:
        >>> config = SaltedHashingConfig(
        ...     algorithm='sha256',
        ...     salt_env_var='ANONYMIZATION_SALT',
        ...     length=16,
        ...     prefix='hash_',
        ...     use_hmac=True,
        ...     seed_env_var='ANONYMIZATION_SEED'
        ... )
        >>> strategy = SaltedHashingStrategy(config)
        >>> h1 = strategy.anonymize('john@example.com')
        >>> h2 = strategy.anonymize('john@example.com')
        >>> h1 == h2  # Deterministic
        True
        >>> h3 = strategy.anonymize('jane@example.com')
        >>> h1 != h3  # Different input = different output
        True
    """

    def __init__(self, config: SaltedHashingConfig | None = None):
        """Initialize salted hashing strategy.

        Args:
            config: SaltedHashingConfig instance

        Raises:
            ValueError: If algorithm is invalid
        """
        config = config or SaltedHashingConfig()
        super().__init__(config)
        self.config: SaltedHashingConfig = config
        self._validate_algorithm()

    def _validate_algorithm(self) -> None:
        """Validate hash algorithm is supported.

        Raises:
            ValueError: If algorithm not supported
        """
        allowed = {"sha256", "sha512", "sha1", "blake2b", "md5"}
        if self.config.algorithm not in allowed:
            raise ValueError(f"Algorithm must be one of {allowed}, got '{self.config.algorithm}'")

    def anonymize(self, value: Any) -> Any:
        """Hash value using salt and HMAC.

        Args:
            value: Value to hash

        Returns:
            Hashed value with optional prefix and truncation

        Example:
            >>> strategy = SaltedHashingStrategy(
            ...     SaltedHashingConfig(seed=12345)
            ... )
            >>> h1 = strategy.anonymize('test')
            >>> h2 = strategy.anonymize('test')
            >>> h1 == h2  # Deterministic
            True
        """
        # Handle NULL
        if value is None:
            return None

        # Handle empty string
        if isinstance(value, str) and value == "":
            return ""

        # Convert to string for hashing
        value_str = str(value)

        # Get salt
        salt = self._get_salt()

        # Hash the value
        hash_value = self._compute_hash(value_str, salt)

        # Apply truncation if specified
        if self.config.length:
            hash_value = hash_value[: self.config.length]

        # Apply prefix if specified
        if self.config.prefix:
            hash_value = f"{self.config.prefix}{hash_value}"

        return hash_value

    def _get_salt(self) -> str:
        """Get salt from environment or configuration.

        Returns:
            Salt value (string)

        Order of precedence:
        1. Environment variable (if salt_env_var is set)
        2. Configuration value (if salt is set)
        3. Seed from strategy (uses _seed)
        4. Default value
        """
        # Try environment variable first
        if self.config.salt_env_var:
            env_salt = os.getenv(self.config.salt_env_var)
            if env_salt:
                return env_salt

        # Try configuration value
        if self.config.salt:
            return self.config.salt

        # Use seed as fallback
        return str(self._seed)

    def _compute_hash(self, value: str, salt: str) -> str:
        """Compute HMAC hash of value with salt.

        Args:
            value: Value to hash
            salt: Salt value

        Returns:
            Hex-encoded hash value
        """
        if self.config.use_hmac:
            # Use HMAC for additional security
            # Key = seed + salt (combining two secrets)
            key = f"{self._seed}{salt}".encode()
            hash_obj = hmac.new(
                key,
                value.encode(),
                getattr(hashlib, self.config.algorithm),
            )
        else:
            # Plain hash with salt prepended
            salted_value = f"{salt}:{value}".encode()
            hash_obj = getattr(hashlib, self.config.algorithm)(salted_value)

        return hash_obj.hexdigest()

    def validate(self, value: Any) -> bool:
        """Hashing works for any value type.

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
        """Comprehensive validation for salted hashing.

        Args:
            value: Value to validate
            column_name: Column name (for error context)
            table_name: Table name (for error context)

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []

        # Check salt is configured
        if not self.config.salt and not os.getenv(self.config.salt_env_var or ""):
            errors.append(
                f"Column {table_name}.{column_name}: "
                f"No salt configured (set {self.config.salt_env_var} env var or salt config)"
            )

        # Check value is string-like
        try:
            value_str = str(value).strip()
            if not value_str:
                errors.append(
                    f"Column {table_name}.{column_name}: "
                    f"Empty string will hash to same value (consider masking instead)"
                )
        except Exception as e:
            errors.append(f"Column {table_name}.{column_name}: Cannot convert to string: {e}")

        return len(errors) == 0, errors

    @property
    def is_reversible(self) -> bool:
        """Salted hashing is irreversible.

        Returns:
            False (hashing cannot be reversed)
        """
        return False
