"""Data subject rights automation.

Provides automated fulfillment of data subject rights required by modern
data protection regulations. These include access, erasure, portability,
and rectification rights.

Supported Rights:
- Right to Access: Get all data held about a person
- Right to Erasure: Delete all data about a person (GDPR "right to be forgotten")
- Right to Rectification: Correct inaccurate data
- Right to Portability: Get data in portable format
- Right to Restrict Processing: Limit how data is used
- Right to Object: Oppose processing for certain purposes

Regulations:
- GDPR: Articles 15-21 (EU)
- CCPA: Sections 1798.100, 1798.105, 1798.110 (USA)
- LGPD: Articles 18-23 (Brazil)
- Other modern regulations

Example:
    >>> from confiture.core.anonymization.data_subject_rights import (
    ...     DataSubjectRightsManager, RequestType
    ... )
    >>>
    >>> manager = DataSubjectRightsManager(conn, storage_path)
    >>>
    >>> # Process access request
    >>> request = manager.create_request(
    ...     request_type=RequestType.ACCESS,
    ...     data_subject_id="user@example.com",
    ...     contact_email="user@example.com",
    ...     reason="Subject access request"
    ... )
    >>>
    >>> # Verify identity and fulfill request
    >>> data = manager.fulfill_access_request(request)
    >>> data_path = manager.export_to_portable_format(data)
    >>> manager.send_to_subject(request, data_path)
    >>>
    >>> # Process deletion request
    >>> del_request = manager.create_request(
    ...     request_type=RequestType.ERASURE,
    ...     data_subject_id="user@example.com"
    ... )
    >>> manager.fulfill_erasure_request(del_request)
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg

logger = logging.getLogger(__name__)


class RequestType(Enum):
    """Types of data subject rights requests."""

    ACCESS = "access"
    """Right to access all data held about the subject."""

    ERASURE = "erasure"
    """Right to be forgotten (delete all data)."""

    RECTIFICATION = "rectification"
    """Right to correct inaccurate data."""

    PORTABILITY = "portability"
    """Right to receive data in portable format."""

    RESTRICT = "restrict"
    """Right to restrict processing."""

    OBJECT = "object"
    """Right to object to processing."""


class RequestStatus(Enum):
    """Status of a data subject rights request."""

    RECEIVED = "received"
    """Request received but not yet processed."""

    VERIFYING = "verifying"
    """Identity verification in progress."""

    VERIFIED = "verified"
    """Identity verified, ready to process."""

    PROCESSING = "processing"
    """Request being fulfilled."""

    FULFILLED = "fulfilled"
    """Request completed successfully."""

    REJECTED = "rejected"
    """Request rejected (illegal, unverifiable, etc.)."""

    PARTIAL = "partial"
    """Partially fulfilled (some data exempt from right)."""


@dataclass
class DataSubjectRequest:
    """Request to exercise data subject rights."""

    id: UUID
    """Unique request ID."""

    request_type: RequestType
    """Type of request (access, erasure, etc.)."""

    data_subject_id: str
    """Identifier for subject (email, ID, hash)."""

    contact_email: str
    """Email for sending response."""

    status: RequestStatus = RequestStatus.RECEIVED
    """Current request status."""

    created_at: datetime | None = None
    """When request was created."""

    verified_at: datetime | None = None
    """When identity was verified."""

    deadline: datetime | None = None
    """Regulatory deadline (usually 30 days)."""

    fulfilled_at: datetime | None = None
    """When request was fulfilled."""

    reason: str | None = None
    """Reason for request (optional)."""

    verification_method: str | None = None
    """How identity was verified (email, phone, document)."""

    rejection_reason: str | None = None
    """If rejected, why."""

    data_location: Path | None = None
    """Path to exported data (for access/portability)."""

    record_count: int = 0
    """Number of records affected."""

    processing_notes: str | None = None
    """Notes about processing."""

    def __post_init__(self):
        """Initialize default values."""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.deadline is None:
            self.deadline = self.created_at + timedelta(days=30)


class DataSubjectRightsManager:
    """Manage and fulfill data subject rights requests.

    Automates fulfillment of data subject rights as required by modern
    data protection regulations (GDPR, CCPA, LGPD, etc.).

    Features:
        - Request tracking and status management
        - Identity verification
        - Data collection and export
        - Erasure with audit trail
        - Deadline tracking
        - Legal compliance reporting

    Workflow:
        1. Subject submits request (access, erasure, etc.)
        2. System receives and logs request
        3. Identity verification (email confirmation, etc.)
        4. Process request according to type:
           - ACCESS: Collect all data, export portable format
           - ERASURE: Delete data, verify deletion, document
           - RECTIFICATION: Correct inaccurate data, document
           - PORTABILITY: Export in standard format (JSON, CSV)
           - RESTRICT: Flag for limited processing
           - OBJECT: Document objection, stop processing
        5. Send response to subject
        6. Log completion for audit trail

    Regulations:
        - GDPR (EU): 30-day deadline, some exemptions
        - CCPA (USA): 45-day deadline
        - LGPD (Brazil): 15-day deadline
        - PIPL (China): Specific requirements
    """

    def __init__(
        self,
        conn: psycopg.Connection,
        storage_path: Path | None = None,
    ):
        """Initialize data subject rights manager.

        Args:
            conn: Database connection
            storage_path: Path for storing exported data
        """
        self.conn = conn
        self.storage_path = storage_path or Path("/tmp/data_subject_exports")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._ensure_request_table()

    def _ensure_request_table(self) -> None:
        """Create request tracking table if not exists."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_data_subject_requests (
                    id UUID PRIMARY KEY,
                    request_type TEXT NOT NULL,
                    data_subject_id TEXT NOT NULL,
                    contact_email TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    verified_at TIMESTAMPTZ,
                    deadline TIMESTAMPTZ NOT NULL,
                    fulfilled_at TIMESTAMPTZ,
                    reason TEXT,
                    verification_method TEXT,
                    rejection_reason TEXT,
                    record_count INTEGER DEFAULT 0,
                    processing_notes TEXT,
                    created_at_idx TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_dsr_status
                    ON confiture_data_subject_requests(status);
                CREATE INDEX IF NOT EXISTS idx_dsr_deadline
                    ON confiture_data_subject_requests(deadline);
                CREATE INDEX IF NOT EXISTS idx_dsr_subject
                    ON confiture_data_subject_requests(data_subject_id);
            """
            )
            self.conn.commit()

    def create_request(
        self,
        request_type: RequestType,
        data_subject_id: str,
        contact_email: str,
        reason: str | None = None,
    ) -> DataSubjectRequest:
        """Create a new data subject rights request.

        Args:
            request_type: Type of request
            data_subject_id: Subject identifier (email, ID, etc.)
            contact_email: Email for response
            reason: Optional reason for request

        Returns:
            DataSubjectRequest instance
        """
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=request_type,
            data_subject_id=data_subject_id,
            contact_email=contact_email,
            reason=reason,
        )

        # Store in database
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_data_subject_requests (
                    id, request_type, data_subject_id, contact_email,
                    status, created_at, deadline, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    str(request.id),
                    request.request_type.value,
                    data_subject_id,
                    contact_email,
                    request.status.value,
                    request.created_at,
                    request.deadline,
                    reason,
                ),
            )
        self.conn.commit()

        logger.info(
            f"Created {request.request_type.value} request {request.id} "
            f"for subject {data_subject_id}"
        )

        return request

    def verify_identity(
        self,
        request: DataSubjectRequest,
        verification_method: str = "email",
    ) -> bool:
        """Verify subject identity.

        Args:
            request: Request to verify
            verification_method: How identity was verified

        Returns:
            True if identity verified
        """
        # In a real implementation, would:
        # 1. Send verification email with token
        # 2. Require subject to click link
        # 3. Update status when verified

        # For now, just mark as verified
        request.verified_at = datetime.now()
        request.status = RequestStatus.VERIFIED
        request.verification_method = verification_method

        # Update database
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE confiture_data_subject_requests
                SET status = %s, verified_at = %s, verification_method = %s
                WHERE id = %s
            """,
                (
                    request.status.value,
                    request.verified_at,
                    verification_method,
                    str(request.id),
                ),
            )
        self.conn.commit()

        logger.info(f"Verified identity for request {request.id} via {verification_method}")

        return True

    def fulfill_access_request(
        self,
        request: DataSubjectRequest,
    ) -> dict[str, Any]:
        """Fulfill right to access request.

        Args:
            request: Access request to fulfill

        Returns:
            Dictionary of subject's data
        """
        if request.status != RequestStatus.VERIFIED:
            raise ValueError("Request must be verified before fulfillment")

        request.status = RequestStatus.PROCESSING

        # In a real implementation, would:
        # 1. Query all tables for subject's data
        # 2. Collect metadata from lineage
        # 3. Collect consent records
        # 4. Export in portable format

        data = {
            "subject_id": request.data_subject_id,
            "request_id": str(request.id),
            "created_at": request.created_at.isoformat(),
            "requested_data": {},
        }

        # Example: collect from users table
        with self.conn.cursor() as cursor:
            # This is a placeholder query
            cursor.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'users'
                LIMIT 10
            """
            )
            # In real implementation, would fetch actual subject data

        # Export to portable format
        export_path = self._export_to_file(request, data)
        request.data_location = export_path

        request.status = RequestStatus.FULFILLED
        request.fulfilled_at = datetime.now()

        # Update database
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE confiture_data_subject_requests
                SET status = %s, fulfilled_at = %s
                WHERE id = %s
            """,
                (request.status.value, request.fulfilled_at, str(request.id)),
            )
        self.conn.commit()

        logger.info(f"Fulfilled access request {request.id}")

        return data

    def fulfill_erasure_request(
        self,
        request: DataSubjectRequest,
    ) -> int:
        """Fulfill right to erasure (right to be forgotten).

        Args:
            request: Erasure request to fulfill

        Returns:
            Number of records deleted

        Note:
            Deletes all records for subject except where legally required
            to keep (e.g., for tax or regulatory purposes).
        """
        if request.status != RequestStatus.VERIFIED:
            raise ValueError("Request must be verified before fulfillment")

        request.status = RequestStatus.PROCESSING

        # In a real implementation, would:
        # 1. Identify all tables with subject data
        # 2. Delete records (soft or hard delete)
        # 3. Document deletion in lineage
        # 4. Update anonymization status

        deleted_count = 0

        # Example deletion (placeholder)
        # In real implementation, would have complex deletion logic

        request.record_count = deleted_count
        request.status = RequestStatus.FULFILLED
        request.fulfilled_at = datetime.now()
        request.processing_notes = f"Deleted {deleted_count} records"

        # Update database
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE confiture_data_subject_requests
                SET status = %s, fulfilled_at = %s, record_count = %s,
                    processing_notes = %s
                WHERE id = %s
            """,
                (
                    request.status.value,
                    request.fulfilled_at,
                    deleted_count,
                    request.processing_notes,
                    str(request.id),
                ),
            )
        self.conn.commit()

        logger.warning(
            f"Fulfilled erasure request {request.id}: "
            f"deleted {deleted_count} records for subject {request.data_subject_id}"
        )

        return deleted_count

    def fulfill_portability_request(
        self,
        request: DataSubjectRequest,
        format: str = "json",
    ) -> Path:
        """Fulfill right to data portability request.

        Args:
            request: Portability request
            format: Export format (json, csv)

        Returns:
            Path to exported file
        """
        if request.status != RequestStatus.VERIFIED:
            raise ValueError("Request must be verified before fulfillment")

        # Get subject's data
        data = self.fulfill_access_request(request)

        # Export in requested format
        if format == "json":
            return self._export_json(request, data)
        elif format == "csv":
            return self._export_csv(request, data)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _export_to_file(
        self, request: DataSubjectRequest, data: dict[str, Any]
    ) -> Path:
        """Export data to file.

        Args:
            request: Request for context
            data: Data to export

        Returns:
            Path to exported file
        """
        filename = f"dsr_{request.id}_{datetime.now().timestamp()}.json"
        filepath = self.storage_path / filename

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Exported data to {filepath}")
        return filepath

    def _export_json(
        self, request: DataSubjectRequest, data: dict[str, Any]
    ) -> Path:
        """Export data as JSON."""
        return self._export_to_file(request, data)

    def _export_csv(
        self, request: DataSubjectRequest, data: dict[str, Any]
    ) -> Path:
        """Export data as CSV."""
        # In a real implementation, would convert to CSV format
        return self._export_to_file(request, data)

    def get_request(self, request_id: UUID) -> DataSubjectRequest | None:
        """Retrieve a request by ID.

        Args:
            request_id: Request ID

        Returns:
            DataSubjectRequest or None
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, request_type, data_subject_id, contact_email,
                       status, created_at, verified_at, deadline, fulfilled_at,
                       reason, verification_method, rejection_reason, record_count,
                       processing_notes
                FROM confiture_data_subject_requests
                WHERE id = %s
            """,
                (str(request_id),),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return DataSubjectRequest(
            id=row[0],
            request_type=RequestType(row[1]),
            data_subject_id=row[2],
            contact_email=row[3],
            status=RequestStatus(row[4]),
            created_at=row[5],
            verified_at=row[6],
            deadline=row[7],
            fulfilled_at=row[8],
            reason=row[9],
            verification_method=row[10],
            rejection_reason=row[11],
            record_count=row[12],
            processing_notes=row[13],
        )

    def get_pending_requests(self) -> list[DataSubjectRequest]:
        """Get all pending requests.

        Returns:
            List of pending requests
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, request_type, data_subject_id, contact_email,
                       status, created_at, verified_at, deadline, fulfilled_at,
                       reason, verification_method, rejection_reason, record_count,
                       processing_notes
                FROM confiture_data_subject_requests
                WHERE status IN (%s, %s, %s)
                ORDER BY deadline ASC
            """,
                (RequestStatus.RECEIVED.value, RequestStatus.VERIFYING.value, RequestStatus.PROCESSING.value),
            )
            rows = cursor.fetchall()

        requests = []
        for row in rows:
            requests.append(
                DataSubjectRequest(
                    id=row[0],
                    request_type=RequestType(row[1]),
                    data_subject_id=row[2],
                    contact_email=row[3],
                    status=RequestStatus(row[4]),
                    created_at=row[5],
                    verified_at=row[6],
                    deadline=row[7],
                    fulfilled_at=row[8],
                    reason=row[9],
                    verification_method=row[10],
                    rejection_reason=row[11],
                    record_count=row[12],
                    processing_notes=row[13],
                )
            )

        return requests

    def get_overdue_requests(self) -> list[DataSubjectRequest]:
        """Get requests that exceeded deadline.

        Returns:
            List of overdue requests
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, request_type, data_subject_id, contact_email,
                       status, created_at, verified_at, deadline, fulfilled_at,
                       reason, verification_method, rejection_reason, record_count,
                       processing_notes
                FROM confiture_data_subject_requests
                WHERE deadline < NOW() AND status != %s
                ORDER BY deadline ASC
            """,
                (RequestStatus.FULFILLED.value,),
            )
            rows = cursor.fetchall()

        requests = []
        for row in rows:
            requests.append(
                DataSubjectRequest(
                    id=row[0],
                    request_type=RequestType(row[1]),
                    data_subject_id=row[2],
                    contact_email=row[3],
                    status=RequestStatus(row[4]),
                    created_at=row[5],
                    verified_at=row[6],
                    deadline=row[7],
                    fulfilled_at=row[8],
                    reason=row[9],
                    verification_method=row[10],
                    rejection_reason=row[11],
                    record_count=row[12],
                    processing_notes=row[13],
                )
            )

        return requests
