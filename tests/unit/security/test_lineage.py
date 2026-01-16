"""Comprehensive tests for data lineage tracking with HMAC signatures.

Tests cover:
- DataLineageEntry dataclass
- sign_lineage_entry and verify_lineage_entry functions
- create_lineage_entry convenience function
- Serialization/deserialization (JSON)
- HMAC signature verification
"""

import json
import os
import pytest
from datetime import datetime, timezone, UTC
from uuid import UUID, uuid4
from unittest.mock import Mock, patch, MagicMock

from confiture.core.anonymization.security.lineage import (
    DataLineageEntry,
    sign_lineage_entry,
    verify_lineage_entry,
    create_lineage_entry,
)


class TestDataLineageEntry:
    """Tests for DataLineageEntry dataclass."""

    def test_create_minimal_entry(self):
        """Test creating entry with minimal required fields."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="op-001",
            table_name="users",
            column_name="email",
            strategy_name="tokenization",
        )

        assert entry.operation_id == "op-001"
        assert entry.table_name == "users"
        assert entry.column_name == "email"
        assert entry.strategy_name == "tokenization"

    def test_entry_default_values(self):
        """Test entry default values."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="op-001",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
        )

        assert entry.strategy_version == "1.0"
        assert entry.rows_affected == 0
        assert entry.executed_by == "system"
        assert entry.reason is None
        assert entry.request_id is None
        assert entry.department is None
        assert entry.data_minimization_applied is False
        assert entry.retention_days is None
        assert entry.status == "success"
        assert entry.error_message is None
        assert entry.hmac_signature == ""
        assert entry.previous_entry_hash is None
        assert entry.entry_hash == ""
        assert entry.verification_status == "unverified"

    def test_entry_post_init_sets_executed_at(self):
        """Test __post_init__ sets executed_at to now if None."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="op-001",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
        )

        assert entry.executed_at is not None
        assert isinstance(entry.executed_at, datetime)

    def test_entry_with_all_fields(self):
        """Test creating entry with all fields."""
        entry_id = uuid4()
        now = datetime.now(UTC)

        entry = DataLineageEntry(
            id=entry_id,
            operation_id="op-complete",
            table_name="orders",
            column_name="credit_card",
            strategy_name="tokenization",
            strategy_version="2.0",
            rows_affected=1500,
            executed_by="admin@example.com",
            executed_at=now,
            reason="PCI DSS compliance",
            request_id="TICKET-12345",
            department="Security",
            data_minimization_applied=True,
            retention_days=90,
            source_count=2000,
            target_count=1500,
            duration_seconds=45.5,
            status="partial",
            error_message="500 rows skipped due to validation",
            hmac_signature="abc123",
            previous_entry_hash="def456",
            entry_hash="ghi789",
            verification_status="verified",
        )

        assert entry.id == entry_id
        assert entry.rows_affected == 1500
        assert entry.executed_by == "admin@example.com"
        assert entry.reason == "PCI DSS compliance"
        assert entry.department == "Security"
        assert entry.data_minimization_applied is True
        assert entry.retention_days == 90
        assert entry.status == "partial"


class TestDataLineageEntrySerialization:
    """Tests for DataLineageEntry JSON serialization."""

    def test_to_json(self):
        """Test serializing entry to JSON."""
        entry_id = uuid4()
        now = datetime.now(UTC)

        entry = DataLineageEntry(
            id=entry_id,
            operation_id="op-001",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
            executed_at=now,
        )

        json_str = entry.to_json()
        data = json.loads(json_str)

        assert data["id"] == str(entry_id)
        assert data["operation_id"] == "op-001"
        assert data["table_name"] == "users"
        assert data["executed_at"] == now.isoformat()

    def test_from_json(self):
        """Test deserializing entry from JSON."""
        entry_id = uuid4()
        now = datetime.now(UTC)

        original = DataLineageEntry(
            id=entry_id,
            operation_id="op-json",
            table_name="products",
            column_name="price",
            strategy_name="rounding",
            rows_affected=500,
            executed_at=now,
        )

        json_str = original.to_json()
        restored = DataLineageEntry.from_json(json_str)

        assert restored.id == entry_id
        assert restored.operation_id == "op-json"
        assert restored.table_name == "products"
        assert restored.rows_affected == 500

    def test_from_json_invalid(self):
        """Test from_json with invalid JSON."""
        with pytest.raises(ValueError, match="Invalid lineage entry"):
            DataLineageEntry.from_json("not valid json")

    def test_from_json_missing_fields(self):
        """Test from_json with missing required fields."""
        with pytest.raises(ValueError, match="Invalid lineage entry"):
            DataLineageEntry.from_json('{"operation_id": "op-001"}')

    def test_roundtrip_serialization(self):
        """Test JSON roundtrip preserves all fields."""
        original = DataLineageEntry(
            id=uuid4(),
            operation_id="roundtrip-test",
            table_name="customers",
            column_name="ssn",
            strategy_name="masking",
            rows_affected=1000,
            executed_by="batch@system",
            reason="GDPR Art. 17",
            request_id="REQ-999",
            department="Legal",
            data_minimization_applied=True,
            retention_days=365,
            source_count=1200,
            target_count=1000,
            duration_seconds=12.5,
            status="success",
        )

        restored = DataLineageEntry.from_json(original.to_json())

        assert restored.operation_id == original.operation_id
        assert restored.rows_affected == original.rows_affected
        assert restored.reason == original.reason
        assert restored.department == original.department


class TestSignLineageEntry:
    """Tests for sign_lineage_entry function."""

    @pytest.fixture
    def sample_entry(self):
        """Create sample entry for signing tests."""
        return DataLineageEntry(
            id=uuid4(),
            operation_id="sign-test",
            table_name="users",
            column_name="email",
            strategy_name="tokenization",
            rows_affected=100,
            executed_by="admin",
            executed_at=datetime.now(UTC),
        )

    def test_sign_returns_signature(self, sample_entry):
        """Test sign_lineage_entry returns signature string."""
        signature = sign_lineage_entry(sample_entry, secret="test-secret")

        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex

    def test_sign_deterministic(self, sample_entry):
        """Test signing is deterministic with same secret."""
        sig1 = sign_lineage_entry(sample_entry, secret="test-secret")
        sig2 = sign_lineage_entry(sample_entry, secret="test-secret")

        assert sig1 == sig2

    def test_sign_different_secrets_different_signatures(self, sample_entry):
        """Test different secrets produce different signatures."""
        sig1 = sign_lineage_entry(sample_entry, secret="secret-1")
        sig2 = sign_lineage_entry(sample_entry, secret="secret-2")

        assert sig1 != sig2

    def test_sign_modified_entry_different_signature(self):
        """Test modified entry produces different signature."""
        entry1 = DataLineageEntry(
            id=uuid4(),
            operation_id="test",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
            rows_affected=100,
        )

        entry2 = DataLineageEntry(
            id=entry1.id,
            operation_id="test",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
            rows_affected=200,  # Modified!
        )

        sig1 = sign_lineage_entry(entry1, secret="test")
        sig2 = sign_lineage_entry(entry2, secret="test")

        assert sig1 != sig2

    def test_sign_uses_env_var_default(self, sample_entry):
        """Test signing uses LINEAGE_SECRET env var by default."""
        with patch.dict(os.environ, {"LINEAGE_SECRET": "env-secret"}):
            sig_env = sign_lineage_entry(sample_entry)

        sig_explicit = sign_lineage_entry(sample_entry, secret="env-secret")

        assert sig_env == sig_explicit

    def test_sign_default_secret_when_no_env(self, sample_entry):
        """Test signing uses default secret when no env var."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove LINEAGE_SECRET if present
            os.environ.pop("LINEAGE_SECRET", None)
            signature = sign_lineage_entry(sample_entry)

            # Should use "default-lineage-secret"
            expected = sign_lineage_entry(sample_entry, secret="default-lineage-secret")
            assert signature == expected


