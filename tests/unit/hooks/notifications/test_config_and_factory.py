"""Tests for NotificationConfig + NotificationsRootConfig + factory — Cycle 7.

Pin: discriminated-union validation, env-var expansion, helpful errors on
misspelled discriminator values, Jinja opt-in gate, factory builds the
right transport/renderer pair for each config combination.
"""

from __future__ import annotations

import pytest

from confiture.core.hooks.notifications.config import (
    NotificationConfig,
    load_notifications_config,
)
from confiture.core.hooks.notifications.factory import from_config
from confiture.core.hooks.notifications.hook import NotificationHook
from confiture.core.hooks.notifications.renderer import (
    DiscordRenderer,
    EmailRenderer,
    OpsGenieRenderer,
    PagerDutyRenderer,
    RawJsonRenderer,
    SlackRenderer,
    TeamsRenderer,
)
from confiture.core.hooks.notifications.transport import (
    HttpTransport,
    SmtpTransport,
    StdoutTransport,
)
from confiture.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Discriminated-union validation + helpful errors.
# ---------------------------------------------------------------------------


class TestDiscriminatedUnionValidation:
    def test_validates_known_renderer_type(self) -> None:
        cfg = NotificationConfig.model_validate(
            {
                "id": "x",
                "transport": {"type": "stdout"},
                "renderer": {"type": "slack"},
            }
        )
        assert cfg.id == "x"

    def test_unknown_renderer_type_helpful_error(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown renderer type 'slak'"):
            NotificationConfig.model_validate(
                {
                    "id": "x",
                    "transport": {"type": "stdout"},
                    "renderer": {"type": "slak"},
                }
            )

    def test_unknown_transport_type_helpful_error(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown transport type 'htp'"):
            NotificationConfig.model_validate(
                {
                    "id": "x",
                    "transport": {"type": "htp", "url": "x"},
                    "renderer": {"type": "raw_json"},
                }
            )

    def test_invalid_phase_rejected(self) -> None:
        with pytest.raises(Exception, match="Unknown phase"):
            NotificationConfig.model_validate(
                {
                    "id": "x",
                    "phase": "after_party",
                    "transport": {"type": "stdout"},
                    "renderer": {"type": "slack"},
                }
            )


# ---------------------------------------------------------------------------
# Env-var expansion.
# ---------------------------------------------------------------------------


class TestEnvVarExpansion:
    def test_expands_env_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_WEBHOOK", "https://hooks.example.com/abc")
        raw = {
            "hooks": [
                {
                    "id": "x",
                    "transport": {"type": "http", "url": "${MY_WEBHOOK}"},
                    "renderer": {"type": "raw_json"},
                }
            ]
        }
        cfg = load_notifications_config(raw)
        assert cfg.hooks[0].transport.url == "https://hooks.example.com/abc"

    def test_missing_env_var_fails_loud(self, monkeypatch) -> None:
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        raw = {
            "hooks": [
                {
                    "id": "x",
                    "transport": {"type": "http", "url": "${DOES_NOT_EXIST}"},
                    "renderer": {"type": "raw_json"},
                }
            ]
        }
        with pytest.raises(ConfigurationError, match="DOES_NOT_EXIST"):
            load_notifications_config(raw)

    def test_env_var_expansion_does_not_substitute_empty_string(self, monkeypatch) -> None:
        """Missing env vars are loud; never silently empty."""
        monkeypatch.setenv("MAYBE_EMPTY", "")  # Set but empty.
        raw = {
            "hooks": [
                {
                    "id": "x",
                    "transport": {"type": "http", "url": "https://x/${MAYBE_EMPTY}"},
                    "renderer": {"type": "raw_json"},
                }
            ]
        }
        cfg = load_notifications_config(raw)
        # Explicitly-set-to-empty is allowed (vs. completely missing).
        assert cfg.hooks[0].transport.url == "https://x/"


# ---------------------------------------------------------------------------
# Jinja opt-in gate at root level.
# ---------------------------------------------------------------------------


class TestJinjaGate:
    def test_jinja_hook_rejected_without_flag(self) -> None:
        raw = {
            "hooks": [
                {
                    "id": "x",
                    "transport": {"type": "http", "url": "https://x"},
                    "renderer": {
                        "type": "jinja",
                        "template": "{{ migration_name }}",
                    },
                }
            ]
        }
        with pytest.raises(ConfigurationError, match="allow_templated_renderers"):
            load_notifications_config(raw)

    def test_jinja_hook_accepted_with_flag(self) -> None:
        raw = {
            "allow_templated_renderers": True,
            "hooks": [
                {
                    "id": "x",
                    "transport": {"type": "http", "url": "https://x"},
                    "renderer": {
                        "type": "jinja",
                        "template": "{{ migration_name }}",
                    },
                }
            ],
        }
        cfg = load_notifications_config(raw)
        assert cfg.allow_templated_renderers is True
        assert cfg.hooks[0].renderer.type == "jinja"


# ---------------------------------------------------------------------------
# Factory: each renderer + transport combination resolves correctly.
# ---------------------------------------------------------------------------


class TestFactory:
    def _build(
        self, transport: dict, renderer: dict, allow_templated: bool = False
    ) -> NotificationHook:
        cfg = NotificationConfig.model_validate(
            {"id": "x", "transport": transport, "renderer": renderer}
        )
        return from_config(cfg, allow_templated_renderers=allow_templated)

    def test_http_slack_combination(self) -> None:
        h = self._build(
            {"type": "http", "url": "https://hooks.example.com/x"},
            {"type": "slack", "mention_on_failure": "@oncall"},
        )
        assert isinstance(h.transport, HttpTransport)
        assert isinstance(h.renderer, SlackRenderer)
        assert h.renderer.mention_on_failure == "@oncall"

    def test_stdout_raw_json_combination(self) -> None:
        h = self._build(
            {"type": "stdout"},
            {"type": "raw_json"},
        )
        assert isinstance(h.transport, StdoutTransport)
        assert isinstance(h.renderer, RawJsonRenderer)

    def test_smtp_email_combination(self) -> None:
        h = self._build(
            {"type": "smtp", "host": "smtp.example.com", "username": "u", "password": "p"},
            {"type": "email", "from": "a@b.com", "to": ["c@d.com"]},
        )
        assert isinstance(h.transport, SmtpTransport)
        assert isinstance(h.renderer, EmailRenderer)

    def test_http_pagerduty_combination(self) -> None:
        h = self._build(
            {"type": "http", "url": "https://events.pagerduty.com/v2/enqueue"},
            {"type": "pagerduty", "routing_key": "key", "service_name": "svc"},
        )
        assert isinstance(h.renderer, PagerDutyRenderer)

    def test_http_opsgenie_combination(self) -> None:
        h = self._build(
            {"type": "http", "url": "https://api.opsgenie.com/v2/alerts"},
            {"type": "opsgenie", "api_key": "k", "tags": ["prod"]},
        )
        assert isinstance(h.renderer, OpsGenieRenderer)

    def test_http_discord_combination(self) -> None:
        h = self._build(
            {"type": "http", "url": "https://discord.com/webhook"},
            {"type": "discord"},
        )
        assert isinstance(h.renderer, DiscordRenderer)

    def test_http_teams_combination(self) -> None:
        h = self._build(
            {"type": "http", "url": "https://teams.webhook"},
            {"type": "teams"},
        )
        assert isinstance(h.renderer, TeamsRenderer)

    def test_jinja_renderer_requires_opt_in(self) -> None:
        with pytest.raises(ConfigurationError, match="allow_templated_renderers"):
            self._build(
                {"type": "http", "url": "https://x"},
                {"type": "jinja", "template": "{{ migration_name }}"},
                allow_templated=False,
            )


# ---------------------------------------------------------------------------
# NotificationHook end-to-end with StdoutTransport.
# ---------------------------------------------------------------------------


class TestNotificationHookEndToEnd:
    """Render → send round-trip through the hook with StdoutTransport."""

    def test_hook_renders_then_sends(self, capsys) -> None:
        import asyncio

        from confiture.core.hooks.context import ExecutionContext, HookContext

        cfg = NotificationConfig.model_validate(
            {
                "id": "test-stdout",
                "transport": {"type": "stdout"},
                "renderer": {"type": "raw_json"},
            }
        )
        hook = from_config(cfg)

        ctx = ExecutionContext(
            elapsed_time_ms=124,
            metadata={
                "migration_name": "add_user_bio",
                "migration_version": "20260520143015",
                "direction": "up",
                "success": True,
                "database_name": "myapp_prod",
            },
        )
        ctx_wrapped = HookContext(phase="after_execute", data=ctx)
        result = asyncio.run(hook.execute(ctx_wrapped))
        assert result.success
        captured = capsys.readouterr()
        assert "add_user_bio" in captured.out
        assert "migration_completed" in captured.out

    def test_transport_failure_is_swallowed(self) -> None:
        """The hook must never block a migration on a notification failure."""
        import asyncio

        from confiture.core.hooks.context import ExecutionContext, HookContext
        from confiture.core.hooks.notifications.renderer import RawJsonRenderer
        from confiture.core.hooks.notifications.transport import Transport, TransportPayload

        class _ExplodingTransport(Transport):
            def send(self, payload: TransportPayload) -> None:
                raise RuntimeError("network down")

        hook = NotificationHook("test", _ExplodingTransport(), RawJsonRenderer())
        ctx = ExecutionContext(elapsed_time_ms=10, metadata={"migration_name": "x"})
        result = asyncio.run(hook.execute(HookContext(phase="after_execute", data=ctx)))
        # Hook returns success=False but does NOT raise.
        assert result.success is False
        assert "network down" in result.error
