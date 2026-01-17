"""Integration of audit logging with ProductionSyncer.

This module provides helpers to log anonymization operations performed
during data synchronization with full audit trail for GDPR compliance.

Features:
- Automatic audit entry creation for sync operations
- Signature verification for tamper detection
- Profile hashing for integrity checks
- User and hostname tracking
- Integration with ProductionSyncer
"""

import hashlib
import json
from typing import Any

import psycopg

from confiture.core.anonymization.audit import (
    AuditEntry,
    AuditLogger,
    create_audit_entry,
    verify_audit_entry,
)
from confiture.core.anonymization.profile import AnonymizationProfile


def hash_profile(profile: AnonymizationProfile | None) -> str:
    """Create SHA256 hash of anonymization profile for integrity check.

    Args:
        profile: AnonymizationProfile to hash, or None

    Returns:
        SHA256 hash of profile JSON representation

    Example:
        >>> profile = AnonymizationProfile(...)
        >>> hash_val = hash_profile(profile)
        >>> print(len(hash_val))
        64  # SHA256 hex is 64 chars
    """
    if profile is None:
        # No anonymization, use empty hash
        return hashlib.sha256(b"").hexdigest()

    # Create deterministic JSON of profile
    profile_dict = {
        "name": profile.name,
        "version": profile.version,
        "global_seed": profile.global_seed,
        "strategies": {
            name: {
                "type": strategy.type,
                "config": strategy.config,
            }
            for name, strategy in profile.strategies.items()
        },
        "tables": {
            table_name: {
                "rules": [
                    {
                        "column": rule.column,
                        "strategy": rule.strategy,
                        "seed": rule.seed,
                    }
                    for rule in table_def.rules
                ]
            }
            for table_name, table_def in profile.tables.items()
        },
    }

    profile_json = json.dumps(profile_dict, sort_keys=True)
    return hashlib.sha256(profile_json.encode()).hexdigest()


def create_sync_audit_entry(
    user: str,
    source_database: str,
    target_database: str,
    profile: AnonymizationProfile | None,
    tables_synced: list[str],
    rows_by_table: dict[str, int],
    strategies_applied: dict[str, int],
    verification_passed: bool = True,
    verification_report: dict[str, Any] | None = None,
    secret: str | None = None,
) -> AuditEntry:
    """Create audit entry for data synchronization operation.

    Convenience function that creates a complete, signed audit entry
    for a sync operation.

    Args:
        user: User who performed the sync (email or system account)
        source_database: Source database identifier
        target_database: Target database identifier
        profile: Anonymization profile used (None if no anonymization)
        tables_synced: List of tables synchronized
        rows_by_table: Dict of table → row count
        strategies_applied: Dict of strategy → application count
        verification_passed: Whether verification checks passed
        verification_report: Detailed verification results
        secret: Secret key for HMAC (or AUDIT_LOG_SECRET env var)

    Returns:
        Signed AuditEntry ready for logging

    Example:
        >>> entry = create_sync_audit_entry(
        ...     user="admin@example.com",
        ...     source_database="prod_main",
        ...     target_database="staging_copy",
        ...     profile=profile,
        ...     tables_synced=["users", "orders"],
        ...     rows_by_table={"users": 1000, "orders": 5000},
        ...     strategies_applied={"email": 1000, "hash": 5000},
        ... )
        >>> logger.log_sync(entry)
    """
    profile_hash = hash_profile(profile)
    profile_name = profile.name if profile else "none"
    profile_version = profile.version if profile else "0.0"

    verification_json = (
        json.dumps(verification_report, sort_keys=True) if verification_report else "{}"
    )

    return create_audit_entry(
        user=user,
        source_db=source_database,
        target_db=target_database,
        profile_name=profile_name,
        profile_version=profile_version,
        profile_hash=profile_hash,
        tables=tables_synced,
        rows_by_table=rows_by_table,
        strategies_by_type=strategies_applied,
        verification_passed=verification_passed,
        verification_report=verification_json,
        secret=secret,
    )


