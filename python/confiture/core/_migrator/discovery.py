"""Migration file discovery utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.core._migrator.engine import Migrator

logger = logging.getLogger(__name__)


def _version_from_migration_filename(filename: str) -> str:
    """Extract version prefix from a migration filename.

    Args:
        filename: Migration filename (e.g., "001_create_users.py")

    Returns:
        Version string (e.g., "001")
    """
    if filename.endswith(".up.sql"):
        filename = filename[:-7]
    elif filename.endswith(".down.sql"):
        filename = filename[:-9]
    return filename.split("_")[0]


def find_duplicate_migration_versions(migrations_dir: Path) -> dict[str, list[Path]]:
    """Find migration files that share the same version prefix.

    Standalone function (no Migrator instance needed). Scans .py and .up.sql
    files, groups by version prefix, returns only versions with >1 file.

    Args:
        migrations_dir: Directory containing migration files

    Returns:
        Dict mapping version strings to lists of conflicting file paths.
        Empty dict if no duplicates exist or directory doesn't exist.
    """
    if not migrations_dir.exists():
        return {}

    py_files = [
        f
        for f in migrations_dir.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    ]
    sql_files = list(migrations_dir.glob("*.up.sql"))
    all_files = py_files + sql_files

    version_map: dict[str, list[Path]] = {}
    for f in all_files:
        version = _version_from_migration_filename(f.name)
        version_map.setdefault(version, []).append(f)

    return {
        v: sorted(files, key=lambda p: p.name) for v, files in version_map.items() if len(files) > 1
    }


# ---------------------------------------------------------------------------
# Migrator-bound discovery operations (peeled from engine.py).
# Free functions taking the Migrator instance; the class keeps thin delegators.
# ---------------------------------------------------------------------------


def find_migration_files(migrator: Migrator, migrations_dir: Path | None = None) -> list[Path]:
    """Find all migration files (``.py`` and ``.up.sql``), sorted by version."""
    if migrations_dir is None:
        migrations_dir = Path("db") / "migrations"

    if not migrations_dir.exists():
        return []

    # Find all .py files (excluding __pycache__, __init__.py)
    py_files = [
        f
        for f in migrations_dir.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    ]

    # Find all .up.sql files (SQL migrations)
    sql_files = list(migrations_dir.glob("*.up.sql"))

    # Combine and sort by version
    all_files = py_files + sql_files
    return sorted(all_files, key=lambda f: migrator._version_from_filename(f.name))


def find_orphaned_sql_files(migrations_dir: Path | None = None) -> list[Path]:
    """Find ``.sql`` files that don't match the {NNN}_{name}.{up,down}.sql pattern."""
    if migrations_dir is None:
        migrations_dir = Path("db") / "migrations"

    if not migrations_dir.exists():
        return []

    # Find all .sql files
    all_sql_files = set(migrations_dir.glob("*.sql"))

    # Find all properly named migration files
    expected_files = set(migrations_dir.glob("*.up.sql")) | set(migrations_dir.glob("*.down.sql"))

    # Orphaned files are SQL files that don't match the expected pattern
    orphaned = all_sql_files - expected_files
    return sorted(orphaned, key=lambda f: f.name)


def fix_orphaned_sql_files(
    migrator: Migrator, migrations_dir: Path | None = None, dry_run: bool = False
) -> dict[str, list[tuple[str, str]]]:
    """Rename orphaned ``{NNN}_{name}.sql`` files to ``{NNN}_{name}.up.sql``.

    Returns ``{"renamed": [(old, new), ...], "errors": [(name, msg), ...]}``.
    """
    if migrations_dir is None:
        migrations_dir = Path("db") / "migrations"

    if not migrations_dir.exists():
        return {"renamed": [], "errors": []}

    orphaned_files = migrator.find_orphaned_sql_files(migrations_dir)
    renamed: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []

    for orphaned_file in orphaned_files:
        # Suggest renaming by adding .up suffix before .sql
        # Example: 001_create_users.sql -> 001_create_users.up.sql
        old_name = orphaned_file.name
        new_name = f"{orphaned_file.stem}.up.sql"
        new_path = orphaned_file.parent / new_name

        try:
            if not dry_run:
                # Check if target already exists
                if new_path.exists():
                    errors.append((old_name, f"Target file already exists: {new_name}"))
                    continue

                # Rename the file
                orphaned_file.rename(new_path)
                logger.info(f"Renamed migration file: {old_name} -> {new_name}")

            renamed.append((old_name, new_name))
        except Exception as e:
            errors.append((old_name, str(e)))
            logger.error(f"Failed to rename {old_name}: {e}")

    return {"renamed": renamed, "errors": errors}


def find_pending(migrator: Migrator, migrations_dir: Path | None = None) -> list[Path]:
    """Find migrations that have not been applied yet."""
    all_migrations = migrator.find_migration_files(migrations_dir)
    applied_versions = set(migrator.get_applied_versions())
    return [
        migration_file
        for migration_file in all_migrations
        if migrator._version_from_filename(migration_file.name) not in applied_versions
    ]
