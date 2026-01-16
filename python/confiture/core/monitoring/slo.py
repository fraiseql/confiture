"""Service Level Objectives and monitoring - Phase 6."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class OperationStatus(Enum):
    """Operation status."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ServiceLevelObjective:
    """Define SLOs for Phase 6 operations."""

    # Hook execution SLOs
    HOOK_EXECUTION_LATENCY_P99_MS = 50  # 50ms per hook max
    HOOK_EXECUTION_LATENCY_P95_MS = 30
    HOOK_EXECUTION_TIMEOUT_MS = 30000  # 30 second global timeout

    # Risk assessment SLOs
    RISK_ASSESSMENT_LATENCY_P99_MS = 5000  # 5 second max
    RISK_ASSESSMENT_LATENCY_P95_MS = 2000

    # Profiling overhead SLOs
    PROFILING_OVERHEAD_PERCENT = 5.0  # Max 5% overhead
    PROFILING_ACCURACY_MINIMUM = 0.8  # At least 80% accurate

    # Rule library SLOs
    RULE_COMPOSITION_LATENCY_MS = 100  # <100ms to compose
    RULE_CONFLICT_DETECTION_LATENCY_MS = 50

    # Performance baseline SLOs
    BASELINE_LOOKUP_LATENCY_MS = 10  # <10ms to lookup
    REGRESSION_CHECK_LATENCY_MS = 20  # <20ms to check


@dataclass
class OperationMetric:
    """Metrics for a single operation."""

    operation: str
    duration_ms: int
    slo_target_ms: int
    compliant: bool = field(init=False)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        self.compliant = self.duration_ms <= self.slo_target_ms


@dataclass
class SLOViolation:
    """Record of an SLO violation."""

    operation: str
    target_ms: int
    actual_ms: int
    percentile: int  # 95, 99, etc.
    severity: str  # "warning", "error", "critical"
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SLOMonitor:
    """Monitor SLO compliance."""

    def __init__(self):
        self.metrics: list[OperationMetric] = []
        self.violations: list[SLOViolation] = []

    def record_metric(
        self,
        operation: str,
        duration_ms: int,
        slo_target_ms: int,
    ) -> None:
        """Record operation metric."""
        metric = OperationMetric(
            operation=operation,
            duration_ms=duration_ms,
            slo_target_ms=slo_target_ms,
        )
        self.metrics.append(metric)

        if not metric.compliant:
            violation = SLOViolation(
                operation=operation,
                target_ms=slo_target_ms,
                actual_ms=duration_ms,
                percentile=95,  # Assumed percentile
                severity="warning" if duration_ms < slo_target_ms * 1.5 else "error",
            )
            self.violations.append(violation)
            logger.warning(f"SLO violation: {operation} took {duration_ms}ms (target: {slo_target_ms}ms)")

    def get_slo_compliance(
        self,
        operation: str,
        percentile: int = 95,
    ) -> float:
        """Get SLO compliance percentage."""
        metrics = [m for m in self.metrics if m.operation == operation]
        if not metrics:
            return 0.0

        compliant = sum(1 for m in metrics if m.compliant)
        return (compliant / len(metrics)) * 100

    def get_compliance_report(self) -> dict[str, float]:
        """Get compliance report for all operations."""
        operations = set(m.operation for m in self.metrics)
        return {
            op: self.get_slo_compliance(op)
            for op in operations
        }

    def get_violations(self, operation: str | None = None) -> list[SLOViolation]:
        """Get violations, optionally filtered by operation."""
        if operation:
            return [v for v in self.violations if v.operation == operation]
        return self.violations

    def get_violation_summary(self) -> dict[str, int]:
        """Get summary of violations by operation."""
        summary: dict[str, int] = {}
        for violation in self.violations:
            summary[violation.operation] = summary.get(violation.operation, 0) + 1
        return summary

    def is_compliant(self, operation: str, threshold_percent: float = 95.0) -> bool:
        """Check if operation meets compliance threshold."""
        compliance = self.get_slo_compliance(operation)
        return compliance >= threshold_percent


# Predefined SLO configurations
DEFAULT_SLOS = {
    "hook_execution": 50,  # ms
    "hook_execution_p95": 30,  # ms
    "risk_assessment": 5000,  # ms
    "risk_assessment_p95": 2000,  # ms
    "profiling_overhead": 5.0,  # percent
    "rule_composition": 100,  # ms
    "rule_conflict_detection": 50,  # ms
    "baseline_lookup": 10,  # ms
    "regression_check": 20,  # ms
}