class AuditedProductionSyncer:
    """Wrapper for ProductionSyncer that logs operations to audit trail.

    This class wraps an existing ProductionSyncer and adds audit logging
    functionality, creating signed audit entries for all sync operations.

    Example:
        >>> from confiture.core.syncer import ProductionSyncer
        >>> syncer = ProductionSyncer("prod", "staging")
        >>> audited = AuditedProductionSyncer(syncer, target_db_connection)
        >>> entry = audited.create_sync_entry(
        ...     user="admin@example.com",
        ...     profile=my_profile,
        ...     tables_synced=["users", "orders"],
        ...     rows_by_table={"users": 1000, "orders": 5000},
        ...     strategies_applied={"email": 1000}
        ... )
        >>> audited.log_sync_entry(entry)
    """

    def __init__(self, syncer: Any, target_connection: psycopg.Connection):
        """Initialize audited syncer.

        Args:
            syncer: ProductionSyncer instance to wrap
            target_connection: PostgreSQL connection for audit logging
        """
        self.syncer = syncer
        self.target_connection = target_connection
        self.audit_logger = AuditLogger(target_connection)

    def create_sync_entry(
        self,
        user: str,
        profile: AnonymizationProfile | None,
        tables_synced: list[str],
        rows_by_table: dict[str, int],
        strategies_applied: dict[str, int],
        verification_passed: bool = True,
        verification_report: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Create signed audit entry for sync operation.

        Args:
            user: User who performed the sync
            profile: Anonymization profile used
            tables_synced: Tables that were synced
            rows_by_table: Row counts per table
            strategies_applied: Strategy application counts
            verification_passed: Whether verification passed
            verification_report: Verification details

        Returns:
            Signed AuditEntry
        """
        source_db = self.syncer.source_config.database
        target_db = self.syncer.target_config.database

        return create_sync_audit_entry(
            user=user,
            source_database=f"{source_db}@{self.syncer.source_config.host}",
            target_database=f"{target_db}@{self.syncer.target_config.host}",
            profile=profile,
            tables_synced=tables_synced,
            rows_by_table=rows_by_table,
            strategies_applied=strategies_applied,
            verification_passed=verification_passed,
            verification_report=verification_report,
        )

    def log_sync_entry(self, entry: AuditEntry) -> None:
        """Log sync operation to audit trail.

        Args:
            entry: AuditEntry to log
        """
        self.audit_logger.log_sync(entry)

    def verify_audit_entry(self, entry: AuditEntry, secret: str | None = None) -> bool:
        """Verify integrity of logged audit entry.

        Args:
            entry: AuditEntry to verify
            secret: Secret key for HMAC (or AUDIT_LOG_SECRET env var)

        Returns:
            True if signature is valid, False otherwise
        """
        return verify_audit_entry(entry, secret)

    def get_sync_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent sync audit log entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of recent AuditEntry instances
        """
        return self.audit_logger.get_audit_log(limit)


def verify_sync_audit_trail(
    target_connection: psycopg.Connection,
    secret: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Verify integrity of all audit log entries.

    Checks that all audit entries have valid signatures, detecting any
    tampering or unauthorized modifications.

    Args:
        target_connection: PostgreSQL connection to audit table
        secret: Secret key for HMAC verification
        strict: If True, raise exception on any invalid entry

    Returns:
        Dictionary with verification results:
        {
            "total_entries": int,
            "valid_entries": int,
            "invalid_entries": int,
            "verification_passed": bool,
            "invalid_ids": list[str],
        }

    Raises:
        ValueError: If strict=True and any entry is invalid
    """
    logger = AuditLogger(target_connection)
    entries = logger.get_audit_log(limit=10000)  # Get all entries

    total = len(entries)
    valid = 0
    invalid = []

    for entry in entries:
        if verify_audit_entry(entry, secret):
            valid += 1
        else:
            invalid.append(str(entry.id))

    if strict and invalid:
        raise ValueError(f"Found {len(invalid)} invalid audit entries: {invalid}")

    return {
        "total_entries": total,
        "valid_entries": valid,
        "invalid_entries": len(invalid),
        "verification_passed": len(invalid) == 0,
        "invalid_ids": invalid,
    }


def audit_sync_operation(
    syncer: Any,
    target_connection: psycopg.Connection,
    user: str,
    profile: AnonymizationProfile | None,
    tables_synced: list[str],
    rows_by_table: dict[str, int],
    strategies_applied: dict[str, int],
    verification_passed: bool = True,
) -> AuditEntry:
    """Helper function to create and log audit entry for sync operation.

    Convenience function that handles the complete audit flow:
    1. Creates audit entry
    2. Signs it with HMAC
    3. Logs to database
    4. Returns entry for verification

    Args:
        syncer: ProductionSyncer instance
        target_connection: PostgreSQL connection
        user: User who performed sync
        profile: Anonymization profile
        tables_synced: Tables synchronized
        rows_by_table: Row counts
        strategies_applied: Strategy counts
        verification_passed: Whether verification passed

    Returns:
        Logged AuditEntry

    Example:
        >>> entry = audit_sync_operation(
        ...     syncer=syncer,
        ...     target_connection=conn,
        ...     user="admin@example.com",
        ...     profile=profile,
        ...     tables_synced=["users"],
        ...     rows_by_table={"users": 1000},
        ...     strategies_applied={"email": 1000}
        ... )
        >>> print(f"Audit entry logged: {entry.id}")
    """
    audited = AuditedProductionSyncer(syncer, target_connection)

    entry = audited.create_sync_entry(
        user=user,
        profile=profile,
        tables_synced=tables_synced,
        rows_by_table=rows_by_table,
        strategies_applied=strategies_applied,
        verification_passed=verification_passed,
    )

    audited.log_sync_entry(entry)
    return entry
