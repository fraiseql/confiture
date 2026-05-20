"""Unit tests for PagerDuty and OpsGenie renderers — Phase 03 Cycle 6.

Both use the stateless model: one event per migration, trigger on failure,
resolve on success.  No cross-migration incident pairing — documented v1
tradeoff.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import (
    OpsGenieRenderer,
    PagerDutyRenderer,
)

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


def _body(payload) -> dict:
    return json.loads(
        payload.body.decode("utf-8") if isinstance(payload.body, bytes) else payload.body
    )


# ---------------------------------------------------------------------------
# PagerDutyRenderer
# ---------------------------------------------------------------------------


class TestPagerDutyRenderer:
    KEY = "00000000000000000000000000000000"

    def test_emits_trigger_event_on_failure(self) -> None:
        r = PagerDutyRenderer(routing_key=self.KEY, service_name="prod-db")
        body = _body(r.render(_ctx(success=False, error="bad SQL")))
        assert body["event_action"] == "trigger"
        assert body["routing_key"] == self.KEY
        assert body["payload"]["source"] == "prod-db"
        assert "FAILED" in body["payload"]["summary"]
        assert body["payload"]["severity"] == "critical"

    def test_emits_resolve_event_on_success(self) -> None:
        r = PagerDutyRenderer(routing_key=self.KEY, service_name="prod-db")
        body = _body(r.render(_ctx(success=True)))
        assert body["event_action"] == "resolve"
        assert body["routing_key"] == self.KEY
        # Resolve events do NOT carry a payload section.
        assert "payload" not in body

    def test_dedup_key_is_stable_per_migration_version(self) -> None:
        """Re-runs of the same migration must not re-page."""
        r = PagerDutyRenderer(routing_key=self.KEY, service_name="prod-db")
        body1 = _body(r.render(_ctx(success=False)))
        body2 = _body(r.render(_ctx(success=False)))
        assert body1["dedup_key"] == body2["dedup_key"]
        assert body1["dedup_key"].startswith("confiture-")

    def test_severity_maps_to_pd_severity(self) -> None:
        r = PagerDutyRenderer(
            routing_key=self.KEY,
            service_name="prod-db",
            severity="warning",
        )
        body = _body(r.render(_ctx(success=False)))
        assert body["payload"]["severity"] == "warning"

    def test_component_group_class_propagate(self) -> None:
        r = PagerDutyRenderer(
            routing_key=self.KEY,
            service_name="prod-db",
            component="postgres",
            group="infrastructure",
            class_="schema-migration",
        )
        body = _body(r.render(_ctx(success=False)))
        assert body["payload"]["component"] == "postgres"
        assert body["payload"]["group"] == "infrastructure"
        assert body["payload"]["class"] == "schema-migration"

    def test_custom_details_contain_migration_metadata(self) -> None:
        r = PagerDutyRenderer(routing_key=self.KEY, service_name="prod-db")
        body = _body(r.render(_ctx(success=False, error="bad")))
        details = body["payload"]["custom_details"]
        assert details["migration"] == "add_user_bio"
        assert details["version"] == "20260520143015"
        assert details["error"] == "bad"


# ---------------------------------------------------------------------------
# OpsGenieRenderer
# ---------------------------------------------------------------------------


class TestOpsGenieRenderer:
    KEY = "og-api-key-test"

    def test_sets_required_alias_field(self) -> None:
        r = OpsGenieRenderer(api_key=self.KEY)
        payload = r.render(_ctx(success=False))
        body = _body(payload)
        assert body["alias"] == "confiture-20260520143015"

    def test_alias_template_format_works(self) -> None:
        r = OpsGenieRenderer(
            api_key=self.KEY,
            alias_template="db-{database_name}-{migration_version}",
        )
        payload = r.render(_ctx(success=False))
        body = _body(payload)
        assert body["alias"] == "db-myapp_prod-20260520143015"

    def test_tags_propagate(self) -> None:
        r = OpsGenieRenderer(api_key=self.KEY, tags=("prod", "db", "migrations"))
        body = _body(r.render(_ctx()))
        assert body["tags"] == ["prod", "db", "migrations"]

    def test_priority_on_failure(self) -> None:
        r = OpsGenieRenderer(api_key=self.KEY, priority_on_failure="P1")
        body = _body(r.render(_ctx(success=False)))
        assert body["priority"] == "P1"
        # Success path uses P5.
        body = _body(r.render(_ctx(success=True)))
        assert body["priority"] == "P5"

    def test_authorization_header_uses_genie_key_scheme(self) -> None:
        r = OpsGenieRenderer(api_key=self.KEY)
        payload = r.render(_ctx())
        assert payload.headers.get("Authorization") == f"GenieKey {self.KEY}"

    def test_description_is_error_on_failure_message_on_success(self) -> None:
        r = OpsGenieRenderer(api_key=self.KEY)
        body_fail = _body(r.render(_ctx(success=False, error="boom")))
        assert body_fail["description"] == "boom"
        body_ok = _body(r.render(_ctx(success=True)))
        assert "Migration" in body_ok["description"]
