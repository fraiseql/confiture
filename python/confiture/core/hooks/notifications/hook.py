"""NotificationHook — the single Hook subclass that ties Transport + Renderer.

Replaces the legacy per-service Hook classes (SlackNotificationHook,
DiscordHook, TeamsHook, EmailHook, WebhookHook).  Cycle 9 ships shims that
keep those names importable but emit DeprecationWarning.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import Renderer
from confiture.core.hooks.notifications.transport import Transport

logger = logging.getLogger(__name__)


class NotificationHook(Hook[ExecutionContext]):
    """Pipe ``ExecutionContext`` → ``NotificationContext`` → render → send.

    The hook never blocks a migration on a notification failure — any
    transport error is logged and swallowed.

    Args:
        hook_id: Unique hook identifier (e.g. ``notifications.prod-slack``).
        transport: Where the rendered payload goes.
        renderer: How the payload is shaped.
        phase: Migration phase to register on.  Stored for the executor.
        priority: Hook execution priority.  Defaults to 9 (last).
    """

    def __init__(
        self,
        hook_id: str,
        transport: Transport,
        renderer: Renderer,
        *,
        phase: str = "after_execute",
        priority: int = 9,
    ) -> None:
        super().__init__(
            hook_id=hook_id,
            name=f"NotificationHook[{hook_id}]",
            priority=priority,
        )
        self.transport = transport
        self.renderer = renderer
        self.phase = phase

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        ctx = context.get_data()
        notif_ctx = _build_notification_context(ctx)

        try:
            payload = self.renderer.render(notif_ctx)
        except Exception as exc:
            logger.warning("NotificationHook %s render failed: %s", self.id, exc)
            return HookResult(success=False, error=str(exc))

        try:
            self.transport.send(payload)
            return HookResult(success=True)
        except Exception as exc:
            # Never block migrations on a notification failure.
            logger.warning(
                "NotificationHook %s transport failed (swallowed): %s",
                self.id,
                exc,
            )
            return HookResult(success=False, error=str(exc))


def _build_notification_context(ctx: ExecutionContext) -> NotificationContext:
    """Project the live ``ExecutionContext`` into a frozen ``NotificationContext``.

    Renderer code never touches the live context — keeps renderers pure and
    snapshot-comparable across tests.
    """
    meta = ctx.metadata
    return NotificationContext(
        migration_name=str(meta.get("migration_name", "unknown")),
        migration_version=str(meta.get("migration_version", "")),
        direction=str(meta.get("direction", "up")),
        success=bool(meta.get("success", True)),
        duration_ms=int(ctx.elapsed_time_ms),
        database_name=str(meta.get("database_name", "")),
        schema=str(meta.get("schema", "public")),
        timestamp=datetime.now(UTC),
        rows_affected=int(ctx.rows_affected),
        error=meta.get("error"),
        migrations_applied=list(meta.get("migrations_applied", [])),
    )
