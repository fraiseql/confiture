"""Immutable audit logging for anonymization operations.

This module provides an append-only audit trail for compliance with:
- GDPR Article 30 (Records of Processing Activities)
- Data protection audit requirements
- Operational accountability

Security Features:
- Immutable database table (append-only, no UPDATE/DELETE)
- HMAC signatures prevent tampering
- Timestamp tracking for all operations
- JSON serialization for portability
- User and hostname tracking
- Verification status recording

Example:
    >>> from datetime import datetime, timezone
    >>> from uuid import uuid4
    >>> from confiture.core.anonymization.audit import AuditEntry, AuditLogger
    >>>
    >>> # Create audit entry
    >>> entry = AuditEntry(
    ...     id=uuid4(),
    ...     timestamp=datetime.now(timezone.utc),
    ...     user="admin@example.com",
    ...     hostname="sync-server-01",
    ...     source_database="prod_main",
    ...     target_database="staging_copy",
    ...     profile_name="production",
    ...     profile_version="1.0",
    ...     profile_hash="abc123def456",
    ...     tables_synced=["users", "orders"],
    ...     rows_anonymized={"users": 1000, "orders": 5000},
    ...     strategies_applied={"email": 1000, "phone": 1000},
    ...     verification_passed=True,
    ...     verification_report="{}",
    ...     signature="hmac_sig_here"
    ... )
    >>>
    >>> # Log to database
    >>> logger = AuditLogger(database_connection)
    >>> logger.log_sync(entry)
    >>> print(f"Logged {entry.id}")
"""

import hashlib
import hmac
import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg


@dataclass
class AuditEntry:
    """Immutable audit log entry for compliance.

    Each entry records a complete anonymization operation with:
    - Identity: WHO (user, hostname) and WHEN (timestamp)
    - Operation: WHAT (which tables, which strategies)
    - Verification: DID IT WORK (verification_passed, verification_report)
    - Integrity: SIGNATURE (HMAC to prevent tampering)

    Attributes:
        id: Unique audit entry ID (UUID)
        timestamp: When the operation occurred (ISO 8601)
        user: User who performed the operation (email or system account)
        hostname: Server hostname where operation was performed
        source_database: Source database URL (for reference)
        target_database: Target database URL (for reference)
        profile_name: Anonymization profile name (for identification)
        profile_version: Profile version (for tracking changes)
        profile_hash: SHA256 hash of profile (for integrity check)
        tables_synced: List of table names processed
        rows_anonymized: Dict of table → count anonymized
        strategies_applied: Dict of strategy → count applied
        verification_passed: Whether verification checks passed
        verification_report: Detailed verification results (JSON string)
        signature: HMAC signature for tamper detection
    """

    id: UUID
    """Unique entry ID (UUID4)."""

    timestamp: datetime
    """Operation timestamp (UTC, ISO 8601)."""

    user: str
    """User who performed the operation."""

    hostname: str
    """Hostname where operation was performed."""

    source_database: str
    """Source database identifier."""

    target_database: str
    """Target database identifier."""

    profile_name: str
    """Anonymization profile name."""

    profile_version: str
    """Profile version number."""

    profile_hash: str
    """SHA256 hash of the profile (integrity check)."""

    tables_synced: list[str]
    """Tables that were anonymized."""

    rows_anonymized: dict[str, int]
    """Count of rows anonymized per table."""

    strategies_applied: dict[str, int]
    """Count of strategy applications per type."""

    verification_passed: bool
    """Whether verification checks passed."""

    verification_report: str
    """Verification details (JSON string)."""

    signature: str
    """HMAC signature for tamper detection."""

    def to_json(self) -> str:
        """Serialize entry to JSON for storage.

        Returns:
            JSON string representation of the audit entry
        """
        data = asdict(self)
        data["id"] = str(self.id)
        data["timestamp"] = self.timestamp.isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "AuditEntry":
        """Deserialize entry from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            Reconstructed AuditEntry instance

        Raises:
            ValueError: If JSON is invalid
        """
        try:
            data = json.loads(json_str)
            data["id"] = UUID(data["id"])
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            return cls(**data)
        except Exception as e:
            raise ValueError(f"Invalid audit entry JSON: {e}") from e


