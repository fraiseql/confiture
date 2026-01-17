"""Comprehensive tests for data subject rights management.

Tests the DataSubjectRightsManager and related classes for fulfilling
data subject rights requests (access, erasure, rectification, portability).
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest

from confiture.core.anonymization.data_subject_rights import (
    DataSubjectRequest,
    DataSubjectRightsManager,
    RequestStatus,
    RequestType,
)


class TestRequestType:
    """Test RequestType enum."""

    def test_request_type_access(self):
        """Test ACCESS request type."""
        assert RequestType.ACCESS.value == "access"

    def test_request_type_erasure(self):
        """Test ERASURE request type."""
        assert RequestType.ERASURE.value == "erasure"

    def test_request_type_rectification(self):
        """Test RECTIFICATION request type."""
        assert RequestType.RECTIFICATION.value == "rectification"

    def test_request_type_portability(self):
        """Test PORTABILITY request type."""
        assert RequestType.PORTABILITY.value == "portability"

    def test_request_type_restrict(self):
        """Test RESTRICT request type."""
        assert RequestType.RESTRICT.value == "restrict"

    def test_request_type_object(self):
        """Test OBJECT request type."""
        assert RequestType.OBJECT.value == "object"

    def test_all_request_types(self):
        """Test all request types are defined."""
        types = [
            RequestType.ACCESS,
            RequestType.ERASURE,
            RequestType.RECTIFICATION,
            RequestType.PORTABILITY,
            RequestType.RESTRICT,
            RequestType.OBJECT,
        ]
        assert len(types) == 6


class TestRequestStatus:
    """Test RequestStatus enum."""

    def test_status_received(self):
        """Test RECEIVED status."""
        assert RequestStatus.RECEIVED.value == "received"

    def test_status_verifying(self):
        """Test VERIFYING status."""
        assert RequestStatus.VERIFYING.value == "verifying"

    def test_status_verified(self):
        """Test VERIFIED status."""
        assert RequestStatus.VERIFIED.value == "verified"

    def test_status_processing(self):
        """Test PROCESSING status."""
        assert RequestStatus.PROCESSING.value == "processing"

    def test_status_fulfilled(self):
        """Test FULFILLED status."""
        assert RequestStatus.FULFILLED.value == "fulfilled"

    def test_status_rejected(self):
        """Test REJECTED status."""
        assert RequestStatus.REJECTED.value == "rejected"

    def test_status_partial(self):
        """Test PARTIAL status."""
        assert RequestStatus.PARTIAL.value == "partial"

    def test_all_statuses(self):
        """Test all statuses are defined."""
        statuses = [
            RequestStatus.RECEIVED,
            RequestStatus.VERIFYING,
            RequestStatus.VERIFIED,
            RequestStatus.PROCESSING,
            RequestStatus.FULFILLED,
            RequestStatus.REJECTED,
            RequestStatus.PARTIAL,
        ]
        assert len(statuses) == 7


class TestDataSubjectRequest:
    """Test DataSubjectRequest dataclass."""

    def test_create_request_minimal(self):
        """Test creating request with minimal fields."""
        request_id = uuid4()
        request = DataSubjectRequest(
            id=request_id,
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.id == request_id
        assert request.request_type == RequestType.ACCESS
        assert request.data_subject_id == "user@example.com"
        assert request.contact_email == "user@example.com"
        assert request.status == RequestStatus.RECEIVED

    def test_create_request_with_reason(self):
        """Test creating request with reason."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            reason="User requested deletion",
        )

        assert request.reason == "User requested deletion"

    def test_create_request_sets_created_at(self):
        """Test that created_at is set automatically."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.created_at is not None
        assert isinstance(request.created_at, datetime)

    def test_create_request_sets_deadline(self):
        """Test that deadline is set to 30 days from creation."""
        now = datetime.now()
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        # Deadline should be approximately 30 days from now
        expected_deadline = now + timedelta(days=30)
        delta = abs((request.deadline - expected_deadline).total_seconds())
        assert delta < 5  # Allow 5 second tolerance

    def test_create_request_custom_deadline(self):
        """Test creating request with custom deadline."""
        custom_deadline = datetime.now() + timedelta(days=45)
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            deadline=custom_deadline,
        )

        assert request.deadline == custom_deadline

    def test_request_status_transitions(self):
        """Test status field transitions."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.status == RequestStatus.RECEIVED
        request.status = RequestStatus.VERIFYING
        assert request.status == RequestStatus.VERIFYING
        request.status = RequestStatus.VERIFIED
        assert request.status == RequestStatus.VERIFIED

    def test_request_with_verification_info(self):
        """Test request with verification details."""
        verified_at = datetime.now()
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            verified_at=verified_at,
            verification_method="email",
        )

        assert request.verified_at == verified_at
        assert request.verification_method == "email"

    def test_request_with_fulfillment_info(self):
        """Test request with fulfillment details."""
        fulfilled_at = datetime.now()
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            status=RequestStatus.FULFILLED,
            fulfilled_at=fulfilled_at,
            record_count=42,
        )

        assert request.status == RequestStatus.FULFILLED
        assert request.fulfilled_at == fulfilled_at
        assert request.record_count == 42

    def test_request_with_rejection_info(self):
        """Test request with rejection details."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            status=RequestStatus.REJECTED,
            rejection_reason="Identity verification failed",
        )

        assert request.status == RequestStatus.REJECTED
        assert request.rejection_reason == "Identity verification failed"

    def test_request_with_processing_notes(self):
        """Test request with processing notes."""
        notes = "Found 15 records to delete, 3 records exempt due to legal hold"
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            processing_notes=notes,
        )

        assert request.processing_notes == notes

    def test_request_different_types(self):
        """Test requests of different types."""
        for request_type in RequestType:
            request = DataSubjectRequest(
                id=uuid4(),
                request_type=request_type,
                data_subject_id="user@example.com",
                contact_email="user@example.com",
            )
            assert request.request_type == request_type

    def test_request_uuid_persistence(self):
        """Test that request UUID is persisted correctly."""
        test_id = uuid4()
        request = DataSubjectRequest(
            id=test_id,
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.id == test_id
        assert isinstance(request.id, UUID)

    def test_request_data_location_path(self):
        """Test storing data location path."""
        path = Path("/tmp/user_data_123.zip")
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.PORTABILITY,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            data_location=path,
        )

        assert request.data_location == path
        assert isinstance(request.data_location, Path)


class TestDataSubjectRightsManager:
    """Test DataSubjectRightsManager class."""

    @pytest.fixture
    def mock_conn(self):
        """Fixture for mocked database connection."""
        mock = MagicMock()
        mock.cursor.return_value.__enter__ = Mock(return_value=Mock())
        mock.cursor.return_value.__exit__ = Mock(return_value=None)
        return mock

    def test_manager_init(self, mock_conn):
        """Test manager initialization."""
        storage_path = Path("/tmp/data_exports")

        manager = DataSubjectRightsManager(mock_conn, storage_path)

        assert manager.conn == mock_conn
        assert manager.storage_path == storage_path

    def test_create_access_request(self, mock_conn):
        """Test creating access request."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        request = manager.create_request(
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
            reason="Subject access request",
        )

        assert request.request_type == RequestType.ACCESS
        assert request.data_subject_id == "user@example.com"
        assert request.contact_email == "user@example.com"
        assert request.reason == "Subject access request"
        assert request.status == RequestStatus.RECEIVED

    def test_create_erasure_request(self, mock_conn):
        """Test creating erasure request."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        request = manager.create_request(
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.request_type == RequestType.ERASURE
        assert request.status == RequestStatus.RECEIVED

    def test_create_portability_request(self, mock_conn):
        """Test creating portability request."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        request = manager.create_request(
            request_type=RequestType.PORTABILITY,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        assert request.request_type == RequestType.PORTABILITY
        assert request.status == RequestStatus.RECEIVED

    def test_manager_request_tracking(self, mock_conn):
        """Test manager tracks multiple requests."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        request1 = manager.create_request(
            request_type=RequestType.ACCESS,
            data_subject_id="user1@example.com",
            contact_email="user1@example.com",
        )

        request2 = manager.create_request(
            request_type=RequestType.ERASURE,
            data_subject_id="user2@example.com",
            contact_email="user2@example.com",
        )

        assert request1.id != request2.id
        assert request1.data_subject_id != request2.data_subject_id

    def test_request_deadline_compliance(self, mock_conn):
        """Test that requests have GDPR-compliant 30-day deadline."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        request = manager.create_request(
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        # Deadline should be approximately 30 days
        delta_days = (request.deadline - request.created_at).days
        assert delta_days == 30

    def test_request_has_unique_id(self, mock_conn):
        """Test that each request has unique ID."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        requests = [
            manager.create_request(
                request_type=RequestType.ACCESS,
                data_subject_id=f"user{i}@example.com",
                contact_email=f"user{i}@example.com",
            )
            for i in range(5)
        ]

        ids = [r.id for r in requests]
        assert len(ids) == len(set(ids))  # All IDs should be unique

    def test_request_type_enum_coverage(self, mock_conn):
        """Test creating requests of all types."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        for request_type in RequestType:
            request = manager.create_request(
                request_type=request_type,
                data_subject_id="user@example.com",
                contact_email="user@example.com",
            )
            assert request.request_type == request_type

    def test_storage_path_configuration(self, mock_conn):
        """Test storage path configuration."""
        path1 = Path("/tmp/path1")
        path2 = Path("/tmp/path2")

        manager1 = DataSubjectRightsManager(mock_conn, path1)
        manager2 = DataSubjectRightsManager(mock_conn, path2)

        assert manager1.storage_path == path1
        assert manager2.storage_path == path2
        assert manager1.storage_path != manager2.storage_path


