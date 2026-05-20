"""Pydantic config models for the notifications package.

YAML schema::

    hooks:
      notifications:
        - id: prod-slack
          phase: after_execute
          transport:
            type: http
            url: https://hooks.slack.com/services/...
            timeout_seconds: 10
            retry:
              attempts: 3
              backoff_seconds: 2
          renderer:
            type: slack
            mention_on_failure: "@oncall"

Discriminator: ``transport.type`` ∈ {``http``, ``smtp``, ``stdout``, ``file``};
``renderer.type`` ∈ {``slack``, ``discord``, ``teams``, ``email``,
``pagerduty``, ``opsgenie``, ``raw_json``, ``jinja``}.

Env-var expansion: any ``${VAR}`` occurrence in a string field is expanded
at config-load time from ``os.environ``.  Missing variables raise
``ConfigurationError`` — no silent empty-string substitution.

The Jinja renderer requires ``notifications.allow_templated_renderers: true``
at the root.  Default off.
"""

from __future__ import annotations

import os
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from confiture.exceptions import ConfigurationError

_KNOWN_RENDERER_TYPES = (
    "slack",
    "discord",
    "teams",
    "email",
    "pagerduty",
    "opsgenie",
    "raw_json",
    "jinja",
)
_KNOWN_TRANSPORT_TYPES = ("http", "smtp", "stdout", "file")

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env_vars(value: Any) -> Any:
    """Walk *value* recursively, expanding ``${VAR}`` in any string."""
    if isinstance(value, str):

        def _sub(match: re.Match) -> str:
            var = match.group(1)
            if var not in os.environ:
                raise ConfigurationError(
                    f"Environment variable {var!r} referenced in notifications config "
                    f"is not set.  Missing variables fail loud — they never expand to "
                    f"an empty string."
                )
            return os.environ[var]

        return _ENV_VAR_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Transport configs
# ---------------------------------------------------------------------------


class RetryPolicyConfig(BaseModel):
    attempts: int = 1
    backoff_seconds: float = 0.0


class HttpTransportConfig(BaseModel):
    type: Literal["http"]
    url: str
    timeout_seconds: float = 10.0
    retry: RetryPolicyConfig | None = None
    verify_tls: bool = True


class SmtpTransportConfig(BaseModel):
    type: Literal["smtp"]
    host: str
    port: int = 587
    username: str = ""
    password: SecretStr = SecretStr("")
    use_tls: bool = True
    timeout_seconds: float = 10.0


class StdoutTransportConfig(BaseModel):
    type: Literal["stdout"]


