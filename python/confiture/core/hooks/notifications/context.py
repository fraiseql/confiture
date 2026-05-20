"""NotificationContext — the value object renderers consume.

Decoupled from the live ``ExecutionContext`` so renderers stay pure (input
→ ``TransportPayload``) and snapshot-comparable across tests.  The
:class:`NotificationHook` builds a ``NotificationContext`` from the live
``ExecutionContext`` at fire time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class NotificationContext:
    """A snapshot of migration state at notification time.

    Attributes:
        migration_name: Human-readable migration name (e.g. ``add_user_bio``).
        migration_version: Version string (e.g. ``20260520143015``).
        direction: ``up`` or ``down``.
        success: Whether the migration succeeded.
        duration_ms: Wall-clock duration of the migration in milliseconds.
        database_name: Database name parsed from the connection URL.
        schema: Schema name (often ``public``).
        timestamp: When the migration finished.  Defaults to ``datetime.now(UTC)``.
        rows_affected: Total rows changed by the migration's DML.
        error: When ``success=False``, the error message from the failed run.
        migrations_applied: When this event represents a batch, the names
            of all migrations applied.  Empty list otherwise.
    """

    migration_name: str = "unknown"
    migration_version: str = ""
    direction: str = "up"
    success: bool = True
    duration_ms: int = 0
    database_name: str = ""
    schema: str = "public"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    rows_affected: int = 0
    error: str | None = None
    migrations_applied: list[str] = field(default_factory=list)

    @property
    def status_word(self) -> str:
        return "succeeded" if self.success else "FAILED"

    @property
    def timestamp_iso(self) -> str:
        return self.timestamp.isoformat(timespec="seconds")

    @property
    def timestamp_human(self) -> str:
        """Format used by legacy hooks: ``YYYY-MM-DD HH:MM UTC``."""
        return self.timestamp.strftime("%Y-%m-%d %H:%M UTC")
