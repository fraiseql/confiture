"""Database connection management for CLI commands."""

import importlib.util
import sys
from collections.abc import Generator
from contextlib import contextmanager
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
        raise MigrationError(
            f"Configuration file not found: {config_file}",
            resolution_hint=f"Create a YAML config file at {config_file} or check the path is correct",
        )

    try:
        with open(config_file) as f:
            config: dict[str, Any] = yaml.safe_load(f)
        return config
    except yaml.YAMLError as e:
        raise MigrationError(
            f"Invalid YAML configuration: {e}",
            resolution_hint="Check the YAML syntax in your config file for indentation or formatting errors",
        ) from e


def create_connection(config: dict[str, Any] | Any) -> psycopg.Connection:
    """Create database connection from configuration.

    Args:
        config: Database URL string, configuration dictionary with 'database' section,
                'database_url' key, or DatabaseConfig instance

    Returns:
        PostgreSQL connection

    Raises:
        MigrationError: If connection fails
    """
    from confiture.config.environment import DatabaseConfig

    try:
        # Handle string database URL
        if isinstance(config, str):
            return psycopg.connect(config)

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
        raise MigrationError(
            f"Failed to connect to database: {e}",
            resolution_hint="Check that the database server is running and the connection credentials are correct",
        ) from e


@contextmanager
def open_connection(
    config: "dict[str, Any] | Any",
) -> "Generator[psycopg.Connection[Any], None, None]":
    """Open a psycopg connection, transparently handling SSH tunnels.

    If *config* has an ``ssh_tunnel`` section (``Environment.ssh_tunnel`` or a
    dict key), the tunnel is opened first and the ``database_url`` placeholder
    ``${TUNNEL_LOCAL_PORT}`` is substituted with the real port.  The connection
    and any tunnel subprocess are always closed on exit.

    Args:
        config: ``Environment`` instance, raw config dict, or database URL string.

    Yields:
        An open ``psycopg.Connection``.

    Example::

        from confiture.core.connection import open_connection

        env = Environment.load("production")
        with open_connection(env) as conn:
            conn.execute("SELECT version()")
    """
    from confiture.config.environment import SshTunnelConfig  # noqa: PLC0415

    # Resolve ssh_tunnel config (supports Environment objects and raw dicts).
    # Explicitly check isinstance(SshTunnelConfig) to avoid treating MagicMock
    # attributes (present in tests) as tunnel configuration.
    tunnel_cfg: SshTunnelConfig | None = None
    if hasattr(config, "ssh_tunnel"):
        _ssh = config.ssh_tunnel
        if isinstance(_ssh, SshTunnelConfig):
            tunnel_cfg = _ssh
    elif isinstance(config, dict) and config.get("ssh_tunnel"):
        raw = config["ssh_tunnel"]
        tunnel_cfg = SshTunnelConfig(**raw) if isinstance(raw, dict) else raw

    if tunnel_cfg is not None:
        from confiture.core.ssh_tunnel import ssh_tunnel  # noqa: PLC0415

        database_url: str
        if hasattr(config, "database_url"):
            database_url = config.database_url
        elif isinstance(config, dict):
            database_url = config.get("database_url", "")
        else:
            raise MigrationError(
                "Cannot determine database_url for SSH tunnel",
                resolution_hint="Ensure your config has a 'database_url' field",
            )

        with ssh_tunnel(tunnel_cfg, database_url) as patched_url:
            try:
                conn = psycopg.connect(patched_url)
            except psycopg.Error as e:
                raise MigrationError(
                    f"Failed to connect through SSH tunnel: {e}",
                    resolution_hint="Check that the SSH tunnel opened correctly and the database URL is valid",
                ) from e
            try:
                yield conn
            finally:
                conn.close()
    else:
        conn = create_connection(config)
        try:
            yield conn
        finally:
            conn.close()


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
            raise MigrationError(
                f"Cannot load migration: {migration_file}",
                resolution_hint="Ensure the migration file exists and contains valid Python code",
            )

        # Load module
        module = importlib.util.module_from_spec(spec)
        sys.modules[migration_file.stem] = module
        spec.loader.exec_module(module)

        return module
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
    from confiture.models.migration import Migration

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
        from confiture.models.sql_file_migration import FileSQLMigration

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
