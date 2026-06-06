"""Pre-flight migration checks.

Filesystem-only checks that require no database connection:
- Reversibility: does every .up.sql have a matching .down.sql?
- Duplicate versions: are there multiple files with the same version prefix?
- Non-transactional statements: does any migration contain DDL that cannot run in a transaction?
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)
from confiture.models.results import MigrationPreflightInfo, PreflightResult

if TYPE_CHECKING:
    from confiture.models.results import PreflightIssue


def is_window_safe(issues: Iterable[PreflightIssue]) -> bool:
    """Typed blue-green window-safety verdict over a preflight issue set (#154).

    ``True`` iff confiture certifies every checked migration is **forward-compatible
    for a two-version shared-DB window** — both N-1 and N serving against one
    Postgres during the cutover. It is ``False`` when any ``PFLIGHT_REPLICA_*``
    finding is present: a replica-unsafe op, **or** a non-SQL ``.py`` migration the
    classifier could not read (``PFLIGHT_REPLICA_UNCLASSIFIED``).

    Window-safety is purely about forward-compatibility, **not** atomicity:
    reversibility (``PFLIGHT_MISSING_DOWN``) and transactionality
    (``PFLIGHT_NON_TRANSACTIONAL``) are reported as their own issues but do **not**
    gate this verdict. In a blue-green cutover, rollback is a traffic swap-back to
    the still-hot old version (no DB rollback), so a non-transactional op such as
    ``CREATE INDEX CONCURRENTLY`` — the canonical online-migration operation — is
    window-safe. Genuine apply failures are caught at the migrate step, before any
    traffic moves.

    This is the *whole* window-safety contract for the consumer: ``True`` means
    "every pending op is forward-compatible", ``False`` means "unsafe or
    uninspectable". The field's absence is treated fail-safe (blocked) by the
    consumer, so older confiture keeps working.
    """
    from confiture.core.linting.libraries.replica import replica_lint_codes

    replica_codes = replica_lint_codes()
    return not any(issue.code in replica_codes for issue in issues)


def preflight_exit_code(summary: dict[str, int], *, strict: bool) -> int:
    """Exit code for a completed preflight report (issue #148).

    Any error-severity issue → 7 (preflight failure, per #146). Under ``strict``,
    warnings also fail (→ 7). Otherwise 0. A clean run and a warnings-only
    non-strict run both exit 0.
    """
    if summary.get("errors", 0) > 0:
        return 7
    if strict and summary.get("warnings", 0) > 0:
        return 7
    return 0


def run_preflight(
    migrations_dir: Path,
    *,
    versions: list[str] | None = None,
) -> PreflightResult:
    """Run pre-flight checks on migration files.

    Args:
        migrations_dir: Directory containing migration files.
        versions: If provided, only check these version prefixes.

    Returns:
        PreflightResult with per-migration analysis and aggregate checks.
    """
    if not migrations_dir.exists():
        return PreflightResult(migrations=[])

    # Discover migration files (.up.sql and .py)
    sql_files = sorted(migrations_dir.glob("*.up.sql"), key=lambda f: f.name)
    py_files = sorted(
        (
            f
            for f in migrations_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ),
        key=lambda f: f.name,
    )

    infos: list[MigrationPreflightInfo] = []

    for up_file in sql_files:
        version = _version_from_migration_filename(up_file.name)
        if versions is not None and version not in versions:
            continue
        base_name = up_file.name[: -len(".up.sql")]
        parts = base_name.split("_", 1)
        name = parts[1] if len(parts) > 1 else base_name
        down_file = up_file.parent / f"{base_name}.down.sql"

        # Analyze non-transactional statements
        non_txn: list[str] = []
        try:
            from confiture.core.migration_analyzer import MigrationAnalyzer

            sql_content = up_file.read_text(encoding="utf-8")
            non_txn = MigrationAnalyzer().analyze(sql_content)
        except ImportError:
            pass

        infos.append(
            MigrationPreflightInfo(
                version=version,
                name=name,
                has_down=down_file.exists(),
                non_transactional_statements=non_txn,
                filename=up_file.name,
            )
        )

    for py_file in py_files:
        version = _version_from_migration_filename(py_file.name)
        if versions is not None and version not in versions:
            continue
        base_name = py_file.stem
        parts = base_name.split("_", 1)
        name = parts[1] if len(parts) > 1 else base_name
        # Python migrations define down() in-class — assumed reversible
        infos.append(
            MigrationPreflightInfo(
                version=version,
                name=name,
                has_down=True,
                filename=py_file.name,
            )
        )

    # Duplicate version detection
    duplicates = find_duplicate_migration_versions(migrations_dir)
    dup_dict = {v: [str(f.name) for f in files] for v, files in duplicates.items()}

    return PreflightResult(
        migrations=infos,
        duplicate_versions=dup_dict,
    )
