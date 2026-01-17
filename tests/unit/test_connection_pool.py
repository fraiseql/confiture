"""Unit tests for connection pooling (Phase 1D).

Tests for:
- PoolConfig validation
- ConnectionPool initialization
- Pool statistics
- Health checks
- Statement timeout
- PgBouncer mode
- Pool resizing
"""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.pool import (
    ConnectionPool,
    PoolConfig,
    PoolExhaustedError,
    PoolStats,
    create_pool_from_config,
)


class TestPoolConfig:
    """Test PoolConfig validation and defaults."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PoolConfig()
        assert config.min_size == 1
        assert config.max_size == 10
        assert config.timeout == 30.0
        assert config.max_idle == 600.0
        assert config.max_lifetime == 3600.0
        assert config.statement_timeout_ms == 0
        assert config.check_connection is True
        assert config.pgbouncer_mode is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = PoolConfig(
            min_size=5,
            max_size=50,
            timeout=60.0,
            statement_timeout_ms=30000,
            pgbouncer_mode=True,
        )
        assert config.min_size == 5
        assert config.max_size == 50
        assert config.timeout == 60.0
        assert config.statement_timeout_ms == 30000
        assert config.pgbouncer_mode is True

    def test_min_size_validation(self):
        """Test min_size must be >= 0."""
        with pytest.raises(ValueError, match="min_size must be >= 0"):
            PoolConfig(min_size=-1)

    def test_max_size_validation(self):
        """Test max_size must be >= 1."""
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            PoolConfig(max_size=0)

    def test_min_exceeds_max_validation(self):
        """Test min_size cannot exceed max_size."""
        with pytest.raises(ValueError, match="min_size cannot exceed max_size"):
            PoolConfig(min_size=20, max_size=10)

    def test_timeout_validation(self):
        """Test timeout must be > 0."""
        with pytest.raises(ValueError, match="timeout must be > 0"):
            PoolConfig(timeout=0)

        with pytest.raises(ValueError, match="timeout must be > 0"):
            PoolConfig(timeout=-1)

    def test_statement_timeout_validation(self):
        """Test statement_timeout_ms must be >= 0."""
        with pytest.raises(ValueError, match="statement_timeout_ms must be >= 0"):
            PoolConfig(statement_timeout_ms=-1)


class TestPoolStats:
    """Test PoolStats dataclass."""

    def test_connections_used_calculation(self):
        """Test connections_used is calculated correctly."""
        stats = PoolStats(pool_size=10, pool_available=3, requests_waiting=2)
        assert stats.connections_used == 7  # 10 - 3

    def test_all_available(self):
        """Test when all connections are available."""
        stats = PoolStats(pool_size=5, pool_available=5, requests_waiting=0)
        assert stats.connections_used == 0

    def test_none_available(self):
        """Test when no connections are available."""
        stats = PoolStats(pool_size=5, pool_available=0, requests_waiting=10)
        assert stats.connections_used == 5


class TestConnectionPoolInit:
    """Test ConnectionPool initialization."""

    def test_init_requires_connection_info(self):
        """Test that either database_url or connection_kwargs is required."""
        with pytest.raises(ValueError, match="Either database_url or connection_kwargs required"):
            ConnectionPool()

    @patch("confiture.core.pool.PsycopgPool")
    def test_init_with_database_url(self, mock_pool_class):
        """Test initialization with database URL."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        assert pool._conninfo == "postgresql://localhost/testdb"
        mock_pool_class.assert_called_once()

    @patch("confiture.core.pool.PsycopgPool")
    def test_init_with_connection_kwargs(self, mock_pool_class):
        """Test initialization with connection kwargs."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(
            host="localhost",
            port=5432,
            dbname="testdb",
            user="testuser",
            password="testpass",
        )

        assert "host=localhost" in pool._conninfo
        assert "dbname=testdb" in pool._conninfo

    @patch("confiture.core.pool.PsycopgPool")
    def test_init_with_custom_config(self, mock_pool_class):
        """Test initialization with custom pool config."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = PoolConfig(min_size=5, max_size=20)
        pool = ConnectionPool(database_url="postgresql://localhost/testdb", config=config)

        assert pool.config.min_size == 5
        assert pool.config.max_size == 20

        # Verify pool was created with correct settings
        call_kwargs = mock_pool_class.call_args
        assert call_kwargs.kwargs["min_size"] == 5
        assert call_kwargs.kwargs["max_size"] == 20

    @patch("confiture.core.pool.PsycopgPool")
    def test_init_pgbouncer_mode(self, mock_pool_class):
        """Test PgBouncer mode disables prepared statements."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = PoolConfig(pgbouncer_mode=True)
        ConnectionPool(database_url="postgresql://localhost/testdb", config=config)

        # Verify prepare_threshold=None was passed
        call_kwargs = mock_pool_class.call_args
        assert call_kwargs.kwargs["kwargs"]["prepare_threshold"] is None


class TestConnectionPoolConnection:
    """Test ConnectionPool.connection() method."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_connection_context_manager(self, mock_pool_class):
        """Test connection as context manager."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        with pool.connection() as conn:
            assert conn is mock_conn

    @patch("confiture.core.pool.PsycopgPool")
    def test_connection_with_statement_timeout(self, mock_pool_class):
        """Test statement timeout is applied to connections."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool_class.return_value = mock_pool

        config = PoolConfig(statement_timeout_ms=30000)
        pool = ConnectionPool(database_url="postgresql://localhost/testdb", config=config)

        with pool.connection():
            pass

        # Verify SET statement_timeout was called
        mock_cursor.execute.assert_called_with("SET statement_timeout = 30000")

    @patch("confiture.core.pool.PsycopgPool")
    def test_connection_with_custom_timeout(self, mock_pool_class):
        """Test connection with custom timeout override."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        with pool.connection(timeout=60.0):
            pass

        mock_pool.connection.assert_called_with(timeout=60.0)

    @patch("confiture.core.pool.PsycopgPool")
    def test_connection_pool_exhausted(self, mock_pool_class):
        """Test PoolExhaustedError when pool is exhausted."""
        from psycopg_pool import PoolTimeout

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = PoolTimeout("timeout")
        mock_pool.get_stats.return_value = MagicMock(
            pool_size=10, pool_available=0, requests_waiting=5
        )
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        with pytest.raises(PoolExhaustedError, match="Connection pool exhausted"):
            with pool.connection():
                pass

    def test_connection_pool_not_initialized(self):
        """Test error when pool is not initialized."""
        pool = ConnectionPool.__new__(ConnectionPool)
        pool._pool = None
        pool.config = PoolConfig()

        with pytest.raises(RuntimeError, match="Connection pool not initialized"):
            with pool.connection():
                pass


class TestConnectionPoolStats:
    """Test ConnectionPool.get_stats() method."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_get_stats(self, mock_pool_class):
        """Test getting pool statistics."""
        mock_pool = MagicMock()
        mock_stats = MagicMock()
        mock_stats.pool_size = 10
        mock_stats.pool_available = 7
        mock_stats.requests_waiting = 0
        mock_pool.get_stats.return_value = mock_stats
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")
        stats = pool.get_stats()

        assert stats.pool_size == 10
        assert stats.pool_available == 7
        assert stats.connections_used == 3
        assert stats.requests_waiting == 0

    def test_get_stats_uninitialized_pool(self):
        """Test get_stats returns zeros for uninitialized pool."""
        pool = ConnectionPool.__new__(ConnectionPool)
        pool._pool = None

        stats = pool.get_stats()

        assert stats.pool_size == 0
        assert stats.pool_available == 0
        assert stats.connections_used == 0


