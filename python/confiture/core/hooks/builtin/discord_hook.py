"""Discord notification hook via webhook."""

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
class DiscordConfig:
    """Configuration for Discord notification hook."""

    webhook_url: str
    username: str = "Confiture Migration"  # Bot display name
    avatar_url: str | None = None  # Bot avatar
    mention_on_failure: str | None = None  # e.g. "@everyone" or "<@user_id>"


class DiscordNotificationHook(Hook[ExecutionContext]):
    """Post migration status to Discord via webhook.

    Registers on HookPhase.after_execute. Posts rich embeds with
    migration details. Never blocks migrations on failure.
    """

    def __init__(self, config: DiscordConfig) -> None:
        super().__init__(
            hook_id="builtin.discord",
            name="Discord Notification",
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
                if resp.status == 204:  # Discord returns 204 on success
                    return HookResult(success=True)
                return HookResult(
                    success=False,
                    error=f"Discord returned HTTP {resp.status}",
                )
        except Exception as exc:
            logger.warning("Discord notification failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _build_payload(self, ctx: ExecutionContext) -> dict:
        """Build Discord webhook payload with rich embed."""
        migration_name = ctx.metadata.get("migration_name", "unknown")
        direction = ctx.metadata.get("direction", "unknown")
        success = ctx.metadata.get("success", True)
        error = ctx.metadata.get("error")

        status = "✅ Succeeded" if success else "❌ Failed"
        color = 0x28A745 if success else 0xDC3545  # Discord color values

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        # Build embed
        embed = {
            "title": f"Migration {status}",
            "color": color,
            "fields": [
                {"name": "Migration", "value": migration_name, "inline": True},
                {"name": "Direction", "value": direction, "inline": True},
                {"name": "Duration", "value": f"{ctx.elapsed_time_ms}ms", "inline": True},
                {"name": "Time", "value": now, "inline": False},
            ],
            "footer": {"text": "Confiture Migration Tool"},
        }

        # Add error field if present
        if error:
            embed["fields"].append({"name": "Error", "value": f"```{error}```", "inline": False})

        payload = {"username": self._config.username, "embeds": [embed]}

        # Add avatar if configured
        if self._config.avatar_url:
            payload["avatar_url"] = self._config.avatar_url

        # Add mention on failure
        content = ""
        if not success and self._config.mention_on_failure:
            content = self._config.mention_on_failure

        if content:
            payload["content"] = content

        return payload
