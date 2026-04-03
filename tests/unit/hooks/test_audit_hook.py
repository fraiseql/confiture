"""Unit tests for builtin audit hook."""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.hooks.builtin.audit_hook import AuditConfig, AuditHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


class TestAuditHook:
    """Test suite for audit logging hook."""

    @pytest.fixture
    def audit_config(self):
        """Create test audit configuration."""
        return AuditConfig(
            database_url="postgresql://test:test@localhost/test",
            signing_key="test_signing_key_12345",
            environment="test_env",
        )

    @pytest.fixture
    def execution_context(self):
        """Create test execution context."""
        return ExecutionContext(
            elapsed_time_ms=1500,
            metadata={
                "migration_name": "test_migration",
                "direction": "up",
                "success": True,
                "executed_by": "test_user",
                "error": None,
            },
        )

    @pytest.fixture
    def hook_context(self, execution_context):
        """Create test hook context."""
        return HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=execution_context,
        )

    def test_audit_hook_initialization(self, audit_config):
        """AuditHook should initialize with correct properties."""
        hook = AuditHook(audit_config)

        assert hook.id == "builtin.audit"
        assert hook.name == "Audit Logger"
        assert hook.priority == 8

    @pytest.mark.asyncio
    @patch("psycopg.connect")
    async def test_audit_hook_successful_logging(
        self,
        mock_connect,
        audit_config,
        hook_context,
    ):
        """AuditHook should insert audit record successfully."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_connect.return_value.__exit__.return_value = None

        hook = AuditHook(audit_config)
        result = await hook.execute(hook_context)

        assert result.success is True
        assert "signature" in result.stats

        # Verify database operations
        mock_conn.execute.assert_called()
        mock_conn.commit.assert_called()

    @pytest.mark.asyncio
    @patch("psycopg.connect")
    async def test_audit_hook_database_failure(
        self,
        mock_connect,
        audit_config,
        hook_context,
    ):
        """AuditHook should handle database failures gracefully."""
        # Mock database connection failure
        mock_connect.side_effect = Exception("Connection failed")

        hook = AuditHook(audit_config)
        result = await hook.execute(hook_context)

        assert result.success is False
        assert "Connection failed" in result.error

    def test_audit_hook_signature_creation(self, audit_config):
        """AuditHook should create consistent HMAC signatures."""
        hook = AuditHook(audit_config)

        record = {
            "migration": "test_migration",
            "direction": "up",
            "environment": "test",
            "executed_by": "user",
            "duration_ms": 1000,
            "success": True,
            "error": None,
        }

        signature1 = hook._sign(record)
        signature2 = hook._sign(record)

        # Same record should produce same signature
        assert signature1 == signature2
        assert len(signature1) == 64  # SHA256 hex length

    def test_audit_hook_signature_verification(self, audit_config):
        """AuditHook.verify_signature should validate signatures correctly."""
        hook = AuditHook(audit_config)

        record = {
            "migration": "test_migration",
            "direction": "up",
            "environment": "test",
            "executed_by": "user",
            "duration_ms": 1000,
            "success": True,
            "error": None,
        }

        signature = hook._sign(record)

        # Valid signature should verify
        assert AuditHook.verify_signature(record, signature, audit_config.signing_key) is True

        # Invalid signature should not verify
        assert AuditHook.verify_signature(record, "invalid_sig", audit_config.signing_key) is False

        # Wrong key should not verify
        assert AuditHook.verify_signature(record, signature, "wrong_key") is False

    @pytest.mark.asyncio
    async def test_audit_hook_handles_missing_metadata(self, audit_config):
        """AuditHook should handle missing metadata gracefully."""
        # Context with minimal metadata
        ctx = ExecutionContext(metadata={})
        hook_context = HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=ctx,
        )

        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn

            hook = AuditHook(audit_config)
            result = await hook.execute(hook_context)

            assert result.success is True

            # Check that default values were used
            call_args = mock_conn.execute.call_args_list[1]  # Second call is INSERT
            params = call_args[0][1]  # Query parameters

            assert params[0] == "unknown"  # migration default
            assert params[1] == "unknown"  # direction default
            assert params[3] == "system"  # executed_by default
