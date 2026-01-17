"""Connection pooling support for production workloads.

Provides connection pool management with:
- Configurable pool size (min/max connections)
- Connection health checks
- Statement timeout configuration
- Automatic reconnection
- PgBouncer awareness (transaction pooling mode)

Example:
    >>> from confiture.core.pool import ConnectionPool, PoolConfig
    >>> config = PoolConfig(min_size=2, max_size=10)
    >>> pool = ConnectionPool(database_url="postgresql://localhost/mydb", config=config)
    >>> with pool.connection() as conn:
    ...     with conn.cursor() as cur:
    ...         cur.execute("SELECT 1")
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg_pool import ConnectionPool as PsycopgPool
from psycopg_pool import PoolTimeout

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for connection pooling.

    Attributes:
        min_size: Minimum number of connections to maintain (default: 1)
        max_size: Maximum number of connections allowed (default: 10)
        timeout: Timeout in seconds to get a connection (default: 30.0)
        max_idle: Maximum time a connection can be idle before being closed (default: 600.0)
        max_lifetime: Maximum time a connection can exist before being recycled (default: 3600.0)
        statement_timeout_ms: Default statement timeout in milliseconds (default: 0 = no timeout)
        check_connection: Whether to check connection health before returning (default: True)
        reconnect_timeout: Timeout for reconnection attempts (default: 300.0)
        pgbouncer_mode: Enable PgBouncer compatibility mode (default: False)
            When True, disables prepared statements and uses transaction pooling compatible settings

    Example:
        >>> config = PoolConfig(min_size=2, max_size=20, statement_timeout_ms=30000)
        >>> config = PoolConfig(pgbouncer_mode=True)  # For PgBouncer setups
    """

    min_size: int = 1
    max_size: int = 10
    timeout: float = 30.0
    max_idle: float = 600.0
    max_lifetime: float = 3600.0
    statement_timeout_ms: int = 0  # 0 = no timeout
    check_connection: bool = True
    reconnect_timeout: float = 300.0
    pgbouncer_mode: bool = False

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.min_size < 0:
            raise ValueError("min_size must be >= 0")
        if self.max_size < 1:
            raise ValueError("max_size must be >= 1")
        if self.min_size > self.max_size:
            raise ValueError("min_size cannot exceed max_size")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")
        if self.statement_timeout_ms < 0:
            raise ValueError("statement_timeout_ms must be >= 0")


@dataclass
class PoolStats:
    """Statistics about the connection pool.

    Attributes:
        pool_size: Current number of connections in the pool
        pool_available: Number of available (idle) connections
        requests_waiting: Number of requests waiting for a connection
        connections_used: Number of connections currently in use
    """

    pool_size: int
    pool_available: int
    requests_waiting: int
    connections_used: int = field(init=False)

    def __post_init__(self) -> None:
        """Calculate derived statistics."""
        self.connections_used = self.pool_size - self.pool_available


class PoolExhaustedError(Exception):
    """Raised when connection pool is exhausted and timeout expires."""

    pass


class ConnectionHealthError(Exception):
    """Raised when connection health check fails."""

    pass