class TestDataSubjectRequestIntegration:
    """Integration tests for data subject requests."""

    @pytest.fixture
    def mock_conn(self):
        """Fixture for mocked database connection."""
        mock = MagicMock()
        mock.cursor.return_value.__enter__ = Mock(return_value=Mock())
        mock.cursor.return_value.__exit__ = Mock(return_value=None)
        return mock

    def test_request_lifecycle(self):
        """Test complete request lifecycle."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        # Initial state
        assert request.status == RequestStatus.RECEIVED
        assert request.verified_at is None

        # Verification
        request.status = RequestStatus.VERIFYING
        request.verified_at = datetime.now()
        request.verification_method = "email"
        request.status = RequestStatus.VERIFIED

        assert request.status == RequestStatus.VERIFIED
        assert request.verification_method == "email"

        # Processing
        request.status = RequestStatus.PROCESSING

        # Fulfillment
        request.status = RequestStatus.FULFILLED
        request.fulfilled_at = datetime.now()
        request.record_count = 42
        request.data_location = Path("/tmp/user_data.zip")

        assert request.status == RequestStatus.FULFILLED
        assert request.record_count == 42
        assert request.data_location is not None

    def test_request_rejection_lifecycle(self):
        """Test request lifecycle with rejection."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        request.status = RequestStatus.VERIFYING
        request.verified_at = datetime.now()

        # Failed verification leads to rejection
        request.status = RequestStatus.REJECTED
        request.rejection_reason = "Identity verification failed"

        assert request.status == RequestStatus.REJECTED
        assert request.rejection_reason is not None

    def test_request_partial_fulfillment(self):
        """Test partial fulfillment scenario."""
        request = DataSubjectRequest(
            id=uuid4(),
            request_type=RequestType.ERASURE,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )

        request.status = RequestStatus.PROCESSING
        request.processing_notes = "15 records deleted, 3 records retained due to legal hold"
        request.status = RequestStatus.PARTIAL
        request.fulfilled_at = datetime.now()
        request.record_count = 15

        assert request.status == RequestStatus.PARTIAL
        assert "legal hold" in request.processing_notes

    def test_manager_request_creation_timestamps(self, mock_conn):
        """Test that manager-created requests have valid timestamps."""
        storage_path = Path("/tmp/data_exports")
        manager = DataSubjectRightsManager(mock_conn, storage_path)

        before = datetime.now()
        request = manager.create_request(
            request_type=RequestType.ACCESS,
            data_subject_id="user@example.com",
            contact_email="user@example.com",
        )
        after = datetime.now()

        assert before <= request.created_at <= after
        assert before <= request.deadline <= after + timedelta(days=31)
