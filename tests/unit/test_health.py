"""Tests for health check endpoints."""

import json
import socket
import time
from http.client import HTTPConnection
from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.health import (
    HealthServer,
    HealthStatus,
    check_database_health,
)


class TestHealthStatus:
    """Tests for HealthStatus dataclass."""

    def test_default_status(self):
        """Test default health status."""
        status = HealthStatus()
        assert status.ready is False
        assert status.live is True
        assert status.migration_status == "pending"
        assert status.current_migration is None
        assert status.error is None

    def test_status_to_dict(self):
        """Test converting status to dictionary."""
        status = HealthStatus(
            ready=True,
            live=True,
            migration_status="completed",
            applied_count=5,
        )
        result = status.to_dict()
        assert result["ready"] is True
        assert result["migration_status"] == "completed"
        assert result["applied_count"] == 5


class TestHealthServer:
    """Tests for HealthServer."""

    def find_free_port(self) -> int:
        """Find a free port for testing."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    def test_server_start_stop(self):
        """Test starting and stopping server."""
        port = self.find_free_port()
        server = HealthServer(port=port)

        assert not server.is_running
        server.start()
        assert server.is_running

        # Give server time to start
        time.sleep(0.1)

        server.stop()
        assert not server.is_running

    def test_server_start_twice(self):
        """Test starting server twice does nothing."""
        port = self.find_free_port()
        server = HealthServer(port=port)

        server.start()
        time.sleep(0.1)
        server.start()  # Should warn but not fail

        server.stop()

    def test_set_pending(self):
        """Test setting pending status."""
        server = HealthServer()
        server.set_pending(pending_count=5)

        assert server.status.ready is False
        assert server.status.live is True
        assert server.status.migration_status == "pending"
        assert server.status.pending_count == 5

    def test_set_running(self):
        """Test setting running status."""
        server = HealthServer()
        server.set_running("001_create_users", remaining=3)

        assert server.status.ready is False
        assert server.status.live is True
        assert server.status.migration_status == "running"
        assert server.status.current_migration == "001_create_users"
        assert server.status.pending_count == 3

    def test_set_completed(self):
        """Test setting completed status."""
        server = HealthServer()
        server.set_completed(applied_count=5)

        assert server.status.ready is True
        assert server.status.live is True
        assert server.status.migration_status == "completed"
        assert server.status.applied_count == 5

    def test_set_failed(self):
        """Test setting failed status."""
        server = HealthServer()
        server.set_failed("Migration error", migration="001_create_users")

        assert server.status.ready is False
        assert server.status.live is False  # Should trigger restart
        assert server.status.migration_status == "failed"
        assert server.status.error == "Migration error"

    def test_set_error_recoverable(self):
        """Test setting recoverable error status."""
        server = HealthServer()
        server.set_error_recoverable("Temporary error")

        assert server.status.ready is False
        assert server.status.live is True  # Should NOT trigger restart
        assert server.status.migration_status == "error"


class TestHealthEndpoints:
    """Tests for health endpoints via HTTP."""

    @pytest.fixture
    def running_server(self):
        """Create and start a health server."""
        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]

        server = HealthServer(port=port)
        server.start()
        time.sleep(0.1)  # Give server time to start

        yield server, port

        server.stop()

    def test_ready_endpoint_pending(self, running_server):
        """Test /ready returns 503 when pending."""
        server, port = running_server
        server.set_pending()

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/ready")
        response = conn.getresponse()

        assert response.status == 503
        data = json.loads(response.read())
        assert data["ready"] is False
        conn.close()

    def test_ready_endpoint_completed(self, running_server):
        """Test /ready returns 200 when completed."""
        server, port = running_server
        server.set_completed()

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/ready")
        response = conn.getresponse()

        assert response.status == 200
        data = json.loads(response.read())
        assert data["ready"] is True
        conn.close()

    def test_readyz_alias(self, running_server):
        """Test /readyz is alias for /ready."""
        server, port = running_server
        server.set_completed()

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/readyz")
        response = conn.getresponse()

        assert response.status == 200
        conn.close()

    def test_live_endpoint_alive(self, running_server):
        """Test /live returns 200 when alive."""
        server, port = running_server

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/live")
        response = conn.getresponse()

        assert response.status == 200
        data = json.loads(response.read())
        assert data["live"] is True
        conn.close()

    def test_live_endpoint_failed(self, running_server):
        """Test /live returns 503 when failed."""
        server, port = running_server
        server.set_failed("Fatal error")

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/live")
        response = conn.getresponse()

        assert response.status == 503
        data = json.loads(response.read())
        assert data["live"] is False
        conn.close()

    def test_livez_alias(self, running_server):
        """Test /livez is alias for /live."""
        server, port = running_server

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/livez")
        response = conn.getresponse()

        assert response.status == 200
        conn.close()

    def test_health_endpoint(self, running_server):
        """Test /health returns full status."""
        server, port = running_server
        server.set_running("001_create_users", remaining=2)

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()

        # Running means not ready, so 503
        assert response.status == 503
        data = json.loads(response.read())
        assert data["migration_status"] == "running"
        assert data["current_migration"] == "001_create_users"
        conn.close()

    def test_healthz_alias(self, running_server):
        """Test /healthz is alias for /health."""
        server, port = running_server
        server.set_completed()

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/healthz")
        response = conn.getresponse()

        assert response.status == 200
        conn.close()

    def test_unknown_endpoint(self, running_server):
        """Test unknown endpoint returns 404."""
        server, port = running_server

        conn = HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/unknown")
        response = conn.getresponse()

        assert response.status == 404
        conn.close()


class TestCheckDatabaseHealth:
    """Tests for check_database_health function."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_healthy_database(self, mock_connection):
        """Test checking healthy database."""
        conn, cursor = mock_connection
        # Note: SELECT 1 doesn't call fetchone in our impl,
        # only current_database() and EXISTS query do
        cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # migration table exists
        ]

        result = check_database_health(conn)

        assert result["database_connected"] is True
        assert result["database_name"] == "test_db"
        assert result["migration_table_exists"] is True
        assert result["error"] is None

    def test_database_connection_error(self, mock_connection):
        """Test database connection error."""
        conn, cursor = mock_connection
        cursor.execute.side_effect = Exception("Connection refused")

        result = check_database_health(conn)

        assert result["database_connected"] is False
        assert result["error"] == "Connection refused"

    def test_migration_table_missing(self, mock_connection):
        """Test when migration table doesn't exist."""
        conn, cursor = mock_connection
        # Note: SELECT 1 doesn't call fetchone in our impl
        cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (False,),  # migration table does NOT exist
        ]

        result = check_database_health(conn)

        assert result["database_connected"] is True
        assert result["migration_table_exists"] is False


class TestHealthIntegration:
    """Integration tests for health checks with real database."""

    @pytest.fixture
    def db_connection(self):
        """Create test database connection if available."""
        try:
            import psycopg

            conn = psycopg.connect("postgresql://localhost/confiture_test")
            yield conn
            conn.close()
        except Exception:
            pytest.skip("Test database not available")

    def test_real_database_health(self, db_connection):
        """Test health check with real database."""
        result = check_database_health(db_connection)

        assert result["database_connected"] is True
        assert result["database_name"] == "confiture_test"
        assert result["error"] is None
