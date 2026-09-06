"""Session-level policies for ``up()``: strict mode, view helpers, auto-baseline.

These are the decisions the CLI used to take in its own apply loop. They live
here so the library path and the CLI path make them the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.core._migrator.events import UpObserver, emit
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from confiture.config.environment import Environment
    from confiture.core._migrator.engine import Migrator


def resolve_strict_mode(flag: bool | None, config: Environment | None) -> bool:
    """An explicit flag wins; otherwise the environment's ``migration.strict_mode``."""
    if flag is not None:
        return flag
    return bool(config is not None and config.migration.strict_mode)


def wants_view_helpers(flag: bool | None, config: Environment | None) -> bool:
    """An explicit flag wins; otherwise ``migration.view_helpers: auto``."""
    if flag is not None:
        return flag
    return config is not None and config.migration.view_helpers == "auto"


def install_view_helpers(conn: Any, on_event: UpObserver | None = None) -> bool:
    """Install the view helper functions if they are missing. Returns True if it did."""
    from confiture.core.view_manager import ViewManager

    manager = ViewManager(conn)
    if manager.helpers_installed():
        return False
    manager.install_helpers()
    emit(on_event, "view_helpers_installed", message="migration.view_helpers: auto")
    return True


def auto_baseline(
    *,
    conn: Any,
    migrator: Migrator,
    migrations_dir: Path,
    snapshots_dir: Path,
    on_event: UpObserver | None = None,
) -> str | None:
    """Self-baseline a database whose ledger is missing (``--auto-detect-baseline``).

    Runs under the migration lock, before the ledger is created. Returns the
    detected snapshot version, or None when no ledger was created because the
    ledger already exists or no snapshot matched.

    Raises:
        ConfigurationError: the ledger name resolves nowhere for this session
            but a relation of that name exists in another schema (#188 — the
            one path that rewrites history unprompted refuses rather than
            guesses); or the snapshots directory is missing or empty.
    """
    from confiture.core import ledger as _ledger

    if migrator.tracking_table_exists():
        return None

    table = migrator.migration_table
    elsewhere = _ledger.find_ledger_relations(conn, table)
    if elsewhere:
        raise ConfigurationError(
            f"--auto-detect-baseline: {table!r} does not resolve for this session, but a "
            f"relation of that name exists in {', '.join(elsewhere)}. Refusing to "
            f"auto-baseline: doing so would create a second ledger and mark every migration "
            f"applied in it.",
            resolution_hint=(
                "Point at the existing ledger — set `migration.tracking_table` to "
                f"{elsewhere[0]!r}, or put its schema on the connection's search_path — then "
                "re-run. If the ledger really is meant to be new, drop or rename the other "
                "relation first."
            ),
        )
    if not snapshots_dir.exists():
        raise ConfigurationError(
            f"--auto-detect-baseline: snapshots directory not found: {snapshots_dir}",
            resolution_hint=(
                "Generate snapshots with 'confiture migrate snapshot' or remove "
                "--auto-detect-baseline"
            ),
        )
    if not list(snapshots_dir.glob("*.sql")):
        raise ConfigurationError(
            f"--auto-detect-baseline: no snapshot files found in {snapshots_dir}",
            resolution_hint=(
                "Generate snapshots with 'confiture migrate snapshot' or remove "
                "--auto-detect-baseline"
            ),
        )

    from confiture.core.baseline_detector import BaselineDetector

    emit(
        on_event, "baseline_probe", message=f"{table} missing — attempting auto-detect baseline..."
    )
    detector = BaselineDetector(snapshots_dir)
    live_sql = detector.introspect_live_schema(conn)
    detected = detector.find_matching_snapshot(live_sql)
    if detected:
        migrator.initialize()
        migrator.baseline_through(detected, migrations_dir)
        emit(
            on_event,
            "baseline_detected",
            version=detected,
            message=f"auto-baselined through {detected}",
        )
        return detected

    closest = detector.last_closest
    if closest:
        version, ratio = closest
        note = f"no exact snapshot match (closest: {version}, {ratio:.0%} similar)"
    else:
        note = "no matching snapshot found"
    emit(on_event, "baseline_missed", message=f"{note} — proceeding with empty baseline")
    return None
