"""Immutable data lineage with HMAC signatures and blockchain-style chaining.

Provides tamper-proof audit trails for anonymization operations using:
- HMAC-SHA256 signatures to detect tampering
- Append-only database constraints
- Blockchain-style entry chaining (each entry includes hash of previous)
- Complete lineage tracking (WHO, WHEN, WHAT, HOW)

Addresses CRITICAL-2 Security Finding:
"Data Lineage Not Tamper-Proof"
- Prevents audit trail falsification
- Enables forensic investigation of anonymization operations
- Supports regulatory compliance (GDPR Articles 30, 5(1)(f))

Example:
    >>> from confiture.core.anonymization.security.lineage import (
    ...     DataLineageEntry, DataLineageTracker, create_lineage_entry
    ... )
    >>>
    >>> # Initialize lineage tracker
    >>> tracker = DataLineageTracker(database_connection)
    >>>
    >>> # Record anonymization operation
    >>> entry = create_lineage_entry(
    ...     operation_id="anon-001",
    ...     table_name="users",
    ...     column_name="email",
    ...     strategy_name="tokenization",
    ...     rows_affected=1000,
    ...     executed_by="admin@example.com",
    ...     reason="GDPR compliance",
    ...     secret="lineage-secret"
    ... )
    >>>
    >>> # Log to database
    >>> tracker.record_entry(entry)
    >>>
    >>> # Verify lineage integrity
    >>> if tracker.verify_lineage_integrity(entry.id):
    ...     print("Lineage is authentic")
    ... else:
    ...     print("Lineage may have been tampered with!")
    >>>
    >>> # Get lineage for a table
    >>> lineage = tracker.get_table_lineage("users")
    >>> for entry in lineage:
    ...     print(f"{entry.operation_id}: {entry.strategy_name} on {entry.column_name}")
"""

import hashlib
import hmac
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg

logger = logging.getLogger(__name__)


@dataclass
class DataLineageEntry:
    """Immutable lineage entry for anonymization operations.

    Each entry records a complete anonymization operation with cryptographic
    proof of authenticity and integrity. Entries are chained together
    (blockchain-style) to detect any tampering.

    Attributes:
        id: Unique entry ID (UUID)
        operation_id: Operation identifier (for correlation)
        table_name: Table that was anonymized
        column_name: Column that was anonymized
        strategy_name: Anonymization strategy used (e.g., 'tokenization')
        strategy_version: Version of strategy (for tracking changes)
        rows_affected: Number of rows anonymized
        executed_by: User who executed the operation
        executed_at: When the operation was executed (UTC)
        reason: Business reason for anonymization (compliance, user request, etc.)
        request_id: External request ID (ticket, case, etc.) for traceability
        department: Department that requested anonymization
        data_minimization_applied: Whether data minimization was used
        retention_days: Data retention period in days
        source_count: Original row count before anonymization
        target_count: Row count after anonymization
        duration_seconds: How long the operation took
        status: Operation status (success, error)
        error_message: Error message if operation failed
        hmac_signature: HMAC-SHA256 signature for tamper detection
        previous_entry_hash: Hash of previous entry (blockchain-style)
        entry_hash: SHA256 hash of this entry's immutable data
        verification_status: Result of HMAC verification
    """

    id: UUID
    """Unique entry ID (UUID4)."""

    operation_id: str
    """Correlation ID for this operation."""

    table_name: str
    """Table that was anonymized."""

    column_name: str
    """Column that was anonymized."""

    strategy_name: str
    """Anonymization strategy used."""

    strategy_version: str = "1.0"
    """Strategy version."""

    rows_affected: int = 0
    """Number of rows anonymized."""

    executed_by: str = "system"
    """User who executed the operation."""

    executed_at: datetime = None
    """When the operation was executed."""

    reason: str | None = None
    """Business reason for anonymization."""

    request_id: str | None = None
    """External request ID (ticket, case, etc.)."""

    department: str | None = None
    """Department that requested anonymization."""

    data_minimization_applied: bool = False
    """Whether data minimization was used."""

    retention_days: int | None = None
    """Data retention period."""

    source_count: int | None = None
    """Original row count."""

    target_count: int | None = None
    """Row count after anonymization."""

    duration_seconds: float = 0.0
    """Operation duration."""

    status: str = "success"
    """Operation status (success, error, partial)."""

    error_message: str | None = None
    """Error message if operation failed."""

    hmac_signature: str = ""
    """HMAC-SHA256 signature for tamper detection."""

    previous_entry_hash: str | None = None
    """SHA256 hash of previous entry (blockchain-style chaining)."""

    entry_hash: str = ""
    """SHA256 hash of this entry's immutable data."""

    verification_status: str = "unverified"
    """Result of HMAC verification (verified, tampered, unverified)."""

    def __post_init__(self) -> None:
        """Initialize defaults for datetime and hash fields."""
        if self.executed_at is None:
            self.executed_at = datetime.now(UTC)

    def to_json(self) -> str:
        """Serialize entry to JSON (for storage/transmission).

        Returns:
            JSON string representation of the entry
        """
        data = asdict(self)
        data["id"] = str(self.id)
        data["executed_at"] = self.executed_at.isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "DataLineageEntry":
        """Deserialize entry from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            Reconstructed DataLineageEntry instance

        Raises:
            ValueError: If JSON is invalid
        """
        try:
            data = json.loads(json_str)
            data["id"] = UUID(data["id"])
            data["executed_at"] = datetime.fromisoformat(data["executed_at"])
            return cls(**data)
        except Exception as e:
            raise ValueError(f"Invalid lineage entry JSON: {e}") from e