class ConnectionPool:
    """Managed connection pool for PostgreSQL.

    Wraps psycopg_pool.ConnectionPool with additional features:
    - Health checking
    - Statement timeout configuration
    - PgBouncer compatibility
    - Graceful reconnection

    Example:
        >>> pool = ConnectionPool("postgresql://localhost/mydb")
        >>> with pool.connection() as conn:
        ...     # Connection is automatically returned to pool after use
        ...     pass
        >>> pool.close()

    Example with configuration:
        >>> config = PoolConfig(min_size=5, max_size=20)
        >>> pool = ConnectionPool("postgresql://localhost/mydb", config=config)
        >>> stats = pool.get_stats()
        >>> print(f"Using {stats.connections_used} of {stats.pool_size} connections")
    """

    def __init__(
        self,
        database_url: str | None = None,
        config: PoolConfig | None = None,
        **connection_kwargs: Any,
    ):
        """Initialize connection pool.

        Args:
            database_url: PostgreSQL connection URL
            config: Pool configuration (uses defaults if None)
            **connection_kwargs: Additional arguments passed to psycopg.connect()
                (host, port, dbname, user, password, etc.)

        Raises:
            ValueError: If neither database_url nor connection_kwargs provided
        """
        self.config = config or PoolConfig()
        self._database_url = database_url
        self._connection_kwargs = connection_kwargs
        self._pool: PsycopgPool | None = None

        # Build connection string
        if database_url:
            self._conninfo = database_url
        elif connection_kwargs:
            self._conninfo = self._build_conninfo(connection_kwargs)
        else:
            raise ValueError("Either database_url or connection_kwargs required")

        self._initialize_pool()

    def _build_conninfo(self, kwargs: dict[str, Any]) -> str:
        """Build connection string from kwargs."""
        parts = []
        mapping = {
            "host": "host",
            "port": "port",
            "dbname": "dbname",
            "database": "dbname",  # alias
            "user": "user",
            "password": "password",
        }
        for key, conninfo_key in mapping.items():
            if key in kwargs:
                value = kwargs[key]
                # Escape single quotes in values
                if isinstance(value, str) and "'" in value:
                    value = value.replace("'", "\\'")
                parts.append(f"{conninfo_key}={value}")

        return " ".join(parts)

    def _initialize_pool(self) -> None:
        """Initialize the underlying psycopg pool."""
        # Configure connection options
        kwargs: dict[str, Any] = {}

        # For PgBouncer mode, disable prepared statements
        if self.config.pgbouncer_mode:
            kwargs["prepare_threshold"] = None
            logger.info("PgBouncer mode enabled: prepared statements disabled")

        self._pool = PsycopgPool(
            conninfo=self._conninfo,
            min_size=self.config.min_size,
            max_size=self.config.max_size,
            timeout=self.config.timeout,
            max_idle=self.config.max_idle,
            max_lifetime=self.config.max_lifetime,
            check=PsycopgPool.check_connection if self.config.check_connection else None,
            kwargs=kwargs if kwargs else None,
            open=True,
        )

        logger.info(
            f"Connection pool initialized: min={self.config.min_size}, "
            f"max={self.config.max_size}"
        )

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[psycopg.Connection]:
        """Get a connection from the pool.

        The connection is automatically returned to the pool when the context
        manager exits. If an exception occurs, the connection is still returned
        but may be discarded if it's in a bad state.

        Args:
            timeout: Override default timeout (seconds) for getting a connection

        Yields:
            PostgreSQL connection

        Raises:
            PoolExhaustedError: If no connection available within timeout
            ConnectionHealthError: If connection fails health check

        Example:
            >>> with pool.connection() as conn:
            ...     with conn.cursor() as cur:
            ...         cur.execute("SELECT 1")
            ...         result = cur.fetchone()
        """
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")

        effective_timeout = timeout if timeout is not None else self.config.timeout

        try:
            with self._pool.connection(timeout=effective_timeout) as conn:
                # Apply statement timeout if configured
                if self.config.statement_timeout_ms > 0:
                    self._set_statement_timeout(conn, self.config.statement_timeout_ms)

                yield conn

        except PoolTimeout as e:
            stats = self.get_stats()
            raise PoolExhaustedError(
                f"Connection pool exhausted after {effective_timeout}s. "
                f"Pool stats: {stats.connections_used}/{stats.pool_size} in use, "
                f"{stats.requests_waiting} waiting"
            ) from e

    def _set_statement_timeout(self, conn: psycopg.Connection, timeout_ms: int) -> None:
        """Set statement timeout on connection.

        Args:
            conn: Database connection
            timeout_ms: Timeout in milliseconds
        """
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {timeout_ms}")
        except psycopg.Error as e:
            logger.warning(f"Failed to set statement timeout: {e}")

    def get_stats(self) -> PoolStats:
        """Get current pool statistics.

        Returns:
            PoolStats with current pool state

        Example:
            >>> stats = pool.get_stats()
            >>> if stats.connections_used > stats.pool_size * 0.8:
            ...     print("Pool is running hot!")
        """
        if self._pool is None:
            return PoolStats(pool_size=0, pool_available=0, requests_waiting=0)

        return PoolStats(
            pool_size=self._pool.get_stats().pool_size,
            pool_available=self._pool.get_stats().pool_available,
            requests_waiting=self._pool.get_stats().requests_waiting,
        )

    def check_health(self) -> bool:
        """Check if pool is healthy by testing a connection.

        Returns:
            True if pool is healthy, False otherwise

        Example:
            >>> if not pool.check_health():
            ...     logger.error("Database connection pool unhealthy!")
        """
        try:
            with self.connection(timeout=5.0) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                return result is not None and result[0] == 1
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def resize(self, min_size: int | None = None, max_size: int | None = None) -> None:
        """Resize the connection pool.

        Args:
            min_size: New minimum size (or None to keep current)
            max_size: New maximum size (or None to keep current)

        Example:
            >>> pool.resize(min_size=5, max_size=50)  # Scale up
        """
        if self._pool is None:
            return

        new_min = min_size if min_size is not None else self.config.min_size
        new_max = max_size if max_size is not None else self.config.max_size

        if new_min > new_max:
            raise ValueError("min_size cannot exceed max_size")

        self._pool.resize(min_size=new_min, max_size=new_max)
        self.config.min_size = new_min
        self.config.max_size = new_max

        logger.info(f"Pool resized: min={new_min}, max={new_max}")

    def close(self) -> None:
        """Close the connection pool.

        Waits for all connections to be returned, then closes them.
        Call this during application shutdown.

        Example:
            >>> try:
            ...     # Use pool
            ... finally:
            ...     pool.close()
        """
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            logger.info("Connection pool closed")

    def __enter__(self) -> "ConnectionPool":
        """Support using pool as context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Close pool when exiting context."""
        self.close()