class TestVerifyLineageEntry:
    """Tests for verify_lineage_entry function."""

    @pytest.fixture
    def signed_entry(self):
        """Create signed entry for verification tests."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="verify-test",
            table_name="accounts",
            column_name="balance",
            strategy_name="noise",
            rows_affected=500,
            executed_by="audit",
            executed_at=datetime.now(UTC),
        )
        entry.hmac_signature = sign_lineage_entry(entry, secret="verify-secret")
        return entry

    def test_verify_valid_signature(self, signed_entry):
        """Test verification of valid signature."""
        is_valid = verify_lineage_entry(signed_entry, secret="verify-secret")

        assert is_valid is True

    def test_verify_invalid_signature(self, signed_entry):
        """Test verification fails with wrong secret."""
        is_valid = verify_lineage_entry(signed_entry, secret="wrong-secret")

        assert is_valid is False

    def test_verify_tampered_entry(self):
        """Test verification detects tampering."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="tamper-test",
            table_name="users",
            column_name="email",
            strategy_name="hashing",
            rows_affected=100,
        )
        entry.hmac_signature = sign_lineage_entry(entry, secret="original")

        # Tamper with the entry
        entry.rows_affected = 999

        is_valid = verify_lineage_entry(entry, secret="original")

        assert is_valid is False

    def test_verify_empty_signature(self):
        """Test verification fails with empty signature."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="empty-sig",
            table_name="test",
            column_name="data",
            strategy_name="mask",
            hmac_signature="",
        )

        is_valid = verify_lineage_entry(entry, secret="test")

        assert is_valid is False


class TestCreateLineageEntry:
    """Tests for create_lineage_entry convenience function."""

    def test_create_minimal(self):
        """Test creating entry with minimal params."""
        entry = create_lineage_entry(
            operation_id="create-test",
            table_name="users",
            column_name="email",
            strategy_name="tokenization",
        )

        assert entry.operation_id == "create-test"
        assert entry.table_name == "users"
        assert entry.column_name == "email"
        assert entry.strategy_name == "tokenization"
        assert isinstance(entry.id, UUID)
        assert entry.hmac_signature != ""

    def test_create_with_all_params(self):
        """Test creating entry with all parameters."""
        entry = create_lineage_entry(
            operation_id="full-test",
            table_name="orders",
            column_name="total",
            strategy_name="rounding",
            rows_affected=2000,
            executed_by="batch@system",
            reason="Privacy compliance",
            request_id="TASK-5678",
            department="Finance",
            data_minimization_applied=True,
            retention_days=180,
            source_count=2500,
            target_count=2000,
            duration_seconds=30.0,
            status="success",
            error_message=None,
            secret="custom-secret",
        )

        assert entry.rows_affected == 2000
        assert entry.executed_by == "batch@system"
        assert entry.reason == "Privacy compliance"
        assert entry.request_id == "TASK-5678"
        assert entry.department == "Finance"
        assert entry.data_minimization_applied is True
        assert entry.retention_days == 180
        assert entry.source_count == 2500
        assert entry.target_count == 2000

    def test_create_entry_is_signed(self):
        """Test created entry has HMAC signature."""
        entry = create_lineage_entry(
            operation_id="signed-test",
            table_name="data",
            column_name="value",
            strategy_name="mask",
            secret="sign-secret",
        )

        assert entry.hmac_signature != ""
        assert len(entry.hmac_signature) == 64

    def test_create_entry_signature_verifiable(self):
        """Test created entry signature is verifiable."""
        entry = create_lineage_entry(
            operation_id="verifiable-test",
            table_name="test",
            column_name="field",
            strategy_name="hash",
            secret="verify-me",
        )

        is_valid = verify_lineage_entry(entry, secret="verify-me")

        assert is_valid is True

    def test_create_with_error_status(self):
        """Test creating entry with error status."""
        entry = create_lineage_entry(
            operation_id="error-test",
            table_name="failed",
            column_name="data",
            strategy_name="anonymize",
            status="error",
            error_message="Database connection failed",
        )

        assert entry.status == "error"
        assert entry.error_message == "Database connection failed"

    def test_create_entry_executed_at_is_recent(self):
        """Test created entry has recent executed_at timestamp."""
        before = datetime.now(UTC)
        entry = create_lineage_entry(
            operation_id="time-test",
            table_name="test",
            column_name="col",
            strategy_name="mask",
        )
        after = datetime.now(UTC)

        assert before <= entry.executed_at <= after


class TestHMACSecurityProperties:
    """Tests for HMAC security properties."""

    def test_hmac_length_extension_attack_resistance(self):
        """Test HMAC is resistant to length extension attacks."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="hmac-test",
            table_name="users",
            column_name="data",
            strategy_name="mask",
        )

        sig1 = sign_lineage_entry(entry, secret="secret")

        # Length extension attack attempt: try to extend the signature
        # HMAC should prevent this
        extended_sig = sig1 + "additional"

        # Verify should fail
        entry.hmac_signature = extended_sig
        is_valid = verify_lineage_entry(entry, secret="secret")

        assert is_valid is False

    def test_timing_safe_comparison(self):
        """Test signature comparison is timing-safe."""
        # This is implicit in hmac.compare_digest, but we test
        # that different-length strings are handled correctly
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="timing-test",
            table_name="test",
            column_name="col",
            strategy_name="mask",
        )

        entry.hmac_signature = "short"
        is_valid = verify_lineage_entry(entry, secret="test")
        assert is_valid is False

        entry.hmac_signature = "a" * 100  # Too long
        is_valid = verify_lineage_entry(entry, secret="test")
        assert is_valid is False

    def test_signature_includes_critical_fields(self):
        """Test signature covers all critical fields."""
        # Create a fixed UUID and time for base params
        fixed_id = uuid4()
        fixed_time = datetime.now(UTC)

        # Test each critical field independently
        critical_fields = [
            ("table_name", "table1", "table2"),
            ("column_name", "col1", "col2"),
            ("rows_affected", 100, 200),
            ("executed_by", "user1", "user2"),
            ("status", "success", "error"),
        ]

        for field, val1, val2 in critical_fields:
            # Create base params fresh for each field test
            base_params = {
                "id": fixed_id,
                "operation_id": "test-op",
                "table_name": "users",
                "column_name": "email",
                "strategy_name": "mask",
                "executed_at": fixed_time,
            }

            params1 = {**base_params, field: val1}
            params2 = {**base_params, field: val2}

            entry1 = DataLineageEntry(**params1)
            entry2 = DataLineageEntry(**params2)

            sig1 = sign_lineage_entry(entry1, secret="test")
            sig2 = sign_lineage_entry(entry2, secret="test")

            assert sig1 != sig2, f"Field {field} not included in signature"


