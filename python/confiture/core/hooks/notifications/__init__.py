"""Notification hooks — Transport / Renderer / Hook architecture.

A single layered architecture replaces the legacy per-service hook classes
(Slack, Discord, Teams, Email, generic webhook).  External configurations
declare a transport (HTTP, SMTP, stdout, file) and a renderer (Slack,
Discord, Teams, Email, PagerDuty, OpsGenie, raw JSON, Jinja), and the
factory builds a :class:`NotificationHook` that ties them together.
"""

from __future__ import annotations

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import (
    DiscordRenderer,
    EmailRenderer,
    OpsGenieRenderer,
    PagerDutyRenderer,
    RawJsonRenderer,
    Renderer,
    SlackRenderer,
    TeamsRenderer,
)
from confiture.core.hooks.notifications.transport import (
    HttpTransport,
    RetryPolicy,
    SmtpConfig,
    SmtpTransport,
    StdoutTransport,
    Transport,
    TransportPayload,
)

__all__ = [
    "DiscordRenderer",
    "EmailRenderer",
    "HttpTransport",
    "NotificationContext",
    "OpsGenieRenderer",
    "PagerDutyRenderer",
    "RawJsonRenderer",
    "Renderer",
    "RetryPolicy",
    "SlackRenderer",
    "SmtpConfig",
    "SmtpTransport",
    "StdoutTransport",
    "TeamsRenderer",
    "Transport",
    "TransportPayload",
]