TransportConfig = Annotated[
    HttpTransportConfig | SmtpTransportConfig | StdoutTransportConfig,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Renderer configs
# ---------------------------------------------------------------------------


class SlackRendererConfig(BaseModel):
    type: Literal["slack"]
    channel: str | None = None
    mention_on_failure: str | None = None


class DiscordRendererConfig(BaseModel):
    type: Literal["discord"]
    username: str | None = None
    mention_on_failure: str | None = None


class TeamsRendererConfig(BaseModel):
    type: Literal["teams"]
    mention_on_failure: str | None = None


class EmailRendererConfig(BaseModel):
    type: Literal["email"]
    from_addr: str = Field(alias="from")
    to: list[str] | str
    subject_template: str = "[Migration] {database_name} — {status}"
    cc: list[str] | None = None
    include_html: bool = True

    model_config = {"populate_by_name": True}


class PagerDutyRendererConfig(BaseModel):
    type: Literal["pagerduty"]
    routing_key: str
    service_name: str
    component: str | None = None
    group: str | None = None
    class_: str | None = Field(default=None, alias="class")
    severity: str = "critical"

    model_config = {"populate_by_name": True}


class OpsGenieRendererConfig(BaseModel):
    type: Literal["opsgenie"]
    api_key: str
    alias_template: str = "confiture-{migration_version}"
    tags: list[str] = []
    priority_on_failure: str = "P2"


class RawJsonRendererConfig(BaseModel):
    type: Literal["raw_json"]


class JinjaRendererConfig(BaseModel):
    type: Literal["jinja"]
    template: str
    content_type: str = "application/json"


RendererConfig = Annotated[
    SlackRendererConfig
    | DiscordRendererConfig
    | TeamsRendererConfig
    | EmailRendererConfig
    | PagerDutyRendererConfig
    | OpsGenieRendererConfig
    | RawJsonRendererConfig
    | JinjaRendererConfig,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# NotificationConfig — one entry per configured hook.
# ---------------------------------------------------------------------------


class NotificationConfig(BaseModel):
    """One notification hook configuration entry."""

    id: str
    phase: str = "after_execute"
    transport: TransportConfig
    renderer: RendererConfig

    @model_validator(mode="before")
    @classmethod
    def _validate_known_types(cls, data: Any) -> Any:
        """Helpful error messages for misspelled discriminator values."""
        if not isinstance(data, dict):
            return data
        transport = data.get("transport")
        if isinstance(transport, dict):
            t_type = transport.get("type")
            if t_type and t_type not in _KNOWN_TRANSPORT_TYPES:
                raise ConfigurationError(
                    f"Unknown transport type {t_type!r}.  "
                    f"Valid options: {sorted(_KNOWN_TRANSPORT_TYPES)}"
                )
        renderer = data.get("renderer")
        if isinstance(renderer, dict):
            r_type = renderer.get("type")
            if r_type and r_type not in _KNOWN_RENDERER_TYPES:
                raise ConfigurationError(
                    f"Unknown renderer type {r_type!r}.  "
                    f"Valid options: {sorted(_KNOWN_RENDERER_TYPES)}"
                )
        return data

    @field_validator("phase")
    @classmethod
    def _valid_phase(cls, value: str) -> str:
        valid_phases = {
            "before_execute",
            "after_execute",
            "on_failure",
            "before_rollback",
            "after_rollback",
        }
        if value not in valid_phases:
            raise ValueError(f"Unknown phase {value!r}.  Valid: {sorted(valid_phases)}")
        return value


# ---------------------------------------------------------------------------
# NotificationsRootConfig — what lives under the YAML key ``notifications:``.
# ---------------------------------------------------------------------------


class NotificationsRootConfig(BaseModel):
    """Top-level shape for the ``notifications:`` key in YAML.

    Attributes:
        allow_templated_renderers: Opt-in flag for the Jinja renderer.
            **Default off.**  Setting this to True is a deliberate signal
            that the operator accepts the trust model documented in
            ``docs/reference/notification-context.md``.
        hooks: List of notification configurations.
    """

    allow_templated_renderers: bool = False
    hooks: list[NotificationConfig] = []

    @model_validator(mode="after")
    def _check_jinja_gate(self) -> NotificationsRootConfig:
        if not self.allow_templated_renderers:
            for hook in self.hooks:
                if isinstance(hook.renderer, JinjaRendererConfig):
                    raise ConfigurationError(
                        f"Hook {hook.id!r} uses renderer type 'jinja' but "
                        "`notifications.allow_templated_renderers` is not set to true.  "
                        "Set it explicitly to enable Jinja templating "
                        "(opt-in by design — see docs/reference/notification-context.md)."
                    )
        return self


def load_notifications_config(raw: dict) -> NotificationsRootConfig:
    """Parse and validate a raw notifications dict, expanding env vars.

    Args:
        raw: The dict loaded from the ``notifications:`` key of the
            environment YAML.

    Returns:
        Validated :class:`NotificationsRootConfig`.

    Raises:
        ConfigurationError: On missing env vars, unknown discriminator
            values, or Jinja-without-opt-in.
    """
    expanded = _expand_env_vars(raw)
    try:
        return NotificationsRootConfig.model_validate(expanded)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"Invalid notifications config: {exc}") from exc
