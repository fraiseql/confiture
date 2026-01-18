"""Database connection management for CLI commands."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import yaml

from confiture.exceptions import MigrationError


def load_config(config_file: Path) -> dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_file: Path to configuration file

    Returns:
        Configuration dictionary

    Raises:
        MigrationError: If config file is invalid
    """
    if not config_file.exists():
        raise MigrationError(f"Configuration file not found: {config_file}")

    try:
        with open(config_file) as f:
            config: dict[str, Any] = yaml.safe_load(f)
        return config
    except yaml.YAMLError as e:
        raise MigrationError(f"Invalid YAML configuration: {e}") from e


def create_connection(config: dict[str, Any] | Any) -> psycopg.Connection:
    """Create database connection from configuration.

    Args:
        config: Configuration dictionary with 'database' section, 'database_url', or DatabaseConfig instance

    Returns:
        PostgreSQL connection

    Raises:
        MigrationError: If connection fails
    """
    from confiture.config.environment import DatabaseConfig

    try:
        # Handle DatabaseConfig instance
        if isinstance(config, DatabaseConfig):
            config_dict = config.to_dict()
            db_config = config_dict.get("database", {})
            conn = psycopg.connect(
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 5432),
                dbname=db_config.get("database", "postgres"),
                user=db_config.get("user", "postgres"),
                password=db_config.get("password", ""),
            )
        else:
            # Check for database_url first
            database_url = config.get("database_url")
            if database_url:
                conn = psycopg.connect(database_url)
            else:
                # Fall back to database section
                db_config = config.get("database", {})
                conn = psycopg.connect(
                    host=db_config.get("host", "localhost"),
                    port=db_config.get("port", 5432),
                    dbname=db_config.get("database", "postgres"),
                    user=db_config.get("user", "postgres"),
                    password=db_config.get("password", ""),
                )
        return conn
    except psycopg.Error as e:
        raise MigrationError(f"Failed to connect to database: {e}") from e


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
        spec = importlib.util.spec_from_file_location(migration_file.stem, migration_file)
        if spec is None or spec.loader is None:
            raise MigrationError(f"Cannot load migration: {migration_file}")

        # Load module
        module = importlib.util.module_from_spec(spec)
        sys.modules[migration_file.stem] = module
        spec.loader.exec_module(module)

        return module
    except Exception as e:
        raise MigrationError(f"Failed to load migration {migration_file}: {e}") from e


def get_migration_class(module: ModuleType) -> type:
    """Extract Migration subclass from loaded module.

    Args:
        module: Loaded Python module

    Returns:
        Migration class

    Raises:
        MigrationError: If no Migration class found
    """
    from confiture.models.migration import Migration

    # Find Migration subclass in module
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, Migration) and attr is not Migration:
            return attr

    raise MigrationError(f"No Migration subclass found in {module}")


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
        from confiture.models.sql_file_migration import FileSQLMigration

        # Find the matching .down.sql file
        base_name = migration_file.name.replace(".up.sql", "")
        down_file = migration_file.parent / f"{base_name}.down.sql"

        if not down_file.exists():
            raise MigrationError(
                f"SQL migration {migration_file.name} has no matching .down.sql file.\n"
                f"Expected: {down_file}\n"
                f"Hint: Create {down_file.name} with the rollback SQL"
            )

        return FileSQLMigration.from_files(migration_file, down_file)
    else:
        raise MigrationError(
            f"Unknown migration file type: {migration_file}\nExpected .py or .up.sql file"
        )
