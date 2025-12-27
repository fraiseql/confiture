"""Tests for immutable audit logging system.

Tests cover:
- AuditEntry creation and serialization
- Append-only constraints
- HMAC signature verification
- Tamper detection
- Database operations
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from confiture.core.anonymization.audit import (
    AuditEntry,
    AuditLogger,
    create_audit_entry,
    sign_audit_entry,
    verify_audit_entry,
)


class TestAuditEntryCreation:
    """Test AuditEntry dataclass creation and validation."""

    def test_create_minimal_entry(self):
        """Create minimal audit entry."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="sig123",
        )
        assert entry.user == "admin"
        assert entry.profile_name == "test"
        assert entry.verification_passed is True

    def test_entry_with_multiple_tables(self):
        """Create entry with multiple tables."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users", "orders", "payments"],
            rows_anonymized={"users": 1000, "orders": 5000, "payments": 2000},
            strategies_applied={"email": 1000, "phone": 1000, "hash": 5000},
            verification_passed=True,
            verification_report="{}",
            signature="sig123",
        )
        assert len(entry.tables_synced) == 3
        assert sum(entry.rows_anonymized.values()) == 8000

    def test_entry_with_verification_failure(self):
        """Create entry recording verification failure."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=False,
            verification_report='{"error": "FK constraint violation"}',
            signature="sig123",
        )
        assert entry.verification_passed is False


class TestAuditEntrySerialization:
    """Test AuditEntry serialization to/from JSON."""

    def test_to_json(self):
        """Serialize entry to JSON."""
        entry_id = uuid4()
        timestamp = datetime.now(UTC)
        entry = AuditEntry(
            id=entry_id,
            timestamp=timestamp,
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="sig123",
        )

        json_str = entry.to_json()
        data = json.loads(json_str)

        assert data["id"] == str(entry_id)
        assert data["user"] == "admin"
        assert data["profile_name"] == "test"
        assert data["verification_passed"] is True

    def test_from_json(self):
        """Deserialize entry from JSON."""
        json_str = """{
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "timestamp": "2025-12-27T10:30:00+00:00",
            "user": "admin@example.com",
            "hostname": "sync-server",
            "source_database": "prod",
            "target_database": "staging",
            "profile_name": "production",
            "profile_version": "1.0",
            "profile_hash": "abc123def456",
            "tables_synced": ["users", "orders"],
            "rows_anonymized": {"users": 1000, "orders": 5000},
            "strategies_applied": {"email": 1000, "phone": 1000},
            "verification_passed": true,
            "verification_report": "{}",
            "signature": "hmac_sig"
        }"""

        entry = AuditEntry.from_json(json_str)
        assert entry.user == "admin@example.com"
        assert entry.profile_name == "production"
        assert len(entry.tables_synced) == 2

    def test_json_roundtrip(self):
        """Serialize and deserialize preserves data."""
        original_id = uuid4()
        original_timestamp = datetime.now(UTC)
        original = AuditEntry(
            id=original_id,
            timestamp=original_timestamp,
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users", "orders"],
            rows_anonymized={"users": 100, "orders": 200},
            strategies_applied={"email": 100, "phone": 200},
            verification_passed=True,
            verification_report="{}",
            signature="sig123",
        )

        json_str = original.to_json()
        restored = AuditEntry.from_json(json_str)

        assert restored.id == original_id
        assert restored.user == "admin"
        assert restored.tables_synced == ["users", "orders"]


class TestAuditSignature:
    """Test HMAC signature creation and verification."""

    def test_sign_entry(self):
        """Create signature for entry."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="",
        )

        sig = sign_audit_entry(entry, secret="test-secret")
        assert len(sig) == 64  # SHA256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in sig)

    def test_signature_changes_with_different_secret(self):
        """Different secrets produce different signatures."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="",
        )

        sig1 = sign_audit_entry(entry, secret="secret1")
        sig2 = sign_audit_entry(entry, secret="secret2")

        assert sig1 != sig2

    def test_signature_is_deterministic(self):
        """Same entry and secret produce same signature."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="",
        )

        sig1 = sign_audit_entry(entry, secret="secret")
        sig2 = sign_audit_entry(entry, secret="secret")

        assert sig1 == sig2

    def test_verify_valid_signature(self):
        """Valid signature verifies successfully."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="placeholder",
        )

        entry.signature = sign_audit_entry(entry, secret="secret")
        assert verify_audit_entry(entry, secret="secret") is True

    def test_verify_fails_with_wrong_secret(self):
        """Verification fails if secret changed."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="placeholder",
        )

        entry.signature = sign_audit_entry(entry, secret="secret1")
        assert verify_audit_entry(entry, secret="secret2") is False

    def test_tamper_detection_user_field(self):
        """Signature fails if user field modified."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="placeholder",
        )

        entry.signature = sign_audit_entry(entry, secret="secret")

        # Modify user field
        entry.user = "hacker"
        assert verify_audit_entry(entry, secret="secret") is False

    def test_tamper_detection_profile_hash(self):
        """Signature fails if profile_hash modified."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="placeholder",
        )

        entry.signature = sign_audit_entry(entry, secret="secret")

        # Modify profile hash
        entry.profile_hash = "modified"
        assert verify_audit_entry(entry, secret="secret") is False

    def test_tamper_detection_verification_passed(self):
        """Signature fails if verification_passed modified."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            user="admin",
            hostname="localhost",
            source_database="prod",
            target_database="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables_synced=["users"],
            rows_anonymized={"users": 100},
            strategies_applied={"email": 100},
            verification_passed=True,
            verification_report="{}",
            signature="placeholder",
        )

        entry.signature = sign_audit_entry(entry, secret="secret")

        # Modify verification_passed
        entry.verification_passed = False
        assert verify_audit_entry(entry, secret="secret") is False


