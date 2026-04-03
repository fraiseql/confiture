"""Unit tests for builtin email notification hook."""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.hooks.builtin.email_hook import EmailConfig, EmailNotificationHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


class TestEmailNotificationHook:
    """Test suite for email notification hook."""

    @pytest.fixture
    def email_config(self):
        """Create test email configuration."""
        return EmailConfig(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            smtp_username="test@example.com",
            smtp_password="test_password",
            from_email="noreply@example.com",
            to_emails=["admin@example.com", "team@example.com"],
            subject_prefix="[Test Migration]",
        )

    @pytest.fixture
    def execution_context_success(self):
        """Create test execution context for successful migration."""
        return ExecutionContext(
            elapsed_time_ms=2500,
            metadata={
                "migration_name": "test_migration",
                "direction": "up",
                "success": True,
            },
        )

    @pytest.fixture
    def execution_context_failure(self):
        """Create test execution context for failed migration."""
        return ExecutionContext(
            elapsed_time_ms=1500,
            metadata={
                "migration_name": "failed_migration",
                "direction": "up",
                "success": False,
                "error": "constraint violation",
            },
        )

    @pytest.fixture
    def hook_context_success(self, execution_context_success):
        """Create test hook context for success."""
        return HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=execution_context_success,
        )

    @pytest.fixture
    def hook_context_failure(self, execution_context_failure):
        """Create test hook context for failure."""
        return HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=execution_context_failure,
        )

    def test_email_hook_initialization(self, email_config):
        """EmailNotificationHook should initialize with correct properties."""
        hook = EmailNotificationHook(email_config)

        assert hook.id == "builtin.email"
        assert hook.name == "Email Notification"
        assert hook.priority == 9

    @pytest.mark.asyncio
    @patch("smtplib.SMTP")
    async def test_email_hook_successful_notification(
        self,
        mock_smtp_class,
        email_config,
        hook_context_success,
    ):
        """EmailNotificationHook should send email successfully."""
        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        hook = EmailNotificationHook(email_config)
        result = await hook.execute(hook_context_success)

        assert result.success is True
        assert result.stats["recipients"] == 2

        # Verify SMTP calls
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587)
        # Note: starttls might not be called in all configurations
        mock_server.login.assert_called_once_with("test@example.com", "test_password")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @pytest.mark.asyncio
    @patch("smtplib.SMTP")
    async def test_email_hook_smtp_failure(
        self,
        mock_smtp_class,
        email_config,
        hook_context_success,
    ):
        """EmailNotificationHook should handle SMTP failures gracefully."""
        # Mock SMTP failure
        mock_smtp_class.side_effect = Exception("SMTP connection failed")

        hook = EmailNotificationHook(email_config)
        result = await hook.execute(hook_context_success)

        assert result.success is False
        assert "SMTP connection failed" in result.error

    @pytest.mark.asyncio
    async def test_email_hook_skip_on_success_disabled(self, email_config, hook_context_success):
        """EmailNotificationHook should skip success notifications when disabled."""
        config = EmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="test",
            smtp_password="test",
            from_email="test@example.com",
            to_emails=["test@example.com"],
            send_on_success=False,  # Disable success notifications
            send_on_failure=True,
        )

        hook = EmailNotificationHook(config)
        result = await hook.execute(hook_context_success)

        assert result.success is True
        assert result.stats["skipped"] == "success notification disabled"

    @pytest.mark.asyncio
    async def test_email_hook_skip_on_failure_disabled(self, email_config, hook_context_failure):
        """EmailNotificationHook should skip failure notifications when disabled."""
        config = EmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="test",
            smtp_password="test",
            from_email="test@example.com",
            to_emails=["test@example.com"],
            send_on_success=True,
            send_on_failure=False,  # Disable failure notifications
        )

        hook = EmailNotificationHook(config)
        result = await hook.execute(hook_context_failure)

        assert result.success is True
        assert result.stats["skipped"] == "failure notification disabled"

    def test_email_hook_build_email_success(self, email_config, execution_context_success):
        """EmailNotificationHook should build correct email for success."""
        hook = EmailNotificationHook(email_config)

        subject, html = hook._build_email(execution_context_success)

        assert "[Test Migration]" in subject
        assert "test_migration" in subject
        assert "up" in subject
        assert "SUCCEEDED" in subject

        assert "Migration ✅ SUCCEEDED" in html
        assert "test_migration" in html
        assert "2500ms" in html

    def test_email_hook_build_email_failure(self, email_config, execution_context_failure):
        """EmailNotificationHook should build correct email for failure."""
        hook = EmailNotificationHook(email_config)

        subject, html = hook._build_email(execution_context_failure)

        assert "[Test Migration]" in subject
        assert "failed_migration" in subject
        assert "FAILED" in subject

        assert "Migration ❌ FAILED" in html
        assert "constraint violation" in html
        assert "1500ms" in html