def create_pool_from_config(config: dict[str, Any]) -> ConnectionPool:
    """Create a connection pool from configuration dictionary.

    Args:
        config: Configuration with 'database' and optional 'pool' sections

    Returns:
        Configured ConnectionPool

    Example:
        >>> config = {
        ...     "database_url": "postgresql://localhost/mydb",
        ...     "pool": {"min_size": 2, "max_size": 20}
        ... }
        >>> pool = create_pool_from_config(config)
    """
    # Get pool configuration
    pool_config_dict = config.get("pool", {})
    pool_config = PoolConfig(
        min_size=pool_config_dict.get("min_size", 1),
        max_size=pool_config_dict.get("max_size", 10),
        timeout=pool_config_dict.get("timeout", 30.0),
        max_idle=pool_config_dict.get("max_idle", 600.0),
        max_lifetime=pool_config_dict.get("max_lifetime", 3600.0),
        statement_timeout_ms=pool_config_dict.get("statement_timeout_ms", 0),
        check_connection=pool_config_dict.get("check_connection", True),
        pgbouncer_mode=pool_config_dict.get("pgbouncer_mode", False),
    )

    # Get database connection info
    database_url = config.get("database_url")
    if database_url:
        return ConnectionPool(database_url=database_url, config=pool_config)

    # Fall back to database section
    db_config = config.get("database", {})
    return ConnectionPool(
        config=pool_config,
        host=db_config.get("host", "localhost"),
        port=db_config.get("port", 5432),
        dbname=db_config.get("database", "postgres"),
        user=db_config.get("user", "postgres"),
        password=db_config.get("password", ""),
    )
