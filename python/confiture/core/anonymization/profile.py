"""Anonymization profile management with Pydantic schema validation.

This module provides secure YAML profile loading with:
- yaml.safe_load() to prevent injection attacks
- Pydantic schema validation to enforce structure
- Strategy type whitelist to prevent unknown strategies

Security Note:
    ✅ Uses yaml.safe_load() instead of yaml.load() - prevents code execution
    ✅ Pydantic validates all structure before use
    ✅ StrategyType enum whitelists allowed strategies
    ❌ Never use yaml.load() - it can execute arbitrary Python code

Example:
    >>> profile = AnonymizationProfile.load(Path("profiles/production.yaml"))
    >>> print(profile.name)
    'production'
    >>> print(list(profile.strategies.keys()))
    ['email_mask', 'phone_mask']
"""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator


class StrategyType(str, Enum):
    """Whitelist of allowed strategy types.

    Only these strategies are permitted in YAML profiles. This prevents
    arbitrary strategy types that could be used for injection attacks.

    Attributes:
        HASH: DeterministicHashStrategy - HMAC-based hashing
        EMAIL: EmailMaskingStrategy - Format-preserving email masking
        PHONE: PhoneMaskingStrategy - Format-preserving phone masking
        REDACT: SimpleRedactStrategy - Simple redaction
    """

    HASH = "hash"
    """HMAC-based deterministic hashing strategy."""

    EMAIL = "email"
    """Format-preserving email masking strategy."""

    PHONE = "phone"
    """Format-preserving phone number masking strategy."""

    REDACT = "redact"
    """Simple redaction strategy (all values → [REDACTED])."""


class StrategyDefinition(BaseModel):
    """Pydantic model for strategy definition in profiles.

    Each strategy in the profile must match this structure. Pydantic validates:
    - Type is in the StrategyType whitelist
    - Config (if provided) is a dictionary
    - All required fields are present

    Attributes:
        type: Strategy type (must be in StrategyType enum)
        config: Optional configuration dict for the strategy
        seed_env_var: Optional environment variable for deterministic seed
    """

    type: str
    """Strategy type name (must be in StrategyType enum)."""

    config: dict[str, Any] | None = None
    """Optional configuration dict for strategy-specific settings."""

    seed_env_var: str | None = None
    """Optional environment variable containing seed for determinism."""

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate strategy type is in whitelist.

        Args:
            v: Strategy type name

        Returns:
            Validated strategy type name

        Raises:
            ValueError: If type is not in StrategyType enum
        """
        allowed = {st.value for st in StrategyType}
        if v not in allowed:
            raise ValueError(
                f"Strategy type '{v}' not allowed. Allowed types: {', '.join(sorted(allowed))}"
            )
        return v


class AnonymizationRule(BaseModel):
    """Rule for anonymizing a specific column.

    Attributes:
        column: Name of the column to anonymize
        strategy: Strategy to apply (must reference a defined strategy)
        seed: Optional column-specific seed (overrides global_seed)
        options: Optional strategy-specific options
    """

    column: str
    """Name of the column to anonymize."""

    strategy: str
    """Strategy name to apply (must be defined in strategies section)."""

    seed: int | None = None
    """Column-specific seed (overrides global_seed if provided)."""

    options: dict[str, Any] | None = None
    """Strategy-specific configuration options."""


class TableDefinition(BaseModel):
    """Rules for anonymizing a specific table.

    Attributes:
        rules: List of anonymization rules for this table
    """

    rules: list[AnonymizationRule]
    """Rules for anonymizing columns in this table."""


class AnonymizationProfile(BaseModel):
    """Anonymization profile with schema validation.

    This Pydantic model validates the entire profile structure before use:
    - All required fields are present
    - Strategy types are whitelisted
    - Global seed and column seeds have proper precedence

    Attributes:
        name: Profile name (for identification)
        version: Profile version (for tracking changes)
        global_seed: Optional seed applied to all columns (if env var not provided)
        strategies: Dictionary of strategy definitions (validated)
        tables: Dictionary of table rules (validated)

    Example:
        >>> profile = AnonymizationProfile(
        ...     name="production",
        ...     version="1.0",
        ...     global_seed=12345,
        ...     strategies={
        ...         "email_mask": StrategyDefinition(type="email")
        ...     },
        ...     tables={
        ...         "users": TableDefinition(rules=[
        ...             AnonymizationRule(column="email", strategy="email_mask")
        ...         ])
        ...     }
        ... )
    """

    name: str
    """Profile name for identification."""

    version: str
    """Profile version (e.g., "1.0")."""

    global_seed: int | None = None
    """Optional seed applied to all columns unless overridden."""

    strategies: dict[str, StrategyDefinition]
    """Dictionary of strategy definitions by name."""

    tables: dict[str, TableDefinition]
    """Dictionary of table rules by table name."""

    @classmethod
    def load(cls, path: Path | str) -> "AnonymizationProfile":
        """Load profile from YAML file with safe loading and validation.

        Uses yaml.safe_load() to prevent code injection attacks, then validates
        the loaded structure with Pydantic schema validation.

        Args:
            path: Path to YAML profile file

        Returns:
            Validated AnonymizationProfile instance

        Raises:
            FileNotFoundError: If profile file doesn't exist
            yaml.YAMLError: If YAML is malformed
            ValueError: If profile structure doesn't match schema

        Example:
            >>> profile = AnonymizationProfile.load("profiles/production.yaml")
            >>> print(f"Profile: {profile.name} v{profile.version}")
            Profile: production v1.0
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Profile file not found: {path}")

        try:
            with open(path) as f:
                # ✅ SAFE: Use safe_load, not load
                raw_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in profile {path}: {e}") from e

        if raw_data is None:
            raise ValueError(f"Profile {path} is empty")

        # ✅ SAFE: Pydantic validates structure and types
        try:
            profile = cls(**raw_data)
        except Exception as e:
            raise ValueError(f"Invalid profile {path}: {e}") from e

        return profile

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnonymizationProfile":
        """Create profile from dictionary (for testing).

        Args:
            data: Dictionary with profile data

        Returns:
            Validated AnonymizationProfile instance

        Raises:
            ValueError: If profile structure doesn't match schema
        """
        return cls(**data)


def resolve_seed_for_column(rule: AnonymizationRule, profile: AnonymizationProfile) -> int:
    """Resolve seed for a column with proper precedence.

    Resolution order:
    1. Column-specific seed (highest priority)
    2. Global profile seed
    3. Default seed (0)

    Args:
        rule: Anonymization rule for the column
        profile: Parent anonymization profile

    Returns:
        Resolved seed value as integer

    Example:
        >>> profile = AnonymizationProfile.from_dict({
        ...     "name": "test",
        ...     "version": "1.0",
        ...     "global_seed": 12345,
        ...     "strategies": {},
        ...     "tables": {}
        ... })
        >>> rule = AnonymizationRule(column="email", strategy="email_mask")
        >>> resolve_seed_for_column(rule, profile)
        12345
        >>> rule2 = AnonymizationRule(
        ...     column="special", strategy="email_mask", seed=99999
        ... )
        >>> resolve_seed_for_column(rule2, profile)
        99999
    """
    # Column-specific seed takes precedence
    if rule.seed is not None:
        return rule.seed

    # Global seed applies to all columns
    if profile.global_seed is not None:
        return profile.global_seed

    # Default seed
    return 0
