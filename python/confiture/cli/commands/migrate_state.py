"""Compatibility shim: `migrate_state` is now `confiture.cli.commands.migrate.*` (Phase 04, Cycle 8).

Re-exports every name this module used to define; removed in a later release.
"""

from __future__ import annotations

from confiture.cli.commands.migrate.baseline import _baseline_from_db_flow, migrate_baseline
from confiture.cli.commands.migrate.rebuild import migrate_rebuild
from confiture.cli.commands.migrate.reinit import migrate_reinit

__all__ = [
    "_baseline_from_db_flow",
    "migrate_baseline",
    "migrate_rebuild",
    "migrate_reinit",
]
