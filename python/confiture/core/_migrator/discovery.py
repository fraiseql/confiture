"""Migration file discovery utilities."""

from __future__ import annotations

from pathlib import Path


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
