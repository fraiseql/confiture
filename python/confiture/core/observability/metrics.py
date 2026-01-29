"""Prometheus metrics for migrations.

Provides optional metrics integration for migration monitoring.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricsConfig:
    """Configuration for Prometheus metrics."""

    enabled: bool = False
    port: int = 9090
    path: str = "/metrics"


class MigrationMetrics:
    """Prometheus metrics for migrations.

    Exposes metrics when prometheus_client is installed:
    - tb_confiture_total (counter)
    - confiture_migration_duration_seconds (histogram)
    - confiture_migration_errors_total (counter)
    - confiture_migration_last_success_timestamp (gauge)

    Example:
        >>> metrics = MigrationMetrics(MetricsConfig(enabled=True))
        >>> metrics.start_server()
        >>> metrics.record_migration("001", "create_users", 2.5, success=True)
    """

    def __init__(self, config: MetricsConfig):
        """Initialize migration metrics.

        Args:
            config: Metrics configuration
        """
        self.config = config
        self._registry: Any = None
        self._migrations_total: Any = None
        self._migration_duration: Any = None
        self._migration_errors: Any = None
        self._last_success: Any = None
        self._initialized = False

        if config.enabled:
            self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        try:
            from prometheus_client import REGISTRY, Counter, Gauge, Histogram  # type: ignore[import]

            self._registry = REGISTRY

            # Define metrics
            self._migrations_total = Counter(
                "tb_confiture_total",
                "Total number of migrations executed",
                ["version", "name", "status"],
                registry=self._registry,
            )

            self._migration_duration = Histogram(
                "confiture_migration_duration_seconds",
                "Migration execution duration",
                ["version"],
                buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
                registry=self._registry,
            )

            self._migration_errors = Counter(
                "confiture_migration_errors_total",
                "Total number of migration errors",
                ["version", "error_type"],
                registry=self._registry,
            )

            self._last_success = Gauge(
                "confiture_migration_last_success_timestamp",
                "Timestamp of last successful migration",
                registry=self._registry,
            )

            self._initialized = True
            logger.info("Prometheus metrics initialized")

        except ImportError:
            logger.warning(
                "prometheus_client not installed. Install with: "
                "pip install confiture[observability]"
            )
            self.config.enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if metrics are enabled and initialized."""
        return self.config.enabled and self._initialized

    def start_server(self) -> None:
        """Start Prometheus metrics HTTP server."""
        if not self.is_enabled:
            return

        try:
            from prometheus_client import start_http_server  # type: ignore[import]

            start_http_server(self.config.port)
            logger.info(f"Prometheus metrics server started on port {self.config.port}")

        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")

    def record_migration(
        self,
        version: str,
        name: str,
        duration_seconds: float,
        success: bool,
        error: Exception | None = None,
    ) -> None:
        """Record migration execution metrics.

        Args:
            version: Migration version
            name: Migration name
            duration_seconds: Execution duration in seconds
            success: Whether migration succeeded
            error: Exception if failed (optional)
        """
        if not self.is_enabled:
            return

        import time

        status = "success" if success else "error"
        self._migrations_total.labels(version=version, name=name, status=status).inc()
        self._migration_duration.labels(version=version).observe(duration_seconds)

        if success:
            self._last_success.set(time.time())
        elif error:
            error_type = type(error).__name__
            self._migration_errors.labels(version=version, error_type=error_type).inc()

    def record_error(self, version: str, error: Exception) -> None:
        """Record a migration error.

        Args:
            version: Migration version
            error: Exception that occurred
        """
        if not self.is_enabled:
            return

        error_type = type(error).__name__
        self._migration_errors.labels(version=version, error_type=error_type).inc()


def create_metrics(config: MetricsConfig | None = None) -> MigrationMetrics:
    """Factory function to create metrics.

    Args:
        config: Metrics configuration (optional)

    Returns:
        Configured MigrationMetrics
    """
    return MigrationMetrics(config or MetricsConfig())
