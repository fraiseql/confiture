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
    testing without the boilerplate of manual importlib usage.

    Args:
        name: Migration filename without .py extension
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
        Load by full name:
        >>> Migration003 = load_migration("003_move_catalog_tables")
        >>> migration = Migration003(connection=conn)
        >>> migration.up()

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
        raise MigrationNotFoundError(
            f"Migrations directory not found: {migrations_dir.absolute()}"
        )

    # Find the migration file
    migration_file: Path | None = None

    if name is not None:
        # Load by exact name
        migration_file = migrations_dir / f"{name}.py"
        if not migration_file.exists():
            raise MigrationNotFoundError(
                f"Migration not found: {migration_file}\n"
                f"Hint: Make sure the file exists and the name is correct "
                f"(without .py extension)"
            )
    else:
        # Load by version prefix
        assert version is not None  # For type checker
        matching_files = list(migrations_dir.glob(f"{version}_*.py"))

        if not matching_files:
            raise MigrationNotFoundError(
                f"No migration found with version '{version}' in {migrations_dir}\n"
                f"Hint: Migration files should be named like '{version}_<name>.py'"
            )

        if len(matching_files) > 1:
            file_names = [f.name for f in matching_files]
            raise MigrationNotFoundError(
                f"Multiple migrations found with version '{version}': {file_names}\n"
                f"Hint: Use 'name' parameter to specify the exact migration"
            )

        migration_file = matching_files[0]

    # Load the migration module and extract the class
    try:
        module = load_migration_module(migration_file)
        migration_class = get_migration_class(module)
        return migration_class
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

    Args:
        version: Migration version prefix (e.g., "003")
        migrations_dir: Custom migrations directory

    Returns:
        Path to the migration file, or None if not found
    """
    if migrations_dir is None:
        migrations_dir = Path("db/migrations")

    if not migrations_dir.exists():
        return None

    matching_files = list(migrations_dir.glob(f"{version}_*.py"))
    return matching_files[0] if len(matching_files) == 1 else None
