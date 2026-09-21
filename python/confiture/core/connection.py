"""Database connection management for CLI commands."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.conninfo import make_conninfo

from confiture.config.environment import DatabaseConfig, SshTunnelConfig
from confiture.core import ssh_tunnel as _core_ssh_tunnel
from confiture.exceptions import ConfigurationError


def load_config(config_file: Path) -> dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_file: Path to configuration file

    Returns:
        Configuration dictionary

    Raises:
        ConfigurationError: If the config file is missing or invalid (exit 5).
    """
    if not config_file.exists():
        raise ConfigurationError(
            f"Configuration file not found: {config_file}",
            error_code="CONFIG_004",
            resolution_hint=f"Create a YAML config file at {config_file} or check the path is correct",
        )

    try:
        with Path(config_file).open() as f:
            config: dict[str, Any] = yaml.safe_load(f)
        return config
    except yaml.YAMLError as e:
        raise ConfigurationError(
            f"Invalid YAML configuration: {e}",
            error_code="CONFIG_002",
            resolution_hint="Check the YAML syntax in your config file for indentation or formatting errors",
        ) from e


def dsn_from_config(config: dict[str, Any] | str | Any) -> str:
    """The libpq connection string a configuration resolves to.

    One derivation for every consumer — :func:`create_connection` and
    :class:`~confiture.core.migrator.MigratorSession` — so a legacy
    ``database:`` block and a ``database_url`` key open the same connection
    whichever path a command takes.

    Args:
        config: A DSN string, a configuration dictionary with a ``database_url``
                key or a ``database`` section, a ``DatabaseConfig`` instance,
                or ``None`` (all defaults).
    """

    if isinstance(config, str):
        return config
    if isinstance(config, DatabaseConfig):
        block = config.to_dict().get("database", {})
    elif config is not None and not isinstance(config, dict):
        # An ``Environment`` (or anything else carrying a resolved URL).
        return str(config.database_url)
    else:
        data: dict[str, Any] = config or {}
        database_url = data.get("database_url")
        if database_url:
            return str(database_url)
        block = data.get("database") or {}
    return make_conninfo(
        host=block.get("host", "localhost"),
        port=block.get("port", 5432),
        dbname=block.get("database", "postgres"),
        user=block.get("user", "postgres"),
        password=block.get("password", ""),
    )


def create_connection(config: dict[str, Any] | Any) -> psycopg.Connection:
    """Create database connection from configuration.

    Args:
        config: Database URL string, configuration dictionary with 'database' section,
                'database_url' key, or DatabaseConfig instance

    Returns:
        psycopg.Connection instance

    Raises:
        ConfigurationError: If connection fails
    """
    try:
        return psycopg.connect(dsn_from_config(config))
    except psycopg.Error as e:
        raise ConfigurationError(
            f"Failed to connect to database: {e}",
            error_code="CONFIG_006",
            resolution_hint="Check that the database server is running and the connection credentials are correct",
        ) from e


ConnectionFactory = Callable[[Any], "psycopg.Connection[Any]"]
"""``config -> connection``; :func:`create_connection` is the default."""


@contextmanager
def open_connection(
    config: "dict[str, Any] | Any",
    *,
    factory: ConnectionFactory = create_connection,
) -> "Generator[psycopg.Connection[Any], None, None]":
    """Open a psycopg connection, transparently handling SSH tunnels.

    If *config* has an ``ssh_tunnel`` section (``Environment.ssh_tunnel`` or a
    dict key), the tunnel is opened first and the ``database_url`` placeholder
    ``${TUNNEL_LOCAL_PORT}`` is substituted with the real port.  The connection
    and any tunnel subprocess are always closed on exit.

    Args:
        config: ``Environment`` instance, raw config dict, or database URL string.
        factory: What opens the connection — injected by tests and embedders;
            bound at definition time, so replacing this module's
            ``create_connection`` afterwards changes nothing here.

    Yields:
        An open ``psycopg.Connection``.

    Example::

        from confiture.core.connection import open_connection

        env = Environment.load("production")
        with open_connection(env) as conn:
            conn.execute("SELECT version()")
    """

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
        database_url: str
        if hasattr(config, "database_url"):
            database_url = str(config.database_url)
        elif isinstance(config, dict):
            database_url = config.get("database_url", "")
        else:
            raise ConfigurationError(
                "Cannot determine database_url for SSH tunnel",
                error_code="CONFIG_001",
                resolution_hint="Ensure your config has a 'database_url' field",
            )

        with _core_ssh_tunnel.ssh_tunnel(tunnel_cfg, database_url) as patched_url:
            try:
                conn = factory(patched_url)
            except (psycopg.Error, ConfigurationError) as e:
                raise ConfigurationError(
                    f"Failed to connect through SSH tunnel: {e}",
                    error_code="CONFIG_006",
                    resolution_hint="Check that the SSH tunnel opened correctly and the database URL is valid",
                ) from e
            try:
                yield conn
            finally:
                conn.close()
    else:
        conn = factory(config)
        try:
            yield conn
        finally:
            conn.close()