class TestConnectionPoolHealthCheck:
    """Test ConnectionPool.check_health() method."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_check_health_success(self, mock_pool_class):
        """Test successful health check."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        assert pool.check_health() is True
        mock_cursor.execute.assert_called_with("SELECT 1")

    @patch("confiture.core.pool.PsycopgPool")
    def test_check_health_failure(self, mock_pool_class):
        """Test failed health check."""
        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Connection failed")
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        assert pool.check_health() is False


class TestConnectionPoolResize:
    """Test ConnectionPool.resize() method."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_resize_pool(self, mock_pool_class):
        """Test resizing the pool."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")
        pool.resize(min_size=5, max_size=50)

        mock_pool.resize.assert_called_with(min_size=5, max_size=50)
        assert pool.config.min_size == 5
        assert pool.config.max_size == 50

    @patch("confiture.core.pool.PsycopgPool")
    def test_resize_partial(self, mock_pool_class):
        """Test resizing only one dimension."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")
        pool.resize(max_size=20)

        mock_pool.resize.assert_called_with(min_size=1, max_size=20)

    @patch("confiture.core.pool.PsycopgPool")
    def test_resize_invalid(self, mock_pool_class):
        """Test resize with invalid values."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")

        with pytest.raises(ValueError, match="min_size cannot exceed max_size"):
            pool.resize(min_size=20, max_size=5)


