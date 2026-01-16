"""Performance baseline management with statistical confidence - Phase 6."""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """Severity levels for performance issues."""

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class PerformanceBaseline:
    """Performance baseline with statistical confidence."""

    operation_id: str  # Query hash or migration name
    environment: str  # "local", "staging", "production"
    baseline_duration_ms: int  # Mean
    confidence_interval: tuple[int, int]  # (lower, upper) - 95% CI
    sample_count: int  # How many measurements
    recorded_at: datetime = field(default_factory=datetime.utcnow)
    recorded_by_version: str = ""
    baseline_age_days: int = 0
    confidence_level: float = 0.95  # Statistical confidence


@dataclass
class RegressionResult:
    """Result of regression check."""

    is_regression: bool
    reason: str  # "NO_BASELINE", "BASELINE_STALE", "IMPROVEMENT", "REGRESSION", "OK"
    message: str
    severity: IssueSeverity


class BaselineStorage:
    """Abstract storage interface for baselines."""

    def save(self, baseline: PerformanceBaseline) -> None:
        """Save baseline."""
        raise NotImplementedError

    def get(self, operation_id: str, environment: str) -> PerformanceBaseline | None:
        """Get baseline."""
        raise NotImplementedError

    def get_history(
        self,
        operation_id: str,
        environment: str,
        days: int = 30,
    ) -> list[PerformanceBaseline]:
        """Get baseline history."""
        raise NotImplementedError


class InMemoryBaselineStorage(BaselineStorage):
    """In-memory baseline storage for testing."""

    def __init__(self):
        self.baselines: dict[tuple[str, str], PerformanceBaseline] = {}
        self.history: dict[tuple[str, str], list[PerformanceBaseline]] = {}

    def save(self, baseline: PerformanceBaseline) -> None:
        """Save baseline."""
        key = (baseline.operation_id, baseline.environment)
        self.baselines[key] = baseline

        if key not in self.history:
            self.history[key] = []
        self.history[key].append(baseline)

    def get(self, operation_id: str, environment: str) -> PerformanceBaseline | None:
        """Get baseline."""
        key = (operation_id, environment)
        return self.baselines.get(key)

    def get_history(
        self,
        operation_id: str,
        environment: str,
        days: int = 30,
    ) -> list[PerformanceBaseline]:
        """Get baseline history."""
        key = (operation_id, environment)
        return self.history.get(key, [])


class PerformanceBaselineManager:
    """Manage performance baselines with precision."""

    def __init__(self, storage: BaselineStorage | None = None):
        self.storage = storage or InMemoryBaselineStorage()

    def record_baseline(
        self,
        operation_id: str,
        environment: str,
        measurements: list[int],  # Duration in ms
        version: str,
    ) -> PerformanceBaseline:
        """Record baseline with statistical confidence."""

        # Calculate statistics
        mean = statistics.mean(measurements)
        stdev = (
            statistics.stdev(measurements)
            if len(measurements) > 1
            else 0
        )

        # 95% confidence interval
        confidence_interval = (
            max(0, int(mean - 2 * stdev)),  # Lower bound
            int(mean + 2 * stdev),  # Upper bound
        )

        baseline = PerformanceBaseline(
            operation_id=operation_id,
            environment=environment,
            baseline_duration_ms=int(mean),
            confidence_interval=confidence_interval,
            sample_count=len(measurements),
            recorded_by_version=version,
            confidence_level=0.95,
        )

        self.storage.save(baseline)
        logger.info(
            f"Recorded baseline for {operation_id} in {environment}: "
            f"{baseline.baseline_duration_ms}ms (CI: {confidence_interval})"
        )
        return baseline

    def check_regression(
        self,
        operation_id: str,
        environment: str,
        actual_duration_ms: int,
        regression_threshold_percent: float = 20.0,
    ) -> RegressionResult:
        """Check if actual performance is a regression."""

        baseline = self.storage.get(operation_id, environment)

        if not baseline:
            return RegressionResult(
                is_regression=False,
                reason="NO_BASELINE",
                message=f"No baseline for {operation_id} in {environment}",
                severity=IssueSeverity.INFO,
            )

        # Check baseline age
        baseline_age_days = (datetime.utcnow() - baseline.recorded_at).days
        if baseline_age_days > 30:
            return RegressionResult(
                is_regression=False,
                reason="BASELINE_STALE",
                message=f"Baseline is {baseline_age_days} days old, treating as stale",
                severity=IssueSeverity.WARNING,
            )

        # Check if within confidence interval
        lower, upper = baseline.confidence_interval

        if actual_duration_ms < lower:
            improvement_percent = (
                (baseline.baseline_duration_ms - actual_duration_ms)
                / baseline.baseline_duration_ms
                * 100
            )
            return RegressionResult(
                is_regression=False,
                reason="IMPROVEMENT",
                message=f"Performance improved {improvement_percent:.1f}%: "
                f"{actual_duration_ms}ms vs {baseline.baseline_duration_ms}ms",
                severity=IssueSeverity.INFO,
            )

        if actual_duration_ms > upper:
            percent_increase = (
                (actual_duration_ms - baseline.baseline_duration_ms)
                / baseline.baseline_duration_ms
                * 100
            )

            if percent_increase > regression_threshold_percent:
                return RegressionResult(
                    is_regression=True,
                    reason="REGRESSION",
                    message=f"Performance regressed {percent_increase:.1f}%: "
                    f"{actual_duration_ms}ms vs baseline {baseline.baseline_duration_ms}ms",
                    severity=IssueSeverity.ERROR,
                )

        return RegressionResult(
            is_regression=False,
            reason="OK",
            message=f"Within confidence interval ({lower}-{upper}ms)",
            severity=IssueSeverity.OK,
        )

    def get_evolution(
        self,
        operation_id: str,
        environment: str,
        days: int = 30,
    ) -> list[PerformanceBaseline]:
        """Get baseline evolution over time."""
        return self.storage.get_history(operation_id, environment, days)