class TestCreateAuditEntry:
    """Test convenience function for creating entries."""

    def test_create_entry_with_defaults(self):
        """Create entry using convenience function."""
        entry = create_audit_entry(
            user="admin@example.com",
            source_db="prod",
            target_db="staging",
            profile_name="production",
            profile_version="1.0",
            profile_hash="abc123",
            tables=["users"],
            rows_by_table={"users": 100},
            strategies_by_type={"email": 100},
            verification_passed=True,
            secret="test-secret",
        )

        assert entry.user == "admin@example.com"
        assert entry.profile_name == "production"
        assert entry.verification_passed is True
        # Hostname should be set automatically
        assert entry.hostname != ""
        # Signature should be computed
        assert len(entry.signature) == 64

    def test_created_entry_is_signed(self):
        """Entry created with function is signed."""
        entry = create_audit_entry(
            user="admin",
            source_db="prod",
            target_db="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables=["users"],
            rows_by_table={"users": 100},
            strategies_by_type={"email": 100},
            verification_passed=True,
            secret="secret",
        )

        # Should verify successfully
        assert verify_audit_entry(entry, secret="secret") is True

    def test_created_entry_is_tamperable(self):
        """Signature fails if created entry is modified."""
        entry = create_audit_entry(
            user="admin",
            source_db="prod",
            target_db="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables=["users"],
            rows_by_table={"users": 100},
            strategies_by_type={"email": 100},
            verification_passed=True,
            secret="secret",
        )

        original_sig = entry.signature

        # Modify entry
        entry.user = "hacker"

        # Signature should no longer match
        assert verify_audit_entry(entry, secret="secret") is False
        # But original signature is unchanged
        assert entry.signature == original_sig


class TestAuditLoggerDatabase:
    """Test AuditLogger database operations (requires test DB)."""

    def test_audit_logger_init(self, target_db):
        """AuditLogger initializes and creates table."""
        logger = AuditLogger(target_db)
        assert logger.conn is not None

        # Verify table exists
        with target_db.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'confiture_audit_log'
                )
            """
            )
            exists = cursor.fetchone()[0]
            assert exists is True

    def test_audit_logger_is_idempotent(self, target_db):
        """Creating AuditLogger multiple times is safe."""
        logger1 = AuditLogger(target_db)
        logger2 = AuditLogger(target_db)

        assert logger1.conn is not None
        assert logger2.conn is not None

    def test_log_single_entry(self, target_db):
        """Log a single audit entry."""
        logger = AuditLogger(target_db)

        entry = create_audit_entry(
            user="admin",
            source_db="prod",
            target_db="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables=["users"],
            rows_by_table={"users": 100},
            strategies_by_type={"email": 100},
            verification_passed=True,
            secret="secret",
        )

        logger.log_sync(entry)

        # Verify entry was logged
        logged = logger.get_audit_log(limit=1)
        assert len(logged) == 1
        assert logged[0].user == "admin"

    def test_log_multiple_entries(self, target_db):
        """Log multiple audit entries."""
        logger = AuditLogger(target_db)

        for i in range(5):
            entry = create_audit_entry(
                user=f"user{i}",
                source_db="prod",
                target_db="staging",
                profile_name="test",
                profile_version="1.0",
                profile_hash="abc123",
                tables=["users"],
                rows_by_table={"users": 100},
                strategies_by_type={"email": 100},
                verification_passed=True,
                secret="secret",
            )
            logger.log_sync(entry)

        # Retrieve all entries
        all_entries = logger.get_audit_log(limit=10)
        assert len(all_entries) == 5

    def test_get_audit_log_ordered(self, target_db):
        """Audit log returns entries in reverse chronological order."""
        logger = AuditLogger(target_db)

        # Create entries with small time differences
        entries = []
        for i in range(3):
            entry = create_audit_entry(
                user=f"user{i}",
                source_db="prod",
                target_db="staging",
                profile_name="test",
                profile_version="1.0",
                profile_hash="abc123",
                tables=["users"],
                rows_by_table={"users": 100},
                strategies_by_type={"email": 100},
                verification_passed=True,
                secret="secret",
            )
            logger.log_sync(entry)
            entries.append(entry)

        # Retrieve entries
        logged = logger.get_audit_log(limit=10)

        # Should be in reverse order (newest first)
        assert len(logged) >= 3
        assert logged[0].user == "user2"

    def test_audit_entries_preserve_signature(self, target_db):
        """Signatures are preserved through database storage."""
        logger = AuditLogger(target_db)

        entry = create_audit_entry(
            user="admin",
            source_db="prod",
            target_db="staging",
            profile_name="test",
            profile_version="1.0",
            profile_hash="abc123",
            tables=["users"],
            rows_by_table={"users": 100},
            strategies_by_type={"email": 100},
            verification_passed=True,
            secret="secret",
        )

        original_sig = entry.signature
        logger.log_sync(entry)

        # Retrieve and verify
        logged = logger.get_audit_log(limit=1)
        assert logged[0].signature == original_sig
        assert verify_audit_entry(logged[0], secret="secret") is True
