"""Unit tests for builtin webhook notification hook."""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.hooks.builtin.webhook_hook import WebhookConfig, WebhookNotificationHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


class TestWebhookNotificationHook:
    """Test suite for generic webhook notification hook."""

    @pytest.fixture
    def webhook_config(self):
        """Create test webhook configuration."""
        return WebhookConfig(
            url="https://api.example.com/webhook",
            method="POST",
            headers={"Authorization": "Bearer token123"},
            send_on_success=True,
            send_on_failure=True,
        )

    @pytest.fixture
    def custom_template_config(self):
        """Create webhook config with custom template."""
        return WebhookConfig(
            url="https://api.example.com/webhook",
            template={
                "alert_type": "migration_{success}",
                "message": "Migration {migration_name} {direction} completed",
                "timestamp": "{timestamp}",
                "details": {
                    "duration": "{duration_ms}ms",
                    "error": "{error}",
                },
            },
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
    def hook_context_success(self, execution_context_success):
        """Create test hook context for success."""
        return HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=execution_context_success,
        )

    def test_webhook_hook_initialization(self, webhook_config):
        """WebhookNotificationHook should initialize with correct properties."""
        hook = WebhookNotificationHook(webhook_config)

        assert hook.id == "builtin.webhook"
        assert hook.name == "Webhook Notification"
        assert hook.priority == 9

    @pytest.mark.asyncio
    @patch("urllib.request.urlopen")
    async def test_webhook_hook_successful_notification(
        self,
        mock_urlopen,
        webhook_config,
        hook_context_success,
    ):
        """WebhookNotificationHook should send HTTP request successfully."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        hook = WebhookNotificationHook(webhook_config)
        result = await hook.execute(hook_context_success)

        assert result.success is True
        assert result.stats["status_code"] == 200

        # Verify the request was made correctly
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args[0][0]  # Request object

        assert call_args.full_url == "https://api.example.com/webhook"
        assert call_args.method == "POST"
        # Note: headers verification would require inspecting the request object differently

    @pytest.mark.asyncio
    @patch("urllib.request.urlopen")
    async def test_webhook_hook_http_failure(
        self,
        mock_urlopen,
        webhook_config,
        hook_context_success,
    ):
        """WebhookNotificationHook should handle HTTP failures gracefully."""
        # Mock HTTP error response
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        hook = WebhookNotificationHook(webhook_config)
        result = await hook.execute(hook_context_success)

        assert result.success is False
        assert "HTTP 500" in result.error

    @pytest.mark.asyncio
    async def test_webhook_hook_skip_on_success_disabled(
        self, webhook_config, hook_context_success
    ):
        """WebhookNotificationHook should skip success notifications when disabled."""
        config = WebhookConfig(
            url="https://api.example.com/webhook",
            send_on_success=False,
            send_on_failure=True,
        )

        hook = WebhookNotificationHook(config)
        result = await hook.execute(hook_context_success)

        assert result.success is True
        assert result.stats["skipped"] == "success notification disabled"

    def test_webhook_hook_build_default_payload(self, webhook_config, execution_context_success):
        """WebhookNotificationHook should build default JSON payload."""
        hook = WebhookNotificationHook(webhook_config)

        payload = hook._build_payload(execution_context_success)

        assert payload["event"] == "migration_complete"
        assert payload["migration"]["name"] == "test_migration"
        assert payload["migration"]["direction"] == "up"
        assert payload["migration"]["success"] is True
        assert payload["migration"]["duration_ms"] == 2500
        assert "timestamp" in payload

    def test_webhook_hook_build_custom_template(
        self, custom_template_config, execution_context_success
    ):
        """WebhookNotificationHook should process custom payload templates."""
        hook = WebhookNotificationHook(custom_template_config)

        payload = hook._build_payload(execution_context_success)

        assert payload["alert_type"] == "migration_True"
        assert payload["message"] == "Migration test_migration up completed"
        assert payload["timestamp"]  # Should be a non-empty timestamp string
        assert payload["details"]["duration"] == "2500ms"
        assert payload["details"]["error"] == ""

    def test_webhook_hook_custom_template_with_failure(self, custom_template_config):
        """WebhookNotificationHook should handle failure data in templates."""
        hook = WebhookNotificationHook(custom_template_config)

        ctx = ExecutionContext(
            elapsed_time_ms=1500,
            metadata={
                "migration_name": "failed_migration",
                "direction": "up",
                "success": False,
                "error": "constraint violation",
            },
        )

        payload = hook._build_payload(ctx)

        assert payload["alert_type"] == "migration_False"
        assert "failed_migration" in payload["message"]
        assert payload["details"]["error"] == "constraint violation"
