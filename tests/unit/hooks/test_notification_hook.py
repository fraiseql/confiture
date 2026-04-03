"""Unit tests for builtin Slack notification hook."""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.hooks.base import HookResult
from confiture.core.hooks.builtin.notification_hook import (
    SlackConfig,
    SlackNotificationHook,
)
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


class TestSlackNotificationHook:
    """Test suite for Slack notification hook."""

    @pytest.fixture
    def slack_config(self):
        """Create test Slack configuration."""
        return SlackConfig(
            webhook_url="https://hooks.slack.com/test",
            channel="#test-channel",
            mention_on_failure="@oncall",
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

    def test_slack_hook_initialization(self, slack_config):
        """SlackNotificationHook should initialize with correct properties."""
        hook = SlackNotificationHook(slack_config)

        assert hook.id == "builtin.slack"
        assert hook.name == "Slack Notification"
        assert hook.priority == 9

    @pytest.mark.asyncio
    @patch("urllib.request.urlopen")
    async def test_slack_hook_successful_notification(
        self,
        mock_urlopen,
        slack_config,
        hook_context_success,
    ):
        """SlackNotificationHook should post success message to Slack."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        hook = SlackNotificationHook(slack_config)
        result = await hook.execute(hook_context_success)

        assert result.success is True

        # Verify webhook was called
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        request = call_args[0][0]

        assert request.method == "POST"
        assert "hooks.slack.com" in request.full_url

        # Verify payload
        import json

        payload = json.loads(request.data.decode())
        assert payload["channel"] == "#test-channel"
        assert len(payload["attachments"]) == 1

        attachment = payload["attachments"][0]
        assert attachment["color"] == "#36a64f"  # green for success
        assert "test_migration" in attachment["text"]
        assert "succeeded" in attachment["text"]

    @pytest.mark.asyncio
    @patch("urllib.request.urlopen")
    async def test_slack_hook_failure_notification(
        self,
        mock_urlopen,
        slack_config,
        hook_context_failure,
    ):
        """SlackNotificationHook should post failure message with mention."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        hook = SlackNotificationHook(slack_config)
        result = await hook.execute(hook_context_failure)

        assert result.success is True

        # Verify payload contains failure indicators
        call_args = mock_urlopen.call_args
        request = call_args[0][0]

        import json

        payload = json.loads(request.data.decode())
        attachment = payload["attachments"][0]

        assert attachment["color"] == "#cc0000"  # red for failure
        assert "FAILED" in attachment["text"]
        assert "@oncall" in attachment["text"]  # mention on failure

    @pytest.mark.asyncio
    @patch("urllib.request.urlopen")
    async def test_slack_hook_http_failure(
        self,
        mock_urlopen,
        slack_config,
        hook_context_success,
    ):
        """SlackNotificationHook should handle HTTP failures gracefully."""
        # Mock HTTP error response
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        hook = SlackNotificationHook(slack_config)
        result = await hook.execute(hook_context_success)

        assert result.success is False
        assert "HTTP 500" in result.error

    @pytest.mark.asyncio
    async def test_slack_hook_network_failure(
        self,
        slack_config,
        hook_context_success,
    ):
        """SlackNotificationHook should handle network failures gracefully."""
        with patch("urllib.request.urlopen", side_effect=Exception("Network timeout")):
            hook = SlackNotificationHook(slack_config)
            result = await hook.execute(hook_context_success)

        assert result.success is False
        assert "Network timeout" in result.error

    def test_slack_hook_payload_structure(self, slack_config, execution_context_success):
        """SlackNotificationHook should build correct payload structure."""
        hook = SlackNotificationHook(slack_config)

        payload = hook._build_payload(execution_context_success)

        # Check required fields
        assert "attachments" in payload
        assert "channel" in payload
        assert payload["channel"] == "#test-channel"

        attachment = payload["attachments"][0]
        assert "color" in attachment
        assert "title" in attachment
        assert "text" in attachment
        assert "fields" in attachment

        # Check fields
        fields = {field["title"]: field["value"] for field in attachment["fields"]}
        assert "Migration" in fields
        assert "Direction" in fields
        assert "Duration" in fields
        assert "Time" in fields

    def test_slack_hook_payload_without_channel(self):
        """SlackNotificationHook should omit channel when not configured."""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        hook = SlackNotificationHook(config)

        ctx = ExecutionContext(
            metadata={"migration_name": "test", "direction": "up", "success": True}
        )
        payload = hook._build_payload(ctx)

        assert "channel" not in payload

    def test_slack_hook_payload_without_mention(self):
        """SlackNotificationHook should omit mention when not configured."""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        hook = SlackNotificationHook(config)

        ctx = ExecutionContext(
            metadata={"migration_name": "test", "direction": "up", "success": False}
        )
        payload = hook._build_payload(ctx)

        attachment = payload["attachments"][0]
        assert "@" not in attachment["text"]  # No mention
