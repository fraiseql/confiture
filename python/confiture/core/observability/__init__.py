"""Observability module for Confiture.

Provides optional integrations with:
- OpenTelemetry (tracing)
- Prometheus (metrics)
- Structured logging
- Audit trail
"""

from confiture.core.observability.audit import (
    AuditConfig,
    AuditEntry,
    AuditTrail,
)
from confiture.core.observability.logging import (
    LoggingConfig,
    StructuredLogger,
    configure_logging,
)
from confiture.core.observability.metrics import (
    MetricsConfig,
    MigrationMetrics,
    create_metrics,
)
from confiture.core.observability.tracing import (
    MigrationTracer,
    TracingConfig,
    create_tracer,
)

__all__ = [
    "TracingConfig",
    "MigrationTracer",
    "create_tracer",
    "MetricsConfig",
    "MigrationMetrics",
    "create_metrics",
    "LoggingConfig",
    "StructuredLogger",
    "configure_logging",
    "AuditConfig",
    "AuditTrail",
    "AuditEntry",
]
