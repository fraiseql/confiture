"""Post-migration Slack notification via webhook."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlackConfig:
    """Configuration for Slack notification hook."""

    webhook_url: str
    channel: str | None = None  # override webhook default
    mention_on_failure: str | None = None  # e.g. "@oncall"


class SlackNotificationHook(Hook[ExecutionContext]):
    """Post migration status to Slack via incoming webhook.

    Registers on HookPhase.after_execute. Posts color-coded messages
    (green=success, red=failure). Never blocks migrations on failure.
    """

    def __init__(self, config: SlackConfig) -> None:
        super().__init__(
            hook_id="builtin.slack",
            name="Slack Notification",
            priority=9,  # run last
        )
        self._config = config

    async def execute(
        self,
        context: HookContext[ExecutionContext],
    ) -> HookResult:
        ctx = context.get_data()
        payload = self._build_payload(ctx)

        try:
            req = urllib.request.Request(
                self._config.webhook_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return HookResult(success=True)
                return HookResult(
                    success=False,
                    error=f"Slack returned HTTP {resp.status}",
                )
        except Exception as exc:
            # Never block migrations for notification failures
            logger.warning("Slack notification failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _build_payload(self, ctx: ExecutionContext) -> dict:
        # Extract migration info from metadata
        migration_name = ctx.metadata.get("migration_name", "unknown")
        direction = ctx.metadata.get("direction", "unknown")
        success = ctx.metadata.get("success", True)

        color = "#36a64f" if success else "#cc0000"
        status = "succeeded" if success else "FAILED"
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        text = f"Migration `{migration_name}` ({direction}) {status}"
        if not success and self._config.mention_on_failure:
            text += f" — {self._config.mention_on_failure}"

        payload: dict = {
            "attachments": [
                {
                    "color": color,
                    "title": f"Migration {status.title()}",
                    "text": text,
                    "fields": [
                        {"title": "Migration", "value": migration_name, "short": True},
                        {"title": "Direction", "value": direction, "short": True},
                        {"title": "Duration", "value": f"{ctx.elapsed_time_ms}ms", "short": True},
                        {"title": "Time", "value": now, "short": True},
                    ],
                }
            ],
        }
        if self._config.channel:
            payload["channel"] = self._config.channel
        return payload
