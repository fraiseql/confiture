"""Unit tests for the Renderer layer.

Cycle 2 of Phase 03 — Renderer ABC + SlackRenderer + DiscordRenderer +
TeamsRenderer.  All tests are pure-Python; no network, no DB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import (
    DiscordRenderer,
    RawJsonRenderer,
    Renderer,
    SlackRenderer,
    TeamsRenderer,
)

# Fixed timestamp so snapshot tests don't drift.
_FIXED_TS = datetime(2026, 5, 20, 14, 30, 0, tzinfo=UTC)


def _ctx(**overrides) -> NotificationContext:
    base = {
        "migration_name": "add_user_bio",
        "migration_version": "20260520143015",
        "direction": "up",
        "success": True,
        "duration_ms": 124,
        "database_name": "myapp_prod",
        "schema": "public",
        "timestamp": _FIXED_TS,
        "rows_affected": 0,
        "error": None,
        "migrations_applied": [],
    }
    base.update(overrides)
    return NotificationContext(**base)


def _decode(payload) -> dict:
    body = payload.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


# ---------------------------------------------------------------------------
# Renderer ABC
# ---------------------------------------------------------------------------


class TestRendererABC:
    def test_renderer_abc_requires_render(self) -> None:
        with pytest.raises(TypeError):
            Renderer()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# SlackRenderer
# ---------------------------------------------------------------------------


class TestSlackRenderer:
    def test_success_payload_matches_legacy_shape(self) -> None:
        """Byte-for-byte compatibility with the legacy SlackNotificationHook.

        Specifically pins the field order, color, title, text, and the four
        ``fields`` rows.  If this snapshot drifts, the deprecation shim for
        ``SlackNotificationHook`` (Cycle 9) will surface a behavioural diff.
        """
        payload = SlackRenderer().render(_ctx())
        body = _decode(payload)

        assert payload.content_type == "application/json"
        assert "channel" not in body  # no channel override by default
        assert len(body["attachments"]) == 1
        att = body["attachments"][0]
        assert att["color"] == "#36a64f"
        assert att["title"] == "Migration Succeeded"
        assert att["text"] == "Migration `add_user_bio` (up) succeeded"
        # The four facts, in legacy order.
        assert att["fields"] == [
            {"title": "Migration", "value": "add_user_bio", "short": True},
            {"title": "Direction", "value": "up", "short": True},
            {"title": "Duration", "value": "124ms", "short": True},
            {"title": "Time", "value": "2026-05-20 14:30 UTC", "short": True},
        ]

    def test_failure_payload_has_red_attachment_color(self) -> None:
        payload = SlackRenderer().render(_ctx(success=False))
        body = _decode(payload)
        assert body["attachments"][0]["color"] == "#cc0000"
        assert "FAILED" in body["attachments"][0]["text"]
        assert body["attachments"][0]["title"] == "Migration Failed"

    def test_includes_mention_on_failure_when_configured(self) -> None:
        payload = SlackRenderer(mention_on_failure="@oncall").render(_ctx(success=False))
        body = _decode(payload)
        assert "@oncall" in body["attachments"][0]["text"]

    def test_omits_mention_on_success_even_when_configured(self) -> None:
        payload = SlackRenderer(mention_on_failure="@oncall").render(_ctx(success=True))
        body = _decode(payload)
        assert "@oncall" not in body["attachments"][0]["text"]

    def test_channel_override_propagates(self) -> None:
        payload = SlackRenderer(channel="#deploys").render(_ctx())
        body = _decode(payload)
        assert body["channel"] == "#deploys"

    def test_down_direction_renders_correctly(self) -> None:
        payload = SlackRenderer().render(_ctx(direction="down"))
        body = _decode(payload)
        assert "(down)" in body["attachments"][0]["text"]
        assert body["attachments"][0]["fields"][1]["value"] == "down"


# ---------------------------------------------------------------------------
# DiscordRenderer
# ---------------------------------------------------------------------------


class TestDiscordRenderer:
    def test_success_payload_has_green_embed(self) -> None:
        payload = DiscordRenderer().render(_ctx())
        body = _decode(payload)
        assert payload.content_type == "application/json"
        assert len(body["embeds"]) == 1
        embed = body["embeds"][0]
        assert embed["color"] == 0x36A64F
        assert embed["title"] == "Migration Succeeded"

    def test_failure_payload_has_red_embed(self) -> None:
        payload = DiscordRenderer().render(_ctx(success=False, error="bad SQL"))
        body = _decode(payload)
        embed = body["embeds"][0]
        assert embed["color"] == 0xCC0000
        error_field = next(f for f in embed["fields"] if f["name"] == "Error")
        assert error_field["value"] == "bad SQL"

    def test_long_error_truncated_to_1024(self) -> None:
        long_err = "x" * 2000
        payload = DiscordRenderer().render(_ctx(success=False, error=long_err))
        embed = _decode(payload)["embeds"][0]
        error_field = next(f for f in embed["fields"] if f["name"] == "Error")
        assert len(error_field["value"]) == 1024

    def test_mention_on_failure_appears_as_content(self) -> None:
        payload = DiscordRenderer(mention_on_failure="<@&123456>").render(_ctx(success=False))
        body = _decode(payload)
        assert body.get("content") == "<@&123456>"

    def test_no_content_field_on_success(self) -> None:
        payload = DiscordRenderer(mention_on_failure="<@&123456>").render(_ctx(success=True))
        body = _decode(payload)
        assert "content" not in body

    def test_username_override_propagates(self) -> None:
        payload = DiscordRenderer(username="confiture-bot").render(_ctx())
        body = _decode(payload)
        assert body["username"] == "confiture-bot"

    def test_embed_includes_iso_timestamp(self) -> None:
        payload = DiscordRenderer().render(_ctx())
        body = _decode(payload)
        # ISO timestamp from the fixed UTC datetime.
        assert body["embeds"][0]["timestamp"].startswith("2026-05-20T14:30:00")


# ---------------------------------------------------------------------------
# RawJsonRenderer (#109) — canonical migration-event JSON payload.
# ---------------------------------------------------------------------------


class TestRawJsonRenderer:
    def test_default_payload_shape(self) -> None:
        payload = RawJsonRenderer().render(_ctx())
        body = _decode(payload)
        # Documented top-level keys, in any order — but all present.
        assert set(body) == {
            "event",
            "timestamp",
            "database",
            "schema",
            "success",
            "execution_time_ms",
            "migrations_applied",
            "error",
            "migration_details",
        }
        assert body["event"] == "migration_completed"

    def test_includes_all_documented_fields(self) -> None:
        payload = RawJsonRenderer().render(_ctx(database_name="myapp_prod"))
        body = _decode(payload)
        assert body["database"] == "myapp_prod"
        assert body["schema"] == "public"
        assert body["success"] is True
        assert body["execution_time_ms"] == 124
        assert body["migrations_applied"] == 1
        assert body["error"] is None
        assert body["timestamp"].startswith("2026-05-20T14:30:00")
        assert body["migration_details"] == [
            {"version": "20260520143015", "name": "add_user_bio", "direction": "up"}
        ]

    def test_omits_error_when_success(self) -> None:
        payload = RawJsonRenderer().render(_ctx(success=True))
        body = _decode(payload)
        assert body["error"] is None

    def test_includes_error_when_failure(self) -> None:
        payload = RawJsonRenderer().render(_ctx(success=False, error="bad SQL"))
        body = _decode(payload)
        assert body["error"] == "bad SQL"
        assert body["success"] is False

    def test_batch_event_lists_all_migrations(self) -> None:
        payload = RawJsonRenderer().render(
            _ctx(
                migrations_applied=["add_user_bio", "add_orders_index", "add_phone"],
            )
        )
        body = _decode(payload)
        assert body["migrations_applied"] == 3
        assert [m["name"] for m in body["migration_details"]] == [
            "add_user_bio",
            "add_orders_index",
            "add_phone",
        ]


# ---------------------------------------------------------------------------
# TeamsRenderer
# ---------------------------------------------------------------------------


class TestTeamsRenderer:
    def test_success_card_shape(self) -> None:
        payload = TeamsRenderer().render(_ctx())
        body = _decode(payload)
        assert body["@type"] == "MessageCard"
        assert body["@context"] == "http://schema.org/extensions"
        assert body["themeColor"] == "36a64f"
        assert body["summary"] == "Migration succeeded"
        section = body["sections"][0]
        assert section["activityTitle"] == "Migration Succeeded"
        assert "(up)" in section["activitySubtitle"]
        assert section["markdown"] is True
        # Facts in the legacy order.
        names = [f["name"] for f in section["facts"]]
        assert names == ["Migration", "Direction", "Duration", "Time"]

    def test_failure_card_has_red_color(self) -> None:
        payload = TeamsRenderer().render(_ctx(success=False, error="boom"))
        body = _decode(payload)
        assert body["themeColor"] == "cc0000"
        section = body["sections"][0]
        # Error fact added.
        names = [f["name"] for f in section["facts"]]
        assert "Error" in names

    def test_long_error_truncated(self) -> None:
        long_err = "x" * 2000
        payload = TeamsRenderer().render(_ctx(success=False, error=long_err))
        section = _decode(payload)["sections"][0]
        error_fact = next(f for f in section["facts"] if f["name"] == "Error")
        assert len(error_fact["value"]) == 1024

    def test_mention_on_failure_appended_to_title(self) -> None:
        payload = TeamsRenderer(mention_on_failure="cc: @oncall").render(_ctx(success=False))
        body = _decode(payload)
        assert "cc: @oncall" in body["sections"][0]["activityTitle"]


# ---------------------------------------------------------------------------
# Renderer + Transport interop — proves the interface contract.
# ---------------------------------------------------------------------------


class TestRendererTransportInterop:
    """Confirm a renderer's output is consumable by a Transport unchanged."""

    def test_slack_renderer_output_round_trips_through_stdout_transport(self) -> None:
        import io

        from confiture.core.hooks.notifications.transport import StdoutTransport

        buf = io.StringIO()
        payload = SlackRenderer().render(_ctx())
        StdoutTransport(stream=buf).send(payload)
        # Round-trip: stdout output is the same JSON.
        out = buf.getvalue().strip()
        assert json.loads(out) == json.loads(payload.body.decode("utf-8"))
