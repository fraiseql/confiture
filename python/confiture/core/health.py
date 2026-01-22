"""Health check endpoints for Kubernetes probes.

Provides health endpoints for readiness and liveness probes
in Kubernetes/container environments.
"""

import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health check status."""

    ready: bool = False
    live: bool = True
    migration_status: str = "pending"  # pending, running, completed, failed
    current_migration: str | None = None
    pending_count: int = 0
    applied_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ready": self.ready,
            "live": self.live,
            "migration_status": self.migration_status,
            "current_migration": self.current_migration,
            "pending_count": self.pending_count,
            "applied_count": self.applied_count,
            "error": self.error,
        }


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health endpoints.

    Handles:
    - GET /ready - Readiness probe (is migration complete?)
    - GET /live - Liveness probe (is process alive?)
    - GET /health - Full health status
    """

    health_status: HealthStatus = HealthStatus()

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/ready" or self.path == "/readyz":
            self._handle_ready()
        elif self.path == "/live" or self.path == "/livez":
            self._handle_live()
        elif self.path == "/health" or self.path == "/healthz":
            self._handle_health()
        else:
            self.send_error(404, "Not Found")

    def _handle_ready(self) -> None:
        """Handle readiness probe.

        Returns 200 when migrations are complete, 503 otherwise.
        """
        if self.health_status.ready:
            self._send_json(200, {"ready": True})
        else:
            self._send_json(
                503,
                {
                    "ready": False,
                    "status": self.health_status.migration_status,
                    "current_migration": self.health_status.current_migration,
                    "pending_count": self.health_status.pending_count,
                },
            )

    def _handle_live(self) -> None:
        """Handle liveness probe.

        Returns 200 when process is alive, 503 on fatal error.
        """
        if self.health_status.live:
            self._send_json(200, {"live": True})
        else:
            self._send_json(
                503,
                {
                    "live": False,
                    "error": self.health_status.error,
                },
            )

    def _handle_health(self) -> None:
        """Handle full health status.

        Returns complete health information.
        """
        status_code = 200 if self.health_status.ready else 503
        self._send_json(status_code, self.health_status.to_dict())

    def _send_json(self, status: int, data: dict) -> None:
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default request logging."""
        # Only log errors
        if args and "error" in str(args[0]).lower():
            logger.warning(format % args)


class HealthServer:
    """Health check HTTP server for Kubernetes probes.

    Runs a lightweight HTTP server in a background thread to serve
    health check endpoints for Kubernetes readiness and liveness probes.

    Example:
        >>> server = HealthServer(port=8080)
        >>> server.start()
        >>> server.set_running("001_create_users")
        >>> # ... run migration ...
        >>> server.set_completed()
        >>> # Server responds to /ready with 200 OK
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        """Initialize health server.

        Args:
            host: Host to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 8080)
        """
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._status = HealthStatus()
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def status(self) -> HealthStatus:
        """Get current health status."""
        return self._status

    def start(self) -> None:
        """Start health server in background thread."""
        if self._running:
            logger.warning("Health server already running")
            return

        # Set handler's status reference
        HealthHandler.health_status = self._status

        try:
            self._server = HTTPServer((self.host, self.port), HealthHandler)

            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="confiture-health-server",
            )
            self._thread.daemon = True
            self._thread.start()

            self._running = True
            logger.info(f"Health server started on {self.host}:{self.port}")

        except OSError as e:
            logger.error(f"Failed to start health server: {e}")
            raise

    def stop(self) -> None:
        """Stop health server."""
        if not self._running:
            return

        if self._server:
            self._server.shutdown()
            self._server = None

        self._running = False
        logger.info("Health server stopped")

    def set_pending(self, pending_count: int = 0) -> None:
        """Set status to pending (waiting to start).

        Args:
            pending_count: Number of pending migrations
        """
        self._status.ready = False
        self._status.live = True
        self._status.migration_status = "pending"
        self._status.current_migration = None
        self._status.pending_count = pending_count
        self._status.error = None

    def set_running(self, migration: str, remaining: int = 0) -> None:
        """Set status to running a migration.

        Args:
            migration: Name/version of current migration
            remaining: Number of remaining migrations after current
        """
        self._status.ready = False
        self._status.live = True
        self._status.migration_status = "running"
        self._status.current_migration = migration
        self._status.pending_count = remaining
        self._status.error = None

    def set_completed(self, applied_count: int = 0) -> None:
        """Set status to completed (all migrations done).

        Args:
            applied_count: Number of migrations applied
        """
        self._status.ready = True
        self._status.live = True
        self._status.migration_status = "completed"
        self._status.current_migration = None
        self._status.pending_count = 0
        self._status.applied_count = applied_count
        self._status.error = None

    def set_failed(self, error: str, migration: str | None = None) -> None:
        """Set status to failed (migration error).

        This will cause both readiness and liveness to fail,
        which may trigger a pod restart in Kubernetes.

        Args:
            error: Error message
            migration: Name of failed migration (optional)
        """
        self._status.ready = False
        self._status.live = False  # Trigger restart
        self._status.migration_status = "failed"
        self._status.current_migration = migration
        self._status.error = error

    def set_error_recoverable(self, error: str, migration: str | None = None) -> None:
        """Set status to error but still alive (recoverable error).

        Unlike set_failed(), this keeps liveness True so the pod
        won't be restarted.

        Args:
            error: Error message
            migration: Name of problematic migration (optional)
        """
        self._status.ready = False
        self._status.live = True  # Don't restart
        self._status.migration_status = "error"
        self._status.current_migration = migration
        self._status.error = error


def check_database_health(connection: Any) -> dict[str, Any]:
    """Check database connectivity and return health info.

    Args:
        connection: Database connection to test

    Returns:
        Dictionary with health status
    """
    result = {
        "database_connected": False,
        "migration_table_exists": False,
        "database_name": None,
        "error": None,
    }

    try:
        with connection.cursor() as cur:
            # Check connection
            cur.execute("SELECT 1")
            result["database_connected"] = True

            # Get database name
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            result["database_name"] = row[0] if row else None

            # Check migration table
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'tb_confiture'
                )
            """)
            row = cur.fetchone()
            result["migration_table_exists"] = row[0] if row else False

    except Exception as e:
        result["error"] = str(e)

    return result
