"""What ``MigratorSession.up`` was asked for, as the one value the apply loop reads.

``up()`` keeps its keyword parameters — fraisier and printoptim call them, and
``tests/contract/test_consumer_symbols.py`` pins the shapes — but nothing below it
forwards them by name: a keyword forwarded through a chain of functions is silently
ignored wherever one link drops it. :class:`UpOptions` is built once, at the
facade; ``tests/unit/test_one_session_signature.py`` holds that every keyword ``up()``
accepts is a field of it and that every field is given one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from confiture.core._migrator.events import UpObserver
from confiture.core.backfill import BackfillSettings


@dataclass(frozen=True)
class UpOptions:
    """``MigratorSession.up``'s arguments, the lock settings already resolved."""

    target: str | None = None
    dry_run: bool = False
    dry_run_execute: bool = False
    verify_checksums: bool = True
    on_checksum_mismatch: str = "fail"
    force: bool = False
    lock_timeout: int = 30000
    no_lock: bool = False
    require_reversible: bool = False
    allow_destructive: bool = False
    online: bool = False
    backfill: BackfillSettings | None = None
    strict_mode: bool | None = None
    auto_baseline: Path | None = None
    install_view_helpers: bool | None = None
    on_event: UpObserver | None = None
    batch: Any | None = None
