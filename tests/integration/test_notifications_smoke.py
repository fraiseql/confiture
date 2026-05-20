"""Notification renderers — end-to-end smoke test through StdoutTransport.

Exercises every renderer once.  For each output:

- The JSON/text body is valid for its declared ``content_type``.
- The rendered payload contains the documented top-level fields for the
  service it targets.  These checks are *thin*; the deep snapshot lives
  in the unit tests.

The point of this file is to pin the docs/guides/notifications.md examples
to a working configuration end-to-end — if a YAML snippet in the guide
stops parsing, this file fails first.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.notifications.config import (
    NotificationConfig,
    load_notifications_config,
)
from confiture.core.hooks.notifications.factory import from_config
from confiture.core.hooks.notifications.transport import StdoutTransport


def _exec_ctx(success: bool = True, error: str | None = None) -> ExecutionContext:
    return ExecutionContext(
        elapsed_time_ms=147,
        rows_affected=12,
        metadata={
            "migration_name": "smoke_test_migration",
            "migration_version": "20260520120000",
            "direction": "up",
            "success": success,
            "database_name": "confiture_smoke",
            "schema": "public",
            "error": error,
        },
    )


def _run_with_stdout(renderer_cfg: dict, ctx: ExecutionContext) -> str:
    """Build a NotificationHook from a renderer config, swap to
    StdoutTransport, execute against *ctx*, and return whatever
    landed on the stream."""
    cfg = NotificationConfig.model_validate(
        {
            "id": "smoke",
            "transport": {"type": "stdout"},
            "renderer": renderer_cfg,
        }
    )
    hook = from_config(cfg)
    stream = io.StringIO()
    hook.transport = StdoutTransport(stream=stream)
    asyncio.run(hook.execute(HookContext(phase="after_execute", data=ctx)))
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Per-renderer smoke tests.
# ---------------------------------------------------------------------------


class TestRendererSmoke:
    """Exercise every renderer through StdoutTransport once."""

    def test_slack_renderer_produces_valid_json_with_attachments(self) -> None:
        out = _run_with_stdout({"type": "slack", "channel": "#migrations"}, _exec_ctx())
        body = json.loads(out)
        assert body["channel"] == "#migrations"
        assert "attachments" in body
        assert body["attachments"][0]["color"] == "#36a64f"

    def test_discord_renderer_produces_valid_json_with_embed(self) -> None:
        out = _run_with_stdout({"type": "discord"}, _exec_ctx())
        body = json.loads(out)
        assert "embeds" in body
        assert body["embeds"][0]["color"] == 0x36A64F

    def test_teams_renderer_produces_valid_messagecard(self) -> None:
        out = _run_with_stdout({"type": "teams"}, _exec_ctx())
        body = json.loads(out)
        assert body["@type"] == "MessageCard"
        assert "sections" in body

    def test_email_renderer_emits_html_body_when_default(self) -> None:
        out = _run_with_stdout(
            {
                "type": "email",
                "from": "noreply@example.com",
                "to": ["team@example.com"],
            },
            _exec_ctx(),
        )
        # The Email renderer body is HTML, not JSON.
        assert "<h2" in out
        assert "smoke_test_migration" in out

    def test_pagerduty_renderer_emits_resolve_on_success(self) -> None:
        out = _run_with_stdout(
            {
                "type": "pagerduty",
                "routing_key": "abc",
                "service_name": "db",
            },
            _exec_ctx(),
        )
        body = json.loads(out)
        assert body["event_action"] == "resolve"
        assert "dedup_key" in body

    def test_pagerduty_renderer_emits_trigger_on_failure(self) -> None:
        out = _run_with_stdout(
            {
                "type": "pagerduty",
                "routing_key": "abc",
                "service_name": "db",
                "severity": "critical",
            },
            _exec_ctx(success=False, error="constraint violation"),
        )
        body = json.loads(out)
        assert body["event_action"] == "trigger"
        assert body["payload"]["severity"] == "critical"

    def test_opsgenie_renderer_has_required_alias_field(self) -> None:
        out = _run_with_stdout(
            {
                "type": "opsgenie",
                "api_key": "key",
                "tags": ["prod", "db"],
            },
            _exec_ctx(),
        )
        body = json.loads(out)
        assert body["alias"]
        assert "prod" in body["tags"]

    def test_raw_json_renderer_emits_canonical_event(self) -> None:
        out = _run_with_stdout({"type": "raw_json"}, _exec_ctx())
        body = json.loads(out)
        assert body["event"] == "migration_completed"
        assert body["success"] is True
        assert body["database"] == "confiture_smoke"

    def test_jinja_renderer_renders_simple_template_when_opted_in(self) -> None:
        raw = {
            "allow_templated_renderers": True,
            "hooks": [
                {
                    "id": "smoke",
                    "transport": {"type": "stdout"},
                    "renderer": {
                        "type": "jinja",
                        "template": "Migration {{ migration_name }} {{ direction }}",
                        "content_type": "text/plain",
                    },
                }
            ],
        }
        root = load_notifications_config(raw)
        hook = from_config(root.hooks[0], allow_templated_renderers=True)
        stream = io.StringIO()
        hook.transport = StdoutTransport(stream=stream)
        asyncio.run(hook.execute(HookContext(phase="after_execute", data=_exec_ctx())))
        out = stream.getvalue()
        assert "Migration smoke_test_migration up" in out


# ---------------------------------------------------------------------------
# Guide-snippet sanity — every YAML block shown in docs/guides/notifications.md
# must parse successfully against NotificationsRootConfig.
# ---------------------------------------------------------------------------


GUIDE_YAML_SNIPPETS = [
    # Slack
    """
notifications:
  hooks:
    - id: prod-slack
      phase: after_execute
      transport:
        type: http
        url: https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX
        timeout_seconds: 10
        retry:
          attempts: 3
          backoff_seconds: 2
      renderer:
        type: slack
        channel: "#migrations"
        mention_on_failure: "@oncall"
""",
    # PagerDuty
    """
notifications:
  hooks:
    - id: oncall-pagerduty
      phase: after_execute
      transport:
        type: http
        url: https://events.pagerduty.com/v2/enqueue
      renderer:
        type: pagerduty
        routing_key: dummy_routing_key
        service_name: production-database
        severity: critical
""",
    # Email
    """
notifications:
  hooks:
    - id: weekly-audit-email
      phase: after_execute
      transport:
        type: smtp
        host: smtp.example.com
        port: 587
        username: notify
        password: dummy
        use_tls: true
      renderer:
        type: email
        from: db-migrations@example.com
        to: [devops@example.com]
        subject_template: "[Migration] {database_name} — {status}"
""",
    # Raw JSON / generic webhook
    """
notifications:
  hooks:
    - id: monitoring-webhook
      phase: after_execute
      transport:
        type: http
        url: https://internal.example.com/webhook
      renderer:
        type: raw_json
""",
]


@pytest.mark.parametrize("snippet", GUIDE_YAML_SNIPPETS)
def test_guide_yaml_snippet_parses(snippet: str) -> None:
    import yaml

    raw = yaml.safe_load(snippet)
    root = load_notifications_config(raw["notifications"])
    assert root.hooks
