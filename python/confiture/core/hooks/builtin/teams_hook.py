"""Microsoft Teams notification hook via webhook."""

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
class TeamsConfig:
    """Configuration for Microsoft Teams notification hook."""

    webhook_url: str
    mention_on_failure: str | None = None  # e.g. "@team" or "<at>John Doe</at>"


class TeamsNotificationHook(Hook[ExecutionContext]):
    """Post migration status to Microsoft Teams via webhook.

    Registers on HookPhase.after_execute. Posts adaptive cards with
    migration details. Never blocks migrations on failure.
    """

    def __init__(self, config: TeamsConfig) -> None:
        super().__init__(
            hook_id="builtin.teams",
            name="Teams Notification",
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
                    error=f"Teams returned HTTP {resp.status}",
                )
        except Exception as exc:
            logger.warning("Teams notification failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _build_payload(self, ctx: ExecutionContext) -> dict:
        """Build Teams adaptive card payload."""
        migration_name = ctx.metadata.get("migration_name", "unknown")
        direction = ctx.metadata.get("direction", "unknown")
        success = ctx.metadata.get("success", True)
        error = ctx.metadata.get("error")

        status = "✅ Succeeded" if success else "❌ Failed"
        color = "good" if success else "attention"  # Teams color names

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        # Build adaptive card
        card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"Migration {status}",
                    "weight": "Bolder",
                    "size": "Medium",
                    "color": color,
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "Migration:", "value": migration_name},
                        {"title": "Direction:", "value": direction},
                        {"title": "Duration:", "value": f"{ctx.elapsed_time_ms}ms"},
                        {"title": "Time:", "value": now},
                    ],
                },
            ],
        }

        # Add error details if present
        if error:
            card["body"].append(
                {
                    "type": "TextBlock",
                    "text": f"**Error:** {error}",
                    "color": "attention",
                    "wrap": True,
                }
            )

        # Add mention on failure
        if not success and self._config.mention_on_failure:
            card["body"].insert(
                0,
                {
                    "type": "TextBlock",
                    "text": self._config.mention_on_failure,
                    "weight": "Bolder",
                },
            )

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