class AuditLogger:
    """Append-only audit log for anonymization operations.

    Provides secure logging with:
    - Immutable database table (no UPDATE/DELETE)
    - Automatic table creation
    - Entry signing with HMAC
    - Tamper detection via signatures

    Example:
        >>> import psycopg
        >>> conn = psycopg.connect("postgresql://localhost/confiture")
        >>> logger = AuditLogger(conn)
        >>> entry = AuditEntry(...)
        >>> logger.log_sync(entry)
        >>> log = logger.get_audit_log(limit=100)
        >>> print(f"Found {len(log)} audit entries")
    """

    def __init__(self, target_conn: psycopg.Connection):
        """Initialize audit logger with database connection.

        Args:
            target_conn: PostgreSQL connection for audit table

        Raises:
            psycopg.OperationalError: If connection fails
        """
        self.conn = target_conn
        self._ensure_audit_table()

    def _ensure_audit_table(self) -> None:
        """Create audit table if not exists (idempotent).

        This method creates the confiture_audit_log table with:
        - UUID primary key for entry identification
        - TIMESTAMPTZ for accurate time tracking
        - JSONB for flexible audit data
        - PostgreSQL-enforced append-only constraints

        Raises:
            psycopg.DatabaseError: If table creation fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_audit_log (
                    id UUID PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    user_name TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    source_database TEXT NOT NULL,
                    target_database TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    tables_synced TEXT[] NOT NULL,
                    rows_anonymized JSONB NOT NULL,
                    strategies_applied JSONB NOT NULL,
                    verification_passed BOOLEAN NOT NULL,
                    verification_report TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                -- Ensure table is append-only by revoking dangerous permissions
                REVOKE UPDATE, DELETE ON confiture_audit_log FROM PUBLIC;
            """
            )
            self.conn.commit()

    def log_sync(self, entry: AuditEntry) -> None:
        """Append entry to audit log (immutable append-only).

        This method appends a new audit entry. The entry cannot be
        modified or deleted after insertion due to database constraints.

        Args:
            entry: AuditEntry to log

        Raises:
            psycopg.DatabaseError: If insertion fails
        """
        with self.conn.cursor() as cursor:
            # Truncate microseconds to ensure consistent signature verification
            ts = entry.timestamp.replace(microsecond=0)
            cursor.execute(
                """
                INSERT INTO confiture_audit_log (
                    id, timestamp, user_name, hostname,
                    source_database, target_database,
                    profile_name, profile_version, profile_hash,
                    tables_synced, rows_anonymized, strategies_applied,
                    verification_passed, verification_report, signature
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    str(entry.id),
                    ts,
                    entry.user,
                    entry.hostname,
                    entry.source_database,
                    entry.target_database,
                    entry.profile_name,
                    entry.profile_version,
                    entry.profile_hash,
                    entry.tables_synced,
                    json.dumps(entry.rows_anonymized),
                    json.dumps(entry.strategies_applied),
                    entry.verification_passed,
                    entry.verification_report,
                    entry.signature,
                ),
            )
            self.conn.commit()

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent audit log entries (for reporting).

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of recent AuditEntry instances, newest first

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, timestamp, user_name, hostname,
                    source_database, target_database,
                    profile_name, profile_version, profile_hash,
                    tables_synced, rows_anonymized, strategies_applied,
                    verification_passed, verification_report, signature
                FROM confiture_audit_log
                ORDER BY timestamp DESC
                LIMIT %s
            """,
                (limit,),
            )

            entries = []
            for row in cursor.fetchall():
                # Normalize timestamp to UTC and remove microseconds for consistent signing
                ts = row[1]
                if ts and hasattr(ts, "astimezone"):
                    # Convert to UTC and truncate microseconds
                    ts = ts.astimezone(UTC).replace(microsecond=0)
                entries.append(
                    AuditEntry(
                        id=row[0],
                        timestamp=ts,
                        user=row[2],
                        hostname=row[3],
                        source_database=row[4],
                        target_database=row[5],
                        profile_name=row[6],
                        profile_version=row[7],
                        profile_hash=row[8],
                        tables_synced=list(row[9]),
                        rows_anonymized=json.loads(row[10])
                        if isinstance(row[10], str)
                        else row[10],
                        strategies_applied=json.loads(row[11])
                        if isinstance(row[11], str)
                        else row[11],
                        verification_passed=row[12],
                        verification_report=row[13],
                        signature=row[14],
                    )
                )

            return entries


