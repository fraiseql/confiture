"""Turn a migration file into the ``Migration`` class it defines.

A ``.py`` migration is imported from its path; an ``.up.sql`` file becomes a
``FileSQLMigration`` with its ``.down.sql`` twin. This is the migrator's concern,
not the connection's: ``core.connection`` opens a database and knows nothing about
migrations.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from confiture.exceptions import MigrationError
from confiture.models.migration import Migration
from confiture.models.sql_file_migration import FileSQLMigration


def load_migration_module(migration_file: Path) -> ModuleType:
    """Dynamically load a migration Python module.

    Args:
        migration_file: Path to migration .py file

    Returns:
        Loaded module

    Raises:
        MigrationError: If module cannot be loaded
    """
    try:
        # Create module spec
        # A namespaced module name: a migration called ``json.py`` must not
        # replace the stdlib ``json`` in ``sys.modules``.
        module_name = f"confiture_migration_{migration_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, migration_file)
        if spec is None or spec.loader is None:
            raise MigrationError(
                f"Cannot load migration: {migration_file}",
                resolution_hint="Ensure the migration file exists and contains valid Python code",
            )

        # Load module
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        return module
    # Reason: importing a migration module executes user code; any failure is a MigrationError with the file
    except Exception as e:
        raise MigrationError(
            f"Failed to load migration {migration_file}: {e}",
            resolution_hint="Check the migration file for syntax errors or missing imports",
        ) from e


def get_migration_class(module: ModuleType) -> type:
    """Extract Migration subclass from loaded module.

    Args:
        module: Loaded Python module

    Returns:
        Migration class

    Raises:
        MigrationError: If no Migration class found
    """

    # Find Migration subclass in module
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, Migration) and attr is not Migration:
            return attr

    raise MigrationError(
        f"No Migration subclass found in {module}",
        resolution_hint="Ensure your migration file defines a class that inherits from confiture.models.migration.Migration",
    )


def load_migration_class(migration_file: Path) -> type:
    """Load a migration class from either Python or SQL file.

    This is the main entry point for loading migrations. It handles:
    - Python migrations (.py files) - loaded via importlib
    - SQL file migrations (.up.sql files) - converted to FileSQLMigration

    Args:
        migration_file: Path to migration file (.py or .up.sql)

    Returns:
        Migration class (not instance)

    Raises:
        MigrationError: If migration cannot be loaded
        FileNotFoundError: If SQL down file is missing

    Example:
        >>> # Python migration
        >>> cls = load_migration_class(Path("db/migrations/001_create_users.py"))
        >>> migration = cls(connection=conn)

        >>> # SQL migration
        >>> cls = load_migration_class(Path("db/migrations/002_add_posts.up.sql"))
        >>> migration = cls(connection=conn)
    """
    if migration_file.suffix == ".py":
        # Python migration
        module = load_migration_module(migration_file)
        return get_migration_class(module)
    elif migration_file.name.endswith(".up.sql"):
        # SQL file migration

        # Find the matching .down.sql file
        base_name = migration_file.name.replace(".up.sql", "")
        down_file = migration_file.parent / f"{base_name}.down.sql"

        if not down_file.exists():
            raise MigrationError(
                f"SQL migration {migration_file.name} has no matching .down.sql file.\n"
                f"Expected: {down_file}",
                resolution_hint=f"Create {down_file.name} with the rollback SQL for this migration",
            )

        return FileSQLMigration.from_files(migration_file, down_file)
    else:
        raise MigrationError(
            f"Unknown migration file type: {migration_file}",
            resolution_hint="Rename the file to use a .py or .up.sql extension",
        )