class TestLineageEntryEdgeCases:
    """Tests for edge cases in lineage entries."""

    def test_entry_with_unicode_values(self):
        """Test entry handles unicode values."""
        entry = create_lineage_entry(
            operation_id="unicode-test-日本語",
            table_name="utilisateurs",
            column_name="prénom",
            strategy_name="masquage",
            reason="Conformité RGPD",
            secret="unicode-secret",
        )

        # Should serialize correctly
        json_str = entry.to_json()
        restored = DataLineageEntry.from_json(json_str)

        assert restored.operation_id == "unicode-test-日本語"
        assert restored.column_name == "prénom"

    def test_entry_with_special_characters(self):
        """Test entry handles special characters."""
        entry = create_lineage_entry(
            operation_id="special<>&'\"test",
            table_name="test_table",
            column_name="field[0]",
            strategy_name="mask",
            reason="Test with special chars: <>&'\"",
        )

        json_str = entry.to_json()
        restored = DataLineageEntry.from_json(json_str)

        assert restored.reason == "Test with special chars: <>&'\""

    def test_entry_with_none_optional_fields(self):
        """Test entry handles None optional fields."""
        entry = DataLineageEntry(
            id=uuid4(),
            operation_id="none-test",
            table_name="test",
            column_name="col",
            strategy_name="mask",
            reason=None,
            request_id=None,
            department=None,
            retention_days=None,
            error_message=None,
        )

        json_str = entry.to_json()
        restored = DataLineageEntry.from_json(json_str)

        assert restored.reason is None
        assert restored.request_id is None

    def test_entry_with_zero_values(self):
        """Test entry handles zero values correctly."""
        entry = create_lineage_entry(
            operation_id="zero-test",
            table_name="empty",
            column_name="data",
            strategy_name="mask",
            rows_affected=0,
            duration_seconds=0.0,
            source_count=0,
            target_count=0,
            retention_days=0,
        )

        assert entry.rows_affected == 0
        assert entry.duration_seconds == 0.0
        assert entry.retention_days == 0

    def test_entry_with_large_values(self):
        """Test entry handles large values."""
        entry = create_lineage_entry(
            operation_id="large-test",
            table_name="big_table",
            column_name="data",
            strategy_name="mask",
            rows_affected=10_000_000,
            duration_seconds=86400.0,  # 24 hours
            source_count=100_000_000,
            target_count=10_000_000,
            retention_days=3650,  # 10 years
        )

        json_str = entry.to_json()
        restored = DataLineageEntry.from_json(json_str)

        assert restored.rows_affected == 10_000_000
        assert restored.duration_seconds == 86400.0
