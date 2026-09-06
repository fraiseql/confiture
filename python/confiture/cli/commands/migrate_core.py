"""Compatibility shim: `migrate_core` is now `confiture.cli.commands.migrate.*` (Phase 04, Cycle 8).

Re-exports every name this module used to define; removed in a later release.
"""

from __future__ import annotations

from confiture.cli.commands.migrate._dry_run_render import _render_dry_run_analysis, _row_estimator
from confiture.cli.commands.migrate._settings import (
    _effective_rebuild_threshold,
    _load_environment_if_present,
    _MigrationSettings,
)
from confiture.cli.commands.migrate.current import migrate_current
from confiture.cli.commands.migrate.down import migrate_down, migrate_down_to
from confiture.cli.commands.migrate.estimate import migrate_estimate
from confiture.cli.commands.migrate.generate import migrate_generate
from confiture.cli.commands.migrate.status import migrate_status
from confiture.cli.commands.migrate.up import (
    _FailedMigration,
    _render_up_result,
    _UpReporter,
    migrate_up,
)

__all__ = [
    "_FailedMigration",
    "_MigrationSettings",
    "_UpReporter",
    "_effective_rebuild_threshold",
    "_load_environment_if_present",
    "_render_dry_run_analysis",
    "_render_up_result",
    "_row_estimator",
    "migrate_current",
    "migrate_down",
    "migrate_down_to",
    "migrate_estimate",
    "migrate_generate",
    "migrate_status",
    "migrate_up",
]
