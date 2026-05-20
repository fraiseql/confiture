"""Factory: NotificationConfig → NotificationHook.

The factory builds a :class:`NotificationHook` from a validated
:class:`NotificationConfig`.  It wires the discriminated transport/renderer
types to their concrete classes.
"""

from __future__ import annotations

from confiture.core.hooks.notifications.config import (
    DiscordRendererConfig,
    EmailRendererConfig,
    HttpTransportConfig,
    JinjaRendererConfig,
    NotificationConfig,
    OpsGenieRendererConfig,
    PagerDutyRendererConfig,
    RawJsonRendererConfig,
    SlackRendererConfig,
    SmtpTransportConfig,
    StdoutTransportConfig,
    TeamsRendererConfig,
)
from confiture.core.hooks.notifications.hook import NotificationHook
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
)


def from_config(
    config: NotificationConfig,
    *,
    allow_templated_renderers: bool = False,
) -> NotificationHook:
    """Build a :class:`NotificationHook` from a validated config.

    Args:
        config: One ``NotificationConfig`` entry (already validated).
        allow_templated_renderers: Passed through to the Jinja renderer's
            opt-in gate.  Set by ``NotificationsRootConfig.model_validate``
            based on the top-level YAML key.

    Returns:
        A ready-to-register :class:`NotificationHook`.
    """
    transport = _build_transport(config.transport)
    renderer = _build_renderer(
        config.renderer,
        allow_templated_renderers=allow_templated_renderers,
    )
    return NotificationHook(
        hook_id=f"notifications.{config.id}",
        transport=transport,
        renderer=renderer,
        phase=config.phase,
    )


def _build_transport(cfg) -> Transport:  # noqa: ANN001
    if isinstance(cfg, HttpTransportConfig):
        retry = (
            RetryPolicy(
                attempts=cfg.retry.attempts,
                backoff_seconds=cfg.retry.backoff_seconds,
            )
            if cfg.retry
            else None
        )
        return HttpTransport(
            url=cfg.url,
            timeout_seconds=cfg.timeout_seconds,
            retry=retry,
            verify_tls=cfg.verify_tls,
        )
    if isinstance(cfg, SmtpTransportConfig):
        return SmtpTransport(
            SmtpConfig(
                host=cfg.host,
                port=cfg.port,
                username=cfg.username,
                password=cfg.password,
                use_tls=cfg.use_tls,
                timeout_seconds=cfg.timeout_seconds,
            )
        )
    if isinstance(cfg, StdoutTransportConfig):
        return StdoutTransport()
    raise TypeError(f"Unknown transport config type: {type(cfg).__name__}")


def _build_renderer(cfg, *, allow_templated_renderers: bool) -> Renderer:  # noqa: ANN001
    if isinstance(cfg, SlackRendererConfig):
        return SlackRenderer(channel=cfg.channel, mention_on_failure=cfg.mention_on_failure)
    if isinstance(cfg, DiscordRendererConfig):
        return DiscordRenderer(username=cfg.username, mention_on_failure=cfg.mention_on_failure)
    if isinstance(cfg, TeamsRendererConfig):
        return TeamsRenderer(mention_on_failure=cfg.mention_on_failure)
    if isinstance(cfg, EmailRendererConfig):
        return EmailRenderer(
            from_addr=cfg.from_addr,
            to=cfg.to,
            subject_template=cfg.subject_template,
            cc=cfg.cc,
            include_html=cfg.include_html,
        )
    if isinstance(cfg, PagerDutyRendererConfig):
        return PagerDutyRenderer(
            routing_key=cfg.routing_key,
            service_name=cfg.service_name,
            component=cfg.component,
            group=cfg.group,
            class_=cfg.class_,
            severity=cfg.severity,
        )
    if isinstance(cfg, OpsGenieRendererConfig):
        return OpsGenieRenderer(
            api_key=cfg.api_key,
            alias_template=cfg.alias_template,
            tags=tuple(cfg.tags),
            priority_on_failure=cfg.priority_on_failure,
        )
    if isinstance(cfg, RawJsonRendererConfig):
        return RawJsonRenderer()
    if isinstance(cfg, JinjaRendererConfig):
        # Lazy import — Jinja lives in the [notifications] extra.
        from confiture.core.hooks.notifications.jinja_renderer import JinjaRenderer

        return JinjaRenderer(
            template=cfg.template,
            content_type=cfg.content_type,
            allow_templated_renderers=allow_templated_renderers,
        )
    raise TypeError(f"Unknown renderer config type: {type(cfg).__name__}")
