"""The ``--dry-run`` summary: what confiture knows about the pending migrations.

No constants. Each migration carries the change-set classification of its SQL
(``core.change_set``), its statement count, the row estimate PostgreSQL's
statistics hold for the tables it touches, and its findings; whatever cannot be
known is ``null``. ``.py`` migrations are unclassified by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg

from confiture.core import large_tables as _core_large_tables
from confiture.core.change_set import ChangeEntry, build_change_set
from confiture.core.ledger import split_qualified_table
from confiture.core.migrator import discover_migration_files, parse_migration_filename
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.sql_lexer import split_statements

RowEstimator = Callable[[str], "int | None"]
UNSAFE_FROM = RiskTier.LOCK_RISKY
SAFE_LINE = "✓ All migrations appear safe to execute"


def row_estimator(connection: Any) -> RowEstimator:
    """``table -> estimated rows`` from ``pg_class.reltuples``; None when unknown."""

    estimator = _core_large_tables.TableSizeEstimator(connection)

    def estimate(table: str) -> int | None:
        try:
            value = estimator.get_row_count_estimate(split_qualified_table(table)[1])
        except (psycopg.Error, ValueError):
            return None
        return value if value > 0 else None

    return estimate


def _is_unsafe(tier: RiskTier | None) -> bool:
    return tier is not None and tier.severity >= UNSAFE_FROM.severity


def _tables(entries: list[ChangeEntry]) -> list[str]:
    seen: dict[str, None] = {}
    for entry in entries:
        obj = entry.object
        if obj and not obj.endswith((".sql", ".py")) and obj != "unknown":
            seen.setdefault(obj, None)
    return list(seen)


def build_dry_run_summary(
    pending: list[tuple[str, str]],
    *,
    migrations_dir: Path,
    migration_id: str,
    mode: str,
    estimate_rows: RowEstimator | None = None,
) -> dict[str, Any]:
    """The JSON payload of ``migrate up --dry-run`` / ``migrate down --dry-run``."""
    versions = [version for version, _ in pending]
    files = {
        parse_migration_filename(p.name)[0]: p for p in discover_migration_files(migrations_dir)
    }
    by_version: dict[str, list[ChangeEntry]] = {v: [] for v in versions}
    for entry in build_change_set(migrations_dir, versions=versions).changes:
        if entry.migration in by_version:
            by_version[entry.migration].append(entry)

    migrations: list[dict[str, Any]] = []
    statements_total = 0
    for version, name in pending:
        entries = by_version.get(version, [])
        path = files.get(version)
        statements: int | None = None
        if path is not None and path.name.endswith(".up.sql"):
            statements = len(split_statements(path.read_text()))
            statements_total += statements
        tier = worst_tier(entry.tier for entry in entries)
        estimates = [estimate_rows(t) for t in _tables(entries)] if estimate_rows else []
        known = [e for e in estimates if e is not None]
        migrations.append(
            {
                "version": version,
                "name": name,
                "classification": tier.value if tier else None,
                "unsafe": _is_unsafe(tier),
                "statements": statements,
                "estimated_rows": max(known) if known else None,
                "findings": [entry.to_dict() for entry in entries],
            }
        )

    unsafe_count = sum(1 for m in migrations if m["unsafe"])
    unclassified_count = sum(1 for m in migrations if m["classification"] is None)
    warnings: list[str] = []
    if unclassified_count:
        warnings.append(
            f"{unclassified_count} migration(s) could not be classified (non-SQL or unparsable) — review by hand"
        )
    return {
        "migration_id": migration_id,
        "mode": mode,
        "statements_analyzed": statements_total,
        "migrations": migrations,
        "summary": {
            "unsafe_count": unsafe_count,
            "unclassified_count": unclassified_count,
            "has_unsafe_statements": unsafe_count > 0,
        },
        "warnings": warnings,
    }


def render_dry_run_text(summary: dict[str, Any], *, rollback: bool = False) -> str:
    """The human rendering of :func:`build_dry_run_summary` — deterministic, no timings."""
    verb = "rollback" if rollback else "apply"
    lines = [
        "Rollback Analysis Summary" if rollback else "Migration Analysis Summary",
        "=" * 80,
        f"Migrations to {verb}: {len(summary['migrations'])}",
        "",
    ]
    for m in summary["migrations"]:
        tier = m["classification"] or "unclassified"
        count = "? statements" if m["statements"] is None else f"{m['statements']} statement(s)"
        rows = "rows: unknown" if m["estimated_rows"] is None else f"rows≈{m['estimated_rows']:,}"
        lines.append(f"  {m['version']}: {m['name']}  [{tier}]  {count} | {rows}")
        for finding in m["findings"]:
            if (
                _is_unsafe(RiskTier(finding["tier"]) if finding.get("tier") else None)
                or "tier" not in finding
            ):
                detail = f" — {finding['detail']}" if finding.get("detail") else ""
                lines.append(f"    ! {finding['kind']} {finding['object']}{detail}")
    lines.append("")
    if rollback:
        lines.append("⚠️  Rollback will undo these migrations")
    elif summary["summary"]["unsafe_count"] == 0 and summary["summary"]["unclassified_count"] == 0:
        lines.append(SAFE_LINE)
    else:
        if summary["summary"]["unsafe_count"]:
            lines.append(
                f"⚠️  {summary['summary']['unsafe_count']} unsafe change(s) — review before applying"
            )
        lines.extend(f"⚠️  {warning}" for warning in summary["warnings"])
    lines.append("=" * 80)
    return "\n".join(lines) + "\n"
