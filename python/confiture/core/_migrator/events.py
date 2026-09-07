"""Progress events emitted by :meth:`MigratorSession.up`.

The session is the one apply loop; a CLI that wants live output ("applying
X…", "acquired lock") observes it through these events instead of running a
loop of its own. Events are informational — nothing about the result depends
on whether anyone listens.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

UpEventKind = Literal[
    "lock_acquired",
    "baseline_probe",
    "baseline_detected",
    "baseline_missed",
    "view_helpers_installed",
    "checksums_verified",
    "pending",
    "applying",
    "applied",
    "failed",
    "superuser_halt",
    "skipped_non_transactional",
    "target_reached",
    "stage_started",
    "stage_done",
    "backfill_progress",
]


@dataclass(frozen=True)
class UpEvent:
    """One step of an ``up()`` run.

    Attributes:
        kind: What happened.
        version: The migration concerned, when there is one.
        name: Its name, when there is one.
        message: Human-readable detail (a failure's message, a baseline note).
        elapsed_ms: Wall-clock time for ``applied``.
    """

    kind: UpEventKind
    version: str | None = None
    name: str | None = None
    message: str = ""
    elapsed_ms: int | None = None

    @property
    def label(self) -> str:
        """``<version>_<name>`` when both are known."""
        if self.version and self.name:
            return f"{self.version}_{self.name}"
        return self.version or self.name or ""


UpObserver = Callable[[UpEvent], None]


def emit(observer: UpObserver | None, kind: UpEventKind, **fields: object) -> None:
    """Deliver ``UpEvent(kind, **fields)`` to *observer* if there is one."""
    if observer is not None:
        observer(UpEvent(kind, **fields))
