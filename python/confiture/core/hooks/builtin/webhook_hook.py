"""Generic webhook notification hook."""

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
class WebhookConfig:
    """Configuration for generic webhook notification hook."""

    url: str
    method: str = "POST"  # HTTP method
    headers: dict[str, str] | None = None  # Custom headers
    template: dict | None = None  # Custom payload template
    send_on_success: bool = True
    send_on_failure: bool = True


class WebhookNotificationHook(Hook[ExecutionContext]):
    """Send migration status to any HTTP webhook endpoint.

    Registers on HookPhase.after_execute. Sends customizable JSON payloads.
    Can be configured for any webhook-compatible service.
    """

    def __init__(self, config: WebhookConfig) -> None:
        super().__init__(
            hook_id="builtin.webhook",
            name="Webhook Notification",
            priority=9,  # run last
        )
        self._config = config

    async def execute(
        self,
        context: HookContext[ExecutionContext],
    ) -> HookResult:
        ctx = context.get_data()

        # Check if we should send based on success/failure settings
        success = ctx.metadata.get("success", True)
        if success and not self._config.send_on_success:
            return HookResult(success=True, stats={"skipped": "success notification disabled"})
        if not success and not self._config.send_on_failure:
            return HookResult(success=True, stats={"skipped": "failure notification disabled"})

        payload = self._build_payload(ctx)

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self._config.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Confiture/0.8.21",
                    **(self._config.headers or {}),
                },
                method=self._config.method,
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    return HookResult(success=True, stats={"status_code": resp.status})
                return HookResult(
                    success=False,
                    error=f"Webhook returned HTTP {resp.status}",
                )

        except Exception as exc:
            logger.warning("Webhook notification failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _build_payload(self, ctx: ExecutionContext) -> dict:
        """Build webhook payload, using template if provided."""
        migration_name = ctx.metadata.get("migration_name", "unknown")
        direction = ctx.metadata.get("direction", "unknown")
        success = ctx.metadata.get("success", True)
        error = ctx.metadata.get("error")

        # Use custom template if provided
        if self._config.template:
            payload = dict(self._config.template)  # Copy template

            # Replace template variables
            def replace_vars(obj):
                if isinstance(obj, str):
                    return obj.format(
                        migration_name=migration_name,
                        direction=direction,
                        success=success,
                        error=error or "",
                        duration_ms=ctx.elapsed_time_ms,
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                elif isinstance(obj, dict):
                    return {k: replace_vars(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [replace_vars(item) for item in obj]
                else:
                    return obj

            return replace_vars(payload)

        # Default payload structure
        return {
            "event": "migration_complete",
            "timestamp": datetime.now(UTC).isoformat(),
            "migration": {
                "name": migration_name,
                "direction": direction,
                "success": success,
                "duration_ms": ctx.elapsed_time_ms,
                "error": error,
            },
            "metadata": ctx.metadata,
        }
