"""Renderer ABC and concrete renderers for notification hooks.

Renderers are *pure functions* from :class:`NotificationContext` to
:class:`TransportPayload`.  No I/O, no clock reads (the context carries
the timestamp), no environment lookups.  This keeps them snapshot-
comparable across tests and trivially recombinable with any transport.

Cycle 2 ships:

- :class:`Renderer` — the ABC.
- :class:`SlackRenderer` — byte-for-byte compatible with the legacy
  ``SlackNotificationHook._build_payload`` shape.
- :class:`DiscordRenderer` — Discord webhook embed format.
- :class:`TeamsRenderer` — Microsoft Teams adaptive-card MessageCard format.

Cycles 3-6 will add ``RawJsonRenderer``, ``JinjaRenderer``, ``EmailRenderer``,
``PagerDutyRenderer``, ``OpsGenieRenderer``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.transport import TransportPayload


class Renderer(ABC):
    """Pure ``NotificationContext`` → ``TransportPayload`` mapping."""

    @abstractmethod
    def render(self, context: NotificationContext) -> TransportPayload:
        """Produce a transport-ready payload from *context*."""


# ---------------------------------------------------------------------------
# Slack — byte-for-byte compatible with legacy SlackNotificationHook output.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlackRenderer(Renderer):
    """Render a Slack webhook payload.

    Args:
        channel: When set, overrides the webhook's default channel.
        mention_on_failure: An ``@user`` or ``@channel`` mention appended
            to the failure message text.  Ignored on success.
    """

    channel: str | None = None
    mention_on_failure: str | None = None

    def render(self, context: NotificationContext) -> TransportPayload:
        color = "#36a64f" if context.success else "#cc0000"
        status_title = context.status_word.title()
        text = f"Migration `{context.migration_name}` ({context.direction}) {context.status_word}"
        if not context.success and self.mention_on_failure:
            text += f" — {self.mention_on_failure}"

        payload: dict = {
            "attachments": [
                {
                    "color": color,
                    "title": f"Migration {status_title}",
                    "text": text,
                    "fields": [
                        {"title": "Migration", "value": context.migration_name, "short": True},
                        {"title": "Direction", "value": context.direction, "short": True},
                        {"title": "Duration", "value": f"{context.duration_ms}ms", "short": True},
                        {"title": "Time", "value": context.timestamp_human, "short": True},
                    ],
                }
            ],
        }
        if self.channel:
            payload["channel"] = self.channel
        return TransportPayload(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# Discord — webhook embed format.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscordRenderer(Renderer):
    """Render a Discord webhook embed payload.

    Args:
        username: Override the webhook's default username for this message.
        mention_on_failure: ``<@USER_ID>`` or ``<@&ROLE_ID>`` to ping on failures.
    """

    username: str | None = None
    mention_on_failure: str | None = None

    # Discord uses decimal colors, not hex strings.
    _COLOR_SUCCESS = 0x36A64F
    _COLOR_FAILURE = 0xCC0000

    def render(self, context: NotificationContext) -> TransportPayload:
        color = self._COLOR_SUCCESS if context.success else self._COLOR_FAILURE
        title = f"Migration {context.status_word.title()}"
        description = f"`{context.migration_name}` ({context.direction})"
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": context.timestamp.isoformat(),
            "fields": [
                {"name": "Migration", "value": context.migration_name, "inline": True},
                {"name": "Direction", "value": context.direction, "inline": True},
                {"name": "Duration", "value": f"{context.duration_ms}ms", "inline": True},
                {"name": "Database", "value": context.database_name or "(unknown)", "inline": True},
            ],
        }
        if not context.success and context.error:
            embed["fields"].append(
                {"name": "Error", "value": context.error[:1024], "inline": False}
            )

        payload: dict = {"embeds": [embed]}
        if self.username:
            payload["username"] = self.username
        if not context.success and self.mention_on_failure:
            payload["content"] = self.mention_on_failure
        return TransportPayload(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# Teams — Microsoft Teams MessageCard (Adaptive Card).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawJsonRenderer(Renderer):
    """Render the canonical confiture migration-event JSON payload.

    Targets generic HTTP webhook receivers (#109).  Operators point this
    renderer at any HTTP endpoint and receive a documented, stable JSON
    schema.  External consumers can validate against
    ``docs/reference/notification-payload-schema.json``.

    The payload shape::

        {
          "event": "migration_completed",
          "timestamp": "2026-05-20T14:30:00+00:00",
          "database": "myapp_prod",
          "schema": "public",
          "success": true,
          "execution_time_ms": 124,
          "migrations_applied": 1,
          "error": null,
          "migration_details": [
            {"version": "...", "name": "...", "direction": "up"}
          ]
        }
    """

    def render(self, context: NotificationContext) -> TransportPayload:
        details = [
            {
                "version": context.migration_version,
                "name": context.migration_name,
                "direction": context.direction,
            }
        ]
        # If this event carries a batch summary, list every migration name.
        if context.migrations_applied:
            details = [
                {"version": "", "name": n, "direction": context.direction}
                for n in context.migrations_applied
            ]

        payload = {
            "event": "migration_completed",
            "timestamp": context.timestamp.isoformat(),
            "database": context.database_name,
            "schema": context.schema,
            "success": context.success,
            "execution_time_ms": context.duration_ms,
            "migrations_applied": len(details),
            "error": context.error if not context.success else None,
            "migration_details": details,
        }
        return TransportPayload(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )


@dataclass(frozen=True)
class EmailRenderer(Renderer):
    """Render an email body and SMTP metadata for :class:`SmtpTransport`.

    Args:
        from_addr: Envelope From and ``From:`` header.
        to: Recipient list (or single address).
        subject_template: Python ``str.format`` template — **not Jinja** —
            using keys ``database_name``, ``status``, ``migration_name``,
            ``direction``.  Plain string formatting keeps SMTP free of any
            Jinja sandbox concerns.
        cc: Optional Cc list.
        include_html: When True (default), produces a ``text/html`` body
            with simple markup; when False, plain text.

    The returned ``TransportPayload`` carries SMTP-specific metadata in
    ``payload.metadata`` (``from``, ``to``, ``subject``, ``cc``).
    """

    from_addr: str
    to: list[str] | str
    subject_template: str = "[Migration] {database_name} — {status}"
    cc: list[str] | None = None
    include_html: bool = True

    def render(self, context: NotificationContext) -> TransportPayload:
        subject = self.subject_template.format(
            database_name=context.database_name,
            status=context.status_word,
            migration_name=context.migration_name,
            direction=context.direction,
        )

        if self.include_html:
            color = "#36a64f" if context.success else "#cc0000"
            error_html = (
                f'<p><strong>Error:</strong> <pre style="color:#cc0000">{context.error}</pre></p>'
                if not context.success and context.error
                else ""
            )
            body = (
                f"<div style='font-family:sans-serif'>"
                f"<h2 style='color:{color}'>Migration {context.status_word}</h2>"
                f"<p><strong>Migration:</strong> <code>{context.migration_name}</code></p>"
                f"<p><strong>Direction:</strong> {context.direction}</p>"
                f"<p><strong>Duration:</strong> {context.duration_ms} ms</p>"
                f"<p><strong>Database:</strong> {context.database_name}</p>"
                f"<p><strong>Time:</strong> {context.timestamp_human}</p>"
                f"{error_html}"
                f"</div>"
            )
            content_type = "text/html"
        else:
            error_block = (
                f"\nError: {context.error}\n" if not context.success and context.error else ""
            )
            body = (
                f"Migration {context.status_word}\n"
                f"Migration: {context.migration_name}\n"
                f"Direction: {context.direction}\n"
                f"Duration:  {context.duration_ms} ms\n"
                f"Database:  {context.database_name}\n"
                f"Time:      {context.timestamp_human}\n"
                f"{error_block}"
            )
            content_type = "text/plain"

        metadata: dict = {
            "from": self.from_addr,
            "to": self.to,
            "subject": subject,
        }
        if self.cc:
            metadata["cc"] = self.cc
        return TransportPayload(body=body, content_type=content_type, metadata=metadata)


@dataclass(frozen=True)
class PagerDutyRenderer(Renderer):
    """Render a PagerDuty Events API v2 payload.

    Stateless model: one event per migration.  ``event_action`` is
    ``"trigger"`` on failure and ``"resolve"`` on success.  No cross-
    migration incident pairing — if both notifications fail, the on-call
    dashboard may show a phantom incident.  This is the documented v1
    tradeoff (see ``docs/guides/notifications.md``).

    Args:
        routing_key: PagerDuty integration routing key (the "Events API
            v2" key, not the API token).  Sensitive — pass via env-var
            substitution at config load.
        service_name: Used as ``payload.source``.
        component: Optional ``payload.component`` (e.g. ``database``).
        group: Optional ``payload.group`` (e.g. ``infrastructure``).
        class_: Optional ``payload.class`` — ``class`` is reserved in
            Python, hence the trailing underscore.
        severity: One of ``critical``, ``error``, ``warning``, ``info``.
            Defaults to ``critical``.
    """

    routing_key: str
    service_name: str
    component: str | None = None
    group: str | None = None
    class_: str | None = None
    severity: str = "critical"

    def render(self, context: NotificationContext) -> TransportPayload:
        # Stateless: every event has a unique dedup_key derived from the
        # migration version, so re-runs don't repeatedly page.
        dedup_key = f"confiture-{context.migration_version or context.migration_name}"

        if context.success:
            payload_dict = {
                "routing_key": self.routing_key,
                "event_action": "resolve",
                "dedup_key": dedup_key,
            }
        else:
            pd_payload = {
                "summary": (
                    f"Migration {context.migration_name} ({context.direction}) "
                    f"FAILED on {context.database_name}"
                ),
                "source": self.service_name,
                "severity": self.severity,
                "timestamp": context.timestamp.isoformat(),
                "custom_details": {
                    "migration": context.migration_name,
                    "version": context.migration_version,
                    "direction": context.direction,
                    "duration_ms": context.duration_ms,
                    "error": context.error or "",
                },
            }
            if self.component:
                pd_payload["component"] = self.component
            if self.group:
                pd_payload["group"] = self.group
            if self.class_:
                pd_payload["class"] = self.class_

            payload_dict = {
                "routing_key": self.routing_key,
                "event_action": "trigger",
                "dedup_key": dedup_key,
                "payload": pd_payload,
            }

        return TransportPayload(
            body=json.dumps(payload_dict).encode("utf-8"),
            content_type="application/json",
        )


@dataclass(frozen=True)
class OpsGenieRenderer(Renderer):
    """Render an OpsGenie alert payload.

    Stateless: one alert per migration.  ``alias`` ensures retries dedupe.

    Args:
        api_key: OpsGenie integration API key.  Sent as the
            ``Authorization`` header; the factory passes this through as
            transport-level header.  Sensitive — env-var substitute at load.
        alias_template: ``str.format`` template for the alert alias.
            Defaults to ``confiture-{migration_version}``.
        tags: Static tags applied to every alert.
        priority_on_failure: One of ``P1``-``P5``.  Defaults to ``P2``.
    """

    api_key: str
    alias_template: str = "confiture-{migration_version}"
    tags: tuple[str, ...] = ()
    priority_on_failure: str = "P2"

    def render(self, context: NotificationContext) -> TransportPayload:
        alias = self.alias_template.format(
            migration_version=context.migration_version or context.migration_name,
            migration_name=context.migration_name,
            database_name=context.database_name,
            direction=context.direction,
        )
        message = (
            f"Migration {context.migration_name} ({context.direction}) "
            f"{context.status_word} on {context.database_name}"
        )
        details = {
            "migration": context.migration_name,
            "version": context.migration_version,
            "direction": context.direction,
            "duration_ms": str(context.duration_ms),
            "error": context.error or "",
            "rows_affected": str(context.rows_affected),
        }
        payload_dict = {
            "message": message,
            "alias": alias,
            "description": context.error if not context.success else message,
            "priority": self.priority_on_failure if not context.success else "P5",
            "source": "confiture",
            "tags": list(self.tags),
            "details": details,
        }
        return TransportPayload(
            body=json.dumps(payload_dict).encode("utf-8"),
            content_type="application/json",
            headers={"Authorization": f"GenieKey {self.api_key}"},
        )


@dataclass(frozen=True)
class TeamsRenderer(Renderer):
    """Render a Microsoft Teams MessageCard payload.

    Args:
        mention_on_failure: Free-form text appended to the activity title
            on failure.  Teams supports ``<at>username</at>`` mentions but
            requires a per-tenant config; this renderer ships the simpler
            text-append behaviour and leaves richer mention markup to the
            operator.
    """

    mention_on_failure: str | None = None

    # MessageCard themeColor accepts hex strings WITHOUT the leading hash.
    _COLOR_SUCCESS = "36a64f"
    _COLOR_FAILURE = "cc0000"

    def render(self, context: NotificationContext) -> TransportPayload:
        color = self._COLOR_SUCCESS if context.success else self._COLOR_FAILURE
        activity_title = f"Migration {context.status_word.title()}"
        if not context.success and self.mention_on_failure:
            activity_title += f" — {self.mention_on_failure}"

        facts = [
            {"name": "Migration", "value": context.migration_name},
            {"name": "Direction", "value": context.direction},
            {"name": "Duration", "value": f"{context.duration_ms}ms"},
            {"name": "Time", "value": context.timestamp_human},
        ]
        if not context.success and context.error:
            facts.append({"name": "Error", "value": context.error[:1024]})

        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": f"Migration {context.status_word}",
            "sections": [
                {
                    "activityTitle": activity_title,
                    "activitySubtitle": f"`{context.migration_name}` ({context.direction})",
                    "facts": facts,
                    "markdown": True,
                }
            ],
        }
        return TransportPayload(
            body=json.dumps(card).encode("utf-8"),
            content_type="application/json",
        )
