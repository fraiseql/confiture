"""Pre-flight migration checks.

Filesystem-only checks that require no database connection:
- Reversibility: does every .up.sql have a matching .down.sql?
- Duplicate versions: are there multiple files with the same version prefix?
- Non-transactional statements: does any migration contain DDL that cannot run in a transaction?
"""

from __future__ import annotations

from pathlib import Path

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)
from confiture.models.results import MigrationPreflightInfo, PreflightResult


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
            )
        )

    # Duplicate version detection
    duplicates = find_duplicate_migration_versions(migrations_dir)
    dup_dict = {v: [str(f.name) for f in files] for v, files in duplicates.items()}

    return PreflightResult(
        migrations=infos,
        duplicate_versions=dup_dict,
    )
