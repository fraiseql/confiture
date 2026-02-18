"""OpenTelemetry tracing for migrations.

Provides optional tracing integration for migration execution.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TracingConfig:
    """Configuration for OpenTelemetry tracing."""

    enabled: bool = False
    service_name: str = "confiture"
    endpoint: str | None = None  # OTLP endpoint
    sample_rate: float = 1.0


class MigrationTracer:
    """OpenTelemetry tracer for migrations.

    Provides tracing spans for migration operations when OpenTelemetry
    is installed and configured.

    Example:
        >>> tracer = MigrationTracer(TracingConfig(enabled=True))
        >>> with tracer.span("migration.apply", migration_id="001"):
        ...     # Migration code
        ...     pass
    """

    def __init__(self, config: TracingConfig):
        """Initialize migration tracer.

        Args:
            config: Tracing configuration
        """
        self.config = config
        self._tracer: Any = None
        self._initialized = False

        if config.enabled:
            self._initialize_tracer()

    def _initialize_tracer(self) -> None:
        """Initialize OpenTelemetry tracer."""
        try:
            from opentelemetry import trace  # type: ignore[import]
            from opentelemetry.sdk.resources import Resource  # type: ignore[import]
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]

            # Create resource
            resource = Resource.create(
                {
                    "service.name": self.config.service_name,
                    "service.version": "0.5.2",
                }
            )

            # Create provider
            provider = TracerProvider(resource=resource)

            # Add exporter if endpoint configured
            if self.config.endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import]
                        OTLPSpanExporter,
                    )

                    exporter = OTLPSpanExporter(endpoint=self.config.endpoint)
                    provider.add_span_processor(BatchSpanProcessor(exporter))
                except ImportError:
                    logger.warning(
                        "OTLP exporter not installed. Install with: "
                        "pip install opentelemetry-exporter-otlp"
                    )

            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("confiture")
            self._initialized = True

            logger.info("OpenTelemetry tracing initialized")

        except ImportError:
            logger.warning(
                "OpenTelemetry not installed. Install with: pip install confiture[observability]"
            )
            self.config.enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if tracing is enabled and initialized."""
        return self.config.enabled and self._initialized

    @contextmanager
    def span(
        self,
        name: str,
        **attributes: Any,
    ) -> Generator[Any, None, None]:
        """Create a tracing span.

        Args:
            name: Span name
            **attributes: Span attributes

        Yields:
            Span context (or None if disabled)
        """
        if not self.is_enabled or self._tracer is None:
            yield None
            return

        with self._tracer.start_as_current_span(name) as span:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))
            yield span

    def record_migration_start(
        self,
        migration_version: str,
        migration_name: str,
    ) -> Any:
        """Create a span for migration start.

        Args:
            migration_version: Migration version
            migration_name: Migration name

        Returns:
            Span context manager
        """
        return self.span(
            "confiture.migration.execute",
            migration_version=migration_version,
            migration_name=migration_name,
        )

    def record_error(self, span: Any, error: Exception) -> None:
        """Record error on span.

        Args:
            span: Active span
            error: Exception that occurred
        """
        if span is None or not self.is_enabled:
            return

        try:
            from opentelemetry import trace  # type: ignore[import]

            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.record_exception(error)
        except ImportError:
            pass

    def record_success(self, span: Any, duration_ms: int) -> None:
        """Record successful completion on span.

        Args:
            span: Active span
            duration_ms: Duration in milliseconds
        """
        if span is None or not self.is_enabled:
            return

        try:
            from opentelemetry import trace  # type: ignore[import]

            span.set_attribute("duration_ms", duration_ms)
            span.set_status(trace.Status(trace.StatusCode.OK))
        except ImportError:
            pass


def create_tracer(config: TracingConfig | None = None) -> MigrationTracer:
    """Factory function to create tracer.

    Args:
        config: Tracing configuration (optional)

    Returns:
        Configured MigrationTracer
    """
    return MigrationTracer(config or TracingConfig())