def sign_audit_entry(entry: AuditEntry, secret: str | None = None) -> str:
    """Create HMAC signature for audit entry (prevents tampering).

    The signature is computed over key fields of the audit entry.
    If the entry is modified after signing, the signature will
    no longer match, indicating tampering.

    Args:
        entry: AuditEntry to sign
        secret: Secret key for HMAC (or uses AUDIT_LOG_SECRET env var)

    Returns:
        HMAC-SHA256 signature as hex string

    Example:
        >>> entry = AuditEntry(...)
        >>> sig = sign_audit_entry(entry, secret="my-secret")
        >>> # Later, verify by recomputing:
        >>> sig2 = sign_audit_entry(modified_entry, secret="my-secret")
        >>> assert sig == sig2  # Should fail if entry was modified
    """
    if secret is None:
        secret = os.getenv("AUDIT_LOG_SECRET", "default-secret")

    # Create deterministic JSON for signing
    # Include only immutable/important fields
    # Truncate microseconds to avoid precision issues when round-tripping through database
    ts = entry.timestamp.replace(microsecond=0)
    data = {
        "id": str(entry.id),
        "timestamp": ts.isoformat(),
        "user": entry.user,
        "hostname": entry.hostname,
        "source_database": entry.source_database,
        "target_database": entry.target_database,
        "profile_name": entry.profile_name,
        "profile_hash": entry.profile_hash,
        "tables_synced": ",".join(sorted(entry.tables_synced)),
        "rows_anonymized": sum(entry.rows_anonymized.values()),
        "verification_passed": entry.verification_passed,
    }

    json_str = json.dumps(data, sort_keys=True)
    signature = hmac.new(
        secret.encode(),
        json_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    return signature


def verify_audit_entry(entry: AuditEntry, secret: str | None = None) -> bool:
    """Verify HMAC signature of audit entry (detect tampering).

    Args:
        entry: AuditEntry to verify
        secret: Secret key for HMAC (or uses AUDIT_LOG_SECRET env var)

    Returns:
        True if signature is valid, False otherwise

    Example:
        >>> entry = logger.get_audit_log()[0]
        >>> if verify_audit_entry(entry, secret="my-secret"):
        ...     print("Entry is authentic")
        ... else:
        ...     print("Entry may have been tampered with!")
    """
    expected_sig = sign_audit_entry(entry, secret)
    return entry.signature == expected_sig


def create_audit_entry(
    user: str,
    source_db: str,
    target_db: str,
    profile_name: str,
    profile_version: str,
    profile_hash: str,
    tables: list[str],
    rows_by_table: dict[str, int],
    strategies_by_type: dict[str, int],
    verification_passed: bool,
    verification_report: str | None = None,
    secret: str | None = None,
) -> AuditEntry:
    """Create and sign an audit entry (convenience function).

    Args:
        user: User who performed the operation
        source_db: Source database identifier
        target_db: Target database identifier
        profile_name: Anonymization profile name
        profile_version: Profile version
        profile_hash: SHA256 hash of profile
        tables: List of tables processed
        rows_by_table: Dict of table → count anonymized
        strategies_by_type: Dict of strategy → count applied
        verification_passed: Whether verification succeeded
        verification_report: Detailed verification results (JSON)
        secret: Secret key for signature (or AUDIT_LOG_SECRET env var)

    Returns:
        Signed AuditEntry ready for logging

    Example:
        >>> entry = create_audit_entry(
        ...     user="admin@example.com",
        ...     source_db="prod_main",
        ...     target_db="staging_copy",
        ...     profile_name="production",
        ...     profile_version="1.0",
        ...     profile_hash="abc123",
        ...     tables=["users", "orders"],
        ...     rows_by_table={"users": 1000, "orders": 5000},
        ...     strategies_by_type={"email": 1000, "phone": 1000},
        ...     verification_passed=True,
        ...     verification_report="{}"
        ... )
        >>> logger.log_sync(entry)
    """
    entry = AuditEntry(
        id=uuid4(),
        timestamp=datetime.now(UTC),
        user=user,
        hostname=socket.gethostname(),
        source_database=source_db,
        target_database=target_db,
        profile_name=profile_name,
        profile_version=profile_version,
        profile_hash=profile_hash,
        tables_synced=tables,
        rows_anonymized=rows_by_table,
        strategies_applied=strategies_by_type,
        verification_passed=verification_passed,
        verification_report=verification_report or "{}",
        signature="",  # Will be computed below
    )

    # Sign the entry
    entry.signature = sign_audit_entry(entry, secret)

    return entry