class TestConnectionPoolClose:
    """Test ConnectionPool.close() method."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_close_pool(self, mock_pool_class):
        """Test closing the pool."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")
        pool.close()

        mock_pool.close.assert_called_once()
        assert pool._pool is None

    @patch("confiture.core.pool.PsycopgPool")
    def test_close_already_closed(self, mock_pool_class):
        """Test closing already closed pool doesn't raise."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(database_url="postgresql://localhost/testdb")
        pool.close()
        pool.close()  # Should not raise

    @patch("confiture.core.pool.PsycopgPool")
    def test_context_manager(self, mock_pool_class):
        """Test using pool as context manager."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        with ConnectionPool(database_url="postgresql://localhost/testdb") as pool:
            assert pool._pool is not None

        mock_pool.close.assert_called_once()


class TestCreatePoolFromConfig:
    """Test create_pool_from_config helper function."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_create_from_database_url(self, mock_pool_class):
        """Test creating pool from database_url config."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = {
            "database_url": "postgresql://localhost/testdb",
            "pool": {"min_size": 2, "max_size": 20},
        }
        pool = create_pool_from_config(config)

        assert pool.config.min_size == 2
        assert pool.config.max_size == 20
        assert pool._conninfo == "postgresql://localhost/testdb"

    @patch("confiture.core.pool.PsycopgPool")
    def test_create_from_database_section(self, mock_pool_class):
        """Test creating pool from database section config."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = {
            "database": {
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "user": "testuser",
                "password": "testpass",
            },
            "pool": {"min_size": 5},
        }
        pool = create_pool_from_config(config)

        assert pool.config.min_size == 5
        assert "host=localhost" in pool._conninfo

    @patch("confiture.core.pool.PsycopgPool")
    def test_create_with_pgbouncer_mode(self, mock_pool_class):
        """Test creating pool with PgBouncer mode."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = {
            "database_url": "postgresql://localhost/testdb",
            "pool": {"pgbouncer_mode": True},
        }
        pool = create_pool_from_config(config)

        assert pool.config.pgbouncer_mode is True

    @patch("confiture.core.pool.PsycopgPool")
    def test_create_with_defaults(self, mock_pool_class):
        """Test creating pool with default pool config."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        config = {"database_url": "postgresql://localhost/testdb"}
        pool = create_pool_from_config(config)

        assert pool.config.min_size == 1
        assert pool.config.max_size == 10


class TestBuildConninfo:
    """Test connection string building."""

    @patch("confiture.core.pool.PsycopgPool")
    def test_build_conninfo_all_params(self, mock_pool_class):
        """Test building conninfo with all parameters."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(
            host="db.example.com",
            port=5433,
            dbname="mydb",
            user="admin",
            password="secret",
        )

        assert "host=db.example.com" in pool._conninfo
        assert "port=5433" in pool._conninfo
        assert "dbname=mydb" in pool._conninfo
        assert "user=admin" in pool._conninfo
        assert "password=secret" in pool._conninfo

    @patch("confiture.core.pool.PsycopgPool")
    def test_build_conninfo_database_alias(self, mock_pool_class):
        """Test 'database' is aliased to 'dbname'."""
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        pool = ConnectionPool(
            host="localhost",
            database="mydb",  # Using 'database' instead of 'dbname'
        )

        assert "dbname=mydb" in pool._conninfo