class DataLineageTracker:
    """Immutable data lineage tracking with HMAC signatures.

    Provides secure logging of anonymization operations with:
    - HMAC-SHA256 signatures prevent tampering
    - Blockchain-style chaining (each entry references previous)
    - Append-only database table (no UPDATE/DELETE)
    - Complete audit trail (WHO, WHEN, WHAT, WHY)
    - Verification capabilities (detect tampering)

    Example:
        >>> import psycopg
        >>> conn = psycopg.connect("postgresql://localhost/confiture")
        >>> tracker = DataLineageTracker(conn)
        >>>
        >>> entry = create_lineage_entry(
        ...     operation_id="anon-001",
        ...     table_name="users",
        ...     column_name="email",
        ...     strategy_name="tokenization",
        ...     rows_affected=1000,
        ...     executed_by="admin@example.com",
        ...     secret="lineage-secret"
        ... )
        >>> tracker.record_entry(entry)
        >>>
        >>> # Verify integrity
        >>> status = tracker.verify_lineage_integrity()
        >>> print(f"Lineage is {status}")
    """

    def __init__(self, conn: psycopg.Connection):
        """Initialize lineage tracker with database connection.

        Args:
            conn: PostgreSQL connection for lineage table

        Raises:
            psycopg.OperationalError: If connection fails
        """
        self.conn = conn
        self._ensure_lineage_table()

    def _ensure_lineage_table(self) -> None:
        """Create lineage table if not exists (idempotent).

        Creates confiture_data_lineage table with:
        - UUID primary key for entry identification
        - HMAC signature column for tamper detection
        - Previous entry hash for blockchain-style chaining
        - PostgreSQL-enforced append-only constraints
        - Indexes for efficient queries

        Raises:
            psycopg.DatabaseError: If table creation fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_data_lineage (
                    id UUID PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    rows_affected INTEGER NOT NULL,
                    executed_by TEXT NOT NULL,
                    executed_at TIMESTAMPTZ NOT NULL,
                    reason TEXT,
                    request_id TEXT,
                    department TEXT,
                    data_minimization_applied BOOLEAN NOT NULL,
                    retention_days INTEGER,
                    source_count INTEGER,
                    target_count INTEGER,
                    duration_seconds FLOAT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    hmac_signature TEXT NOT NULL,
                    previous_entry_hash TEXT,
                    entry_hash TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                -- Indexes for efficient queries
                CREATE INDEX IF NOT EXISTS idx_lineage_operation_id
                    ON confiture_data_lineage(operation_id);
                CREATE INDEX IF NOT EXISTS idx_lineage_table_name
                    ON confiture_data_lineage(table_name);
                CREATE INDEX IF NOT EXISTS idx_lineage_column_name
                    ON confiture_data_lineage(column_name);
                CREATE INDEX IF NOT EXISTS idx_lineage_executed_by
                    ON confiture_data_lineage(executed_by);
                CREATE INDEX IF NOT EXISTS idx_lineage_executed_at
                    ON confiture_data_lineage(executed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_lineage_strategy_name
                    ON confiture_data_lineage(strategy_name);

                -- Ensure table is append-only by revoking dangerous permissions
                REVOKE UPDATE, DELETE ON confiture_data_lineage FROM PUBLIC;
            """
            )
            self.conn.commit()

    def record_entry(self, entry: DataLineageEntry) -> None:
        """Record a lineage entry (append-only, immutable).

        This method:
        1. Fetches the previous entry's hash (for chaining)
        2. Computes HMAC signature of the entry
        3. Computes hash of the entry (for next entry's chaining)
        4. Appends to database (no modification possible)

        Args:
            entry: DataLineageEntry to record

        Raises:
            psycopg.DatabaseError: If insertion fails
        """
        try:
            # Get previous entry's hash for blockchain-style chaining
            previous_hash = self._get_previous_entry_hash()

            # Compute entry hash for next entry's chaining
            entry.entry_hash = self._compute_entry_hash(entry)

            # Set previous entry hash
            entry.previous_entry_hash = previous_hash

            # Compute HMAC signature
            entry.hmac_signature = sign_lineage_entry(entry)

            # Insert into database
            with self.conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO confiture_data_lineage (
                        id, operation_id, table_name, column_name, strategy_name,
                        strategy_version, rows_affected, executed_by, executed_at,
                        reason, request_id, department, data_minimization_applied,
                        retention_days, source_count, target_count, duration_seconds,
                        status, error_message, hmac_signature, previous_entry_hash,
                        entry_hash, verification_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """,
                    (
                        str(entry.id),
                        entry.operation_id,
                        entry.table_name,
                        entry.column_name,
                        entry.strategy_name,
                        entry.strategy_version,
                        entry.rows_affected,
                        entry.executed_by,
                        entry.executed_at,
                        entry.reason,
                        entry.request_id,
                        entry.department,
                        entry.data_minimization_applied,
                        entry.retention_days,
                        entry.source_count,
                        entry.target_count,
                        entry.duration_seconds,
                        entry.status,
                        entry.error_message,
                        entry.hmac_signature,
                        entry.previous_entry_hash,
                        entry.entry_hash,
                        entry.verification_status,
                    ),
                )
            self.conn.commit()

            logger.info(
                f"Recorded lineage entry: {entry.operation_id} "
                f"({entry.strategy_name} on {entry.table_name}.{entry.column_name})"
            )

        except Exception as e:
            logger.error(f"Failed to record lineage entry: {e}")
            raise

    def _get_previous_entry_hash(self) -> str | None:
        """Get the hash of the most recent entry (for blockchain chaining).

        Returns:
            Hash of previous entry, or None if this is the first entry

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT entry_hash FROM confiture_data_lineage
                ORDER BY executed_at DESC, created_at DESC
                LIMIT 1
            """
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def _compute_entry_hash(self, entry: DataLineageEntry) -> str:
        """Compute SHA256 hash of entry's immutable fields.

        This hash is used for blockchain-style chaining (included in next entry).

        Args:
            entry: Entry to hash

        Returns:
            SHA256 hash as hex string
        """
        # Include only immutable fields
        data = {
            "id": str(entry.id),
            "operation_id": entry.operation_id,
            "table_name": entry.table_name,
            "column_name": entry.column_name,
            "strategy_name": entry.strategy_name,
            "rows_affected": entry.rows_affected,
            "executed_by": entry.executed_by,
            "executed_at": entry.executed_at.isoformat(),
            "status": entry.status,
        }

        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def verify_lineage_integrity(self, entry_id: UUID | None = None) -> bool:
        """Verify lineage integrity (detect tampering).

        If entry_id is provided, verifies only that entry.
        If entry_id is None, verifies the entire chain.

        Args:
            entry_id: Optional entry ID to verify (all if None)

        Returns:
            True if lineage is authentic, False if tampering detected

        Raises:
            psycopg.DatabaseError: If query fails
        """
        if entry_id:
            return self._verify_single_entry(entry_id)
        else:
            return self._verify_entire_chain()

    def _verify_single_entry(self, entry_id: UUID) -> bool:
        """Verify a single entry's HMAC signature.

        Args:
            entry_id: Entry to verify

        Returns:
            True if signature is valid, False otherwise
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, operation_id, table_name, column_name, strategy_name,
                    strategy_version, rows_affected, executed_by, executed_at,
                    reason, request_id, department, data_minimization_applied,
                    retention_days, source_count, target_count, duration_seconds,
                    status, error_message, hmac_signature, previous_entry_hash,
                    entry_hash, verification_status
                FROM confiture_data_lineage
                WHERE id = %s
            """,
                (str(entry_id),),
            )
            row = cursor.fetchone()

        if not row:
            logger.warning(f"Entry not found: {entry_id}")
            return False

        # Reconstruct entry from row
        entry = DataLineageEntry(
            id=UUID(row[0]),
            operation_id=row[1],
            table_name=row[2],
            column_name=row[3],
            strategy_name=row[4],
            strategy_version=row[5],
            rows_affected=row[6],
            executed_by=row[7],
            executed_at=row[8],
            reason=row[9],
            request_id=row[10],
            department=row[11],
            data_minimization_applied=row[12],
            retention_days=row[13],
            source_count=row[14],
            target_count=row[15],
            duration_seconds=row[16],
            status=row[17],
            error_message=row[18],
            hmac_signature=row[19],
            previous_entry_hash=row[20],
            entry_hash=row[21],
            verification_status=row[22],
        )

        # Verify HMAC signature
        expected_sig = sign_lineage_entry(entry)
        is_valid = entry.hmac_signature == expected_sig

        if not is_valid:
            logger.error(f"HMAC signature mismatch for entry {entry_id}")

        return is_valid

    def _verify_entire_chain(self) -> bool:
        """Verify entire lineage chain for tampering.

        Checks:
        1. Each entry's HMAC signature (authenticity)
        2. Blockchain-style chaining (completeness)

        Returns:
            True if entire chain is authentic, False if any tampering found

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, operation_id, table_name, column_name, strategy_name,
                    strategy_version, rows_affected, executed_by, executed_at,
                    reason, request_id, department, data_minimization_applied,
                    retention_days, source_count, target_count, duration_seconds,
                    status, error_message, hmac_signature, previous_entry_hash,
                    entry_hash, verification_status
                FROM confiture_data_lineage
                ORDER BY executed_at ASC, created_at ASC
            """
            )
            rows = cursor.fetchall()

        if not rows:
            # Empty chain is valid
            return True

        previous_hash = None

        for row in rows:
            # Reconstruct entry
            entry = DataLineageEntry(
                id=UUID(row[0]),
                operation_id=row[1],
                table_name=row[2],
                column_name=row[3],
                strategy_name=row[4],
                strategy_version=row[5],
                rows_affected=row[6],
                executed_by=row[7],
                executed_at=row[8],
                reason=row[9],
                request_id=row[10],
                department=row[11],
                data_minimization_applied=row[12],
                retention_days=row[13],
                source_count=row[14],
                target_count=row[15],
                duration_seconds=row[16],
                status=row[17],
                error_message=row[18],
                hmac_signature=row[19],
                previous_entry_hash=row[20],
                entry_hash=row[21],
                verification_status=row[22],
            )

            # 1. Verify HMAC signature
            expected_sig = sign_lineage_entry(entry)
            if entry.hmac_signature != expected_sig:
                logger.error(f"HMAC signature mismatch for entry {entry.id}")
                return False

            # 2. Verify blockchain chain
            if entry.previous_entry_hash != previous_hash:
                logger.error(
                    f"Chain integrity error at entry {entry.id}: "
                    f"expected previous hash {previous_hash}, "
                    f"got {entry.previous_entry_hash}"
                )
                return False

            previous_hash = entry.entry_hash

        logger.info(f"Lineage chain verified ({len(rows)} entries)")
        return True

    def get_table_lineage(self, table_name: str) -> list[DataLineageEntry]:
        """Get complete lineage for a table (for compliance reporting).

        Args:
            table_name: Table name to get lineage for

        Returns:
            List of lineage entries for table, newest first

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, operation_id, table_name, column_name, strategy_name,
                    strategy_version, rows_affected, executed_by, executed_at,
                    reason, request_id, department, data_minimization_applied,
                    retention_days, source_count, target_count, duration_seconds,
                    status, error_message, hmac_signature, previous_entry_hash,
                    entry_hash, verification_status
                FROM confiture_data_lineage
                WHERE table_name = %s
                ORDER BY executed_at DESC
            """,
                (table_name,),
            )
            rows = cursor.fetchall()

        entries = []
        for row in rows:
            entries.append(
                DataLineageEntry(
                    id=UUID(row[0]),
                    operation_id=row[1],
                    table_name=row[2],
                    column_name=row[3],
                    strategy_name=row[4],
                    strategy_version=row[5],
                    rows_affected=row[6],
                    executed_by=row[7],
                    executed_at=row[8],
                    reason=row[9],
                    request_id=row[10],
                    department=row[11],
                    data_minimization_applied=row[12],
                    retention_days=row[13],
                    source_count=row[14],
                    target_count=row[15],
                    duration_seconds=row[16],
                    status=row[17],
                    error_message=row[18],
                    hmac_signature=row[19],
                    previous_entry_hash=row[20],
                    entry_hash=row[21],
                    verification_status=row[22],
                )
            )

        return entries

    def get_lineage_by_operation(self, operation_id: str) -> list[DataLineageEntry]:
        """Get all entries for a specific operation.

        Args:
            operation_id: Operation identifier to search for

        Returns:
            List of lineage entries for operation

        Raises:
            psycopg.DatabaseError: If query fails
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, operation_id, table_name, column_name, strategy_name,
                    strategy_version, rows_affected, executed_by, executed_at,
                    reason, request_id, department, data_minimization_applied,
                    retention_days, source_count, target_count, duration_seconds,
                    status, error_message, hmac_signature, previous_entry_hash,
                    entry_hash, verification_status
                FROM confiture_data_lineage
                WHERE operation_id = %s
                ORDER BY executed_at DESC
            """,
                (operation_id,),
            )
            rows = cursor.fetchall()

        entries = []
        for row in rows:
            entries.append(
                DataLineageEntry(
                    id=UUID(row[0]),
                    operation_id=row[1],
                    table_name=row[2],
                    column_name=row[3],
                    strategy_name=row[4],
                    strategy_version=row[5],
                    rows_affected=row[6],
                    executed_by=row[7],
                    executed_at=row[8],
                    reason=row[9],
                    request_id=row[10],
                    department=row[11],
                    data_minimization_applied=row[12],
                    retention_days=row[13],
                    source_count=row[14],
                    target_count=row[15],
                    duration_seconds=row[16],
                    status=row[17],
                    error_message=row[18],
                    hmac_signature=row[19],
                    previous_entry_hash=row[20],
                    entry_hash=row[21],
                    verification_status=row[22],
                )
            )

        return entries


def sign_lineage_entry(entry: DataLineageEntry, secret: str | None = None) -> str:
    """Create HMAC signature for lineage entry (prevents tampering).

    The signature is computed over immutable fields of the entry.
    If the entry is modified after signing, the signature will
    no longer match, indicating tampering.

    Args:
        entry: DataLineageEntry to sign
        secret: Secret key for HMAC (default: LINEAGE_SECRET env var)

    Returns:
        HMAC-SHA256 signature as hex string

    Example:
        >>> entry = create_lineage_entry(...)
        >>> sig = sign_lineage_entry(entry, secret="my-secret")
        >>> # Later, verify by recomputing:
        >>> sig2 = sign_lineage_entry(modified_entry, secret="my-secret")
        >>> assert sig == sig2  # Should fail if entry was modified
    """
    import os

    if secret is None:
        secret = os.getenv("LINEAGE_SECRET", "default-lineage-secret")

    # Create deterministic JSON for signing
    # Include only immutable fields
    data = {
        "id": str(entry.id),
        "operation_id": entry.operation_id,
        "table_name": entry.table_name,
        "column_name": entry.column_name,
        "strategy_name": entry.strategy_name,
        "rows_affected": entry.rows_affected,
        "executed_by": entry.executed_by,
        "executed_at": entry.executed_at.isoformat(),
        "status": entry.status,
        "previous_entry_hash": entry.previous_entry_hash,
    }

    json_str = json.dumps(data, sort_keys=True)
    signature = hmac.new(
        secret.encode(),
        json_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    return signature


def verify_lineage_entry(entry: DataLineageEntry, secret: str | None = None) -> bool:
    """Verify HMAC signature of lineage entry (detect tampering).

    Args:
        entry: DataLineageEntry to verify
        secret: Secret key for HMAC (default: LINEAGE_SECRET env var)

    Returns:
        True if signature is valid, False otherwise

    Example:
        >>> entry = tracker.get_table_lineage("users")[0]
        >>> if verify_lineage_entry(entry, secret="my-secret"):
        ...     print("Entry is authentic")
        ... else:
        ...     print("Entry may have been tampered with!")
    """
    expected_sig = sign_lineage_entry(entry, secret)
    return entry.hmac_signature == expected_sig


def create_lineage_entry(
    operation_id: str,
    table_name: str,
    column_name: str,
    strategy_name: str,
    rows_affected: int = 0,
    executed_by: str = "system",
    reason: str | None = None,
    request_id: str | None = None,
    department: str | None = None,
    data_minimization_applied: bool = False,
    retention_days: int | None = None,
    source_count: int | None = None,
    target_count: int | None = None,
    duration_seconds: float = 0.0,
    status: str = "success",
    error_message: str | None = None,
    secret: str | None = None,
) -> DataLineageEntry:
    """Create and sign a lineage entry (convenience function).

    Args:
        operation_id: Operation identifier
        table_name: Table that was anonymized
        column_name: Column that was anonymized
        strategy_name: Anonymization strategy used
        rows_affected: Number of rows anonymized
        executed_by: User who executed the operation
        reason: Business reason for anonymization
        request_id: External request ID
        department: Department that requested anonymization
        data_minimization_applied: Whether data minimization was used
        retention_days: Data retention period
        source_count: Original row count
        target_count: Row count after anonymization
        duration_seconds: Operation duration
        status: Operation status (success, error, partial)
        error_message: Error message if operation failed
        secret: Secret key for signature (or LINEAGE_SECRET env var)

    Returns:
        Signed DataLineageEntry ready for logging

    Example:
        >>> entry = create_lineage_entry(
        ...     operation_id="anon-001",
        ...     table_name="users",
        ...     column_name="email",
        ...     strategy_name="tokenization",
        ...     rows_affected=1000,
        ...     executed_by="admin@example.com",
        ...     reason="GDPR compliance",
        ...     secret="lineage-secret"
        ... )
        >>> tracker.record_entry(entry)
    """
    entry = DataLineageEntry(
        id=uuid4(),
        operation_id=operation_id,
        table_name=table_name,
        column_name=column_name,
        strategy_name=strategy_name,
        rows_affected=rows_affected,
        executed_by=executed_by,
        executed_at=datetime.now(UTC),
        reason=reason,
        request_id=request_id,
        department=department,
        data_minimization_applied=data_minimization_applied,
        retention_days=retention_days,
        source_count=source_count,
        target_count=target_count,
        duration_seconds=duration_seconds,
        status=status,
        error_message=error_message,
        hmac_signature="",  # Will be computed by tracker
        previous_entry_hash=None,  # Will be set by tracker
        entry_hash="",  # Will be computed by tracker
        verification_status="unverified",  # Will be verified by tracker
    )

    # Sign the entry
    entry.hmac_signature = sign_lineage_entry(entry, secret)

    return entry
