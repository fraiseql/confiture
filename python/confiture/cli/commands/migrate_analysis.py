"""Compatibility shim: `migrate_analysis` is now `confiture.cli.commands.migrate.*` (Phase 04, Cycle 8).

Re-exports every name this module used to define; removed in a later release.
"""

from __future__ import annotations

from confiture.cli.commands.migrate.diff import migrate_diff
from confiture.cli.commands.migrate.fix import migrate_fix
from confiture.cli.commands.migrate.fix_signatures import (
    _extract_function_source,
    migrate_fix_signatures,
)
from confiture.cli.commands.migrate.introspect import _introspect_payload, migrate_introspect
from confiture.cli.commands.migrate.preflight import (
    _collect_preflight_facts,
    _display_against_result,
    _display_change_set,
    _display_dependent_analysis,
    _lock_annotation,
    _preflight_replica_policy,
    _preflight_tracking_table,
    _preflight_version_from_filename,
    _resolve_preflight_pending,
    _run_dependent_check,
    _target_tracking_table_state,
    migrate_preflight,
)
from confiture.cli.commands.migrate.validate import (
    _pattern_catalog_payload,
    _reject_exclusive_composition,
    migrate_validate,
)
from confiture.cli.commands.migrate.verify import migrate_verify

__all__ = [
    "_collect_preflight_facts",
    "_display_against_result",
    "_display_change_set",
    "_display_dependent_analysis",
    "_extract_function_source",
    "_introspect_payload",
    "_lock_annotation",
    "_pattern_catalog_payload",
    "_preflight_replica_policy",
    "_preflight_tracking_table",
    "_preflight_version_from_filename",
    "_reject_exclusive_composition",
    "_resolve_preflight_pending",
    "_run_dependent_check",
    "_target_tracking_table_state",
    "migrate_diff",
    "migrate_fix",
    "migrate_fix_signatures",
    "migrate_introspect",
    "migrate_preflight",
    "migrate_validate",
    "migrate_verify",
]
