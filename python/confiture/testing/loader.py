"""Migration loader utility for testing.

Provides a simple API for loading migration classes without the boilerplate
of manual importlib usage.

Example:
    >>> from confiture.testing import load_migration
    >>> Migration003 = load_migration("003_move_catalog_tables")
    >>> Migration003 = load_migration(version="003")
"""

from pathlib import Path

from confiture.core.connection import get_migration_class, load_migration_module
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration
from confiture.models.sql_file_migration import FileSQLMigration


class MigrationNotFoundError(MigrationError):
    """Raised when a migration file cannot be found."""

    pass


class MigrationLoadError(MigrationError):
    """Raised when a migration cannot be loaded from file."""

    pass


def load_migration(
    name: str | None = None,
    *,
    version: str | None = None,
    migrations_dir: Path | None = None,
) -> type[Migration]:
    """Load a migration class by name or version.

    This function provides a convenient way to load migration classes for
    testing without the boilerplate of manual importlib usage. It supports
    both Python migrations (.py) and SQL-only migrations (.up.sql/.down.sql).

    Args:
        name: Migration filename without extension
            (e.g., "003_move_catalog_tables")
        version: Migration version prefix (e.g., "003"). If provided,
            searches for any migration starting with this version.
        migrations_dir: Custom migrations directory. Defaults to "db/migrations"
            relative to current working directory.

    Returns:
        The Migration class (not an instance). You can instantiate it with
        a connection: `migration = MigrationClass(connection=conn)`

    Raises:
        MigrationNotFoundError: If no migration file matches the name/version
        MigrationLoadError: If the migration file cannot be loaded
        ValueError: If neither name nor version is provided, or both are provided

    Example:
        Load Python migration by full name:
        >>> Migration003 = load_migration("003_move_catalog_tables")
        >>> migration = Migration003(connection=conn)
        >>> migration.up()

        Load SQL-only migration (automatically detected):
        >>> Migration004 = load_migration("004_add_indexes")
        >>> # This works if 004_add_indexes.up.sql and .down.sql exist

        Load by version prefix:
        >>> Migration = load_migration(version="003")

        Load from custom directory:
        >>> Migration = load_migration("003_test", migrations_dir=Path("/tmp/migrations"))
    """
    # Validate arguments
    if name is None and version is None:
        raise ValueError("Either 'name' or 'version' must be provided")
    if name is not None and version is not None:
        raise ValueError("Provide either 'name' or 'version', not both")

    # Determine migrations directory
    if migrations_dir is None:
        migrations_dir = Path("db/migrations")

    if not migrations_dir.exists():
        raise MigrationNotFoundError(f"Migrations directory not found: {migrations_dir.absolute()}")

    # Find the migration file
    if name is not None:
        return _load_by_name(name, migrations_dir)
    else:
        assert version is not None  # For type checker
        return _load_by_version(version, migrations_dir)


def _load_by_name(name: str, migrations_dir: Path) -> type[Migration]:
    """Load migration by exact name, trying Python first then SQL."""
    # Try Python migration first
    py_file = migrations_dir / f"{name}.py"
    if py_file.exists():
        return _load_python_migration(py_file)

    # Try SQL-only migration
    up_file = migrations_dir / f"{name}.up.sql"
    down_file = migrations_dir / f"{name}.down.sql"

    if up_file.exists() and down_file.exists():
        return FileSQLMigration.from_files(up_file, down_file)

    # Neither found - provide helpful error message
    if up_file.exists() and not down_file.exists():
        raise MigrationNotFoundError(
            f"SQL migration found but missing .down.sql file.\n"
            f"Found: {up_file}\n"
            f"Missing: {down_file}\n"
            f"Hint: Create {down_file.name} with the rollback SQL"
        )

    raise MigrationNotFoundError(
        f"Migration not found: {name}\n"
        f"Searched for:\n"
        f"  - {py_file} (Python migration)\n"
        f"  - {up_file} + {down_file} (SQL-only migration)\n"
        f"Hint: Make sure the migration files exist in {migrations_dir}"
    )


def _load_by_version(version: str, migrations_dir: Path) -> type[Migration]:
    """Load migration by version prefix, trying Python first then SQL."""
    # Find Python migrations
    py_files = list(migrations_dir.glob(f"{version}_*.py"))

    # Find SQL-only migrations
    sql_up_files = list(migrations_dir.glob(f"{version}_*.up.sql"))

    # Collect all matches
    all_matches: list[tuple[str, Path]] = []
    for f in py_files:
        all_matches.append(("python", f))
    for up_f in sql_up_files:
        # Check that .down.sql exists
        base_name = up_f.name.replace(".up.sql", "")
        down_f = migrations_dir / f"{base_name}.down.sql"
        if down_f.exists():
            all_matches.append(("sql", up_f))

    if not all_matches:
        raise MigrationNotFoundError(
            f"No migration found with version '{version}' in {migrations_dir}\n"
            f"Hint: Migration files should be named like:\n"
            f"  - {version}_<name>.py (Python migration)\n"
            f"  - {version}_<name>.up.sql + {version}_<name>.down.sql (SQL-only)"
        )

    if len(all_matches) > 1:
        file_names = [f.name for _, f in all_matches]
        raise MigrationNotFoundError(
            f"Multiple migrations found with version '{version}': {file_names}\n"
            f"Hint: Use 'name' parameter to specify the exact migration"
        )

    migration_type, migration_file = all_matches[0]

    if migration_type == "python":
        return _load_python_migration(migration_file)
    else:
        # SQL migration
        base_name = migration_file.name.replace(".up.sql", "")
        down_file = migrations_dir / f"{base_name}.down.sql"
        return FileSQLMigration.from_files(migration_file, down_file)


def _load_python_migration(migration_file: Path) -> type[Migration]:
    """Load a Python migration from file."""
    try:
        module = load_migration_module(migration_file)
        migration_class = get_migration_class(module)
        return migration_class  # type: ignore[return-value]
    except MigrationError:
        raise
    except Exception as e:
        raise MigrationLoadError(
            f"Failed to load migration from {migration_file}: {e}\n"
            f"Hint: Check that the file contains a valid Migration subclass"
        ) from e


def find_migration_by_version(
    version: str,
    migrations_dir: Path | None = None,
) -> Path | None:
    """Find a migration file by version prefix.

    Searches for both Python migrations (.py) and SQL-only migrations
    (.up.sql/.down.sql pairs).

    Args:
        version: Migration version prefix (e.g., "003")
        migrations_dir: Custom migrations directory

    Returns:
        Path to the migration file (.py or .up.sql), or None if not found
        or if multiple migrations have the same version.
    """
    if migrations_dir is None:
        migrations_dir = Path("db/migrations")

    if not migrations_dir.exists():
        return None

    # Find Python migrations
    py_files = list(migrations_dir.glob(f"{version}_*.py"))

    # Find SQL-only migrations (with matching .down.sql)
    sql_files: list[Path] = []
    for up_file in migrations_dir.glob(f"{version}_*.up.sql"):
        base_name = up_file.name.replace(".up.sql", "")
        down_file = migrations_dir / f"{base_name}.down.sql"
        if down_file.exists():
            sql_files.append(up_file)

    all_files = py_files + sql_files
    return all_files[0] if len(all_files) == 1 else None
