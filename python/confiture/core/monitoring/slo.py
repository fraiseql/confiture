"""Service Level Objectives and monitoring - Phase 6."""
from __future__ import annotations


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
class SLOConfiguration:
    """Environment-aware SLO configuration.

    Different environments have different performance expectations:
    - local: Development machine, relaxed latency targets
    - staging: Production-like, moderate latency targets
    - production: Strict latency targets for user-facing operations
    """

    environment: str  # "local", "staging", "production"

    # Hook execution SLOs
    hook_execution_latency_p99_ms: int  # P99 latency per hook
    hook_execution_latency_p95_ms: int  # P95 latency per hook
    hook_execution_timeout_ms: int  # Global timeout for entire hook execution

    # Risk assessment SLOs
    risk_assessment_latency_p99_ms: int  # P99 latency
    risk_assessment_latency_p95_ms: int  # P95 latency

    # Profiling overhead SLOs
    profiling_overhead_percent: float  # Max overhead as percentage
    profiling_accuracy_minimum: float  # Minimum accuracy (0.0-1.0)

    # Rule library SLOs
    rule_composition_latency_ms: int  # Time to compose rules
    rule_conflict_detection_latency_ms: int  # Time to detect conflicts

    # Performance baseline SLOs
    baseline_lookup_latency_ms: int  # Time to lookup baseline
    regression_check_latency_ms: int  # Time to check regression

    def get_target_for_operation(self, operation: str) -> int | None:
        """Get SLO target for a specific operation.

        Args:
            operation: Operation name (e.g., "hook_execution", "risk_assessment")

        Returns:
            Target latency in milliseconds, or None if operation not recognized
        """
        targets = {
            "hook_execution_p99": self.hook_execution_latency_p99_ms,
            "hook_execution_p95": self.hook_execution_latency_p95_ms,
            "risk_assessment_p99": self.risk_assessment_latency_p99_ms,
            "risk_assessment_p95": self.risk_assessment_latency_p95_ms,
            "rule_composition": self.rule_composition_latency_ms,
            "rule_conflict_detection": self.rule_conflict_detection_latency_ms,
            "baseline_lookup": self.baseline_lookup_latency_ms,
            "regression_check": self.regression_check_latency_ms,
        }
        return targets.get(operation)


# Environment-specific SLO configurations
SLO_CONFIGURATIONS = {
    "local": SLOConfiguration(
        environment="local",
        # Local development: relaxed targets
        hook_execution_latency_p99_ms=100,
        hook_execution_latency_p95_ms=50,
        hook_execution_timeout_ms=60000,  # 60 second timeout
        risk_assessment_latency_p99_ms=10000,
        risk_assessment_latency_p95_ms=5000,
        profiling_overhead_percent=10.0,
        profiling_accuracy_minimum=0.7,
        rule_composition_latency_ms=200,
        rule_conflict_detection_latency_ms=100,
        baseline_lookup_latency_ms=20,
        regression_check_latency_ms=50,
    ),
    "staging": SLOConfiguration(
        environment="staging",
        # Staging: production-like
        hook_execution_latency_p99_ms=75,
        hook_execution_latency_p95_ms=40,
        hook_execution_timeout_ms=45000,  # 45 second timeout
        risk_assessment_latency_p99_ms=7000,
        risk_assessment_latency_p95_ms=3000,
        profiling_overhead_percent=7.0,
        profiling_accuracy_minimum=0.75,
        rule_composition_latency_ms=125,
        rule_conflict_detection_latency_ms=70,
        baseline_lookup_latency_ms=15,
        regression_check_latency_ms=30,
    ),
    "production": SLOConfiguration(
        environment="production",
        # Production: strict targets for user-facing operations
        hook_execution_latency_p99_ms=50,
        hook_execution_latency_p95_ms=30,
        hook_execution_timeout_ms=30000,  # 30 second timeout
        risk_assessment_latency_p99_ms=5000,
        risk_assessment_latency_p95_ms=2000,
        profiling_overhead_percent=5.0,
        profiling_accuracy_minimum=0.8,
        rule_composition_latency_ms=100,
        rule_conflict_detection_latency_ms=50,
        baseline_lookup_latency_ms=10,
        regression_check_latency_ms=20,
    ),
}


# Legacy class for backward compatibility
@dataclass
class ServiceLevelObjective:
    """Define SLOs for Phase 6 operations (DEPRECATED).

    Use SLOConfiguration with environment-specific targets instead.
    This class is maintained for backward compatibility only.
    """

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


# Get default SLO configuration (production)
def get_slo_config(environment: str = "production") -> SLOConfiguration:
    """Get SLO configuration for the specified environment.

    Args:
        environment: Environment name ("local", "staging", or "production")

    Returns:
        SLOConfiguration for the environment, defaults to production if not found

    Raises:
        ValueError: If environment is not recognized
    """
    if environment not in SLO_CONFIGURATIONS:
        available = ", ".join(SLO_CONFIGURATIONS.keys())
        raise ValueError(
            f"Unknown environment: {environment}. Available: {available}"
        )
    return SLO_CONFIGURATIONS[environment]


# Legacy default SLOs (production environment)
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
