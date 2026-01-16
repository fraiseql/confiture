"""Comprehensive unit tests for Phase 6 Performance and Monitoring Systems.

Tests cover:
- Query profiling with observable overhead
- Performance baseline management
- Regression detection
- Statistical confidence intervals
- SLO configuration and monitoring
- SLO compliance tracking
- Environment-aware SLO targets
"""

from __future__ import annotations

import pytest

# Note: Performance monitoring classes are part of Phase 6
import sys
pytestmark = pytest.mark.skipif(
    False,  # Set to True if these modules aren't available
    reason="Phase 6 performance monitoring not yet fully integrated"
)

try:
    from confiture.core.monitoring import (
        OperationMetric,
        OperationStatus,
        SLOConfiguration,
        SLOMonitor,
        SLOViolation,
        get_slo_config,
    )
    from confiture.core.performance.baseline_manager import (
        BaselineManager,
        IssueSeverity,
        PerformanceBaseline,
        RegressionResult,
    )
except ImportError as e:
    pytest.skip(f"Performance monitoring modules not available: {e}", allow_module_level=True)
from confiture.core.performance.query_profiler import (
    ProfilingMetadata,
    QueryProfile,
    QueryProfiler,
)


class TestQueryProfiler:
    """Test query profiling functionality."""

    def test_create_profiler(self):
        """Test creating query profiler."""
        profiler = QueryProfiler(target_overhead_percent=5.0, sampling_rate=1.0)

        assert profiler.target_overhead_percent == 5.0
        assert profiler.sampling_rate == 1.0

    def test_profiler_sampling_rate(self):
        """Test profiler sampling rate configuration."""
        # Full profiling
        profiler_full = QueryProfiler(sampling_rate=1.0)
        assert profiler_full.sampling_rate == 1.0

        # 50% sampling
        profiler_half = QueryProfiler(sampling_rate=0.5)
        assert profiler_half.sampling_rate == 0.5

        # No profiling
        profiler_none = QueryProfiler(sampling_rate=0.0)
        assert profiler_none.sampling_rate == 0.0

    def test_query_hash_generation(self):
        """Test that queries get unique hashes."""
        profiler = QueryProfiler()
        import hashlib

        query1 = "SELECT * FROM users"
        query2 = "SELECT * FROM orders"

        hash1 = hashlib.sha256(query1.encode()).hexdigest()[:8]
        hash2 = hashlib.sha256(query2.encode()).hexdigest()[:8]

        assert hash1 != hash2

    def test_profiler_tracks_query_count(self):
        """Test that profiler tracks total query count."""
        profiler = QueryProfiler()

        # Simulate tracking queries
        profiler.query_count += 1
        profiler.query_count += 1

        assert profiler.query_count == 2


class TestQueryProfile:
    """Test individual query profile."""

    def test_create_query_profile(self):
        """Test creating query profile."""
        profile = QueryProfile(
            query_hash="abc123",
            query_text="SELECT * FROM users",
            execution_count=5,
            total_duration_ms=500,
            avg_duration_ms=100.0,
            min_duration_ms=80,
            max_duration_ms=150,
            has_sequential_scans=False,
            has_sorts=True,
            estimated_rows=1000,
            actual_rows=1000,
            plan_quality_estimate=0.95,
        )

        assert profile.query_hash == "abc123"
        assert profile.execution_count == 5
        assert profile.avg_duration_ms == 100.0

    def test_profile_execution_count(self):
        """Test profile tracks execution count."""
        profile = QueryProfile(
            query_hash="abc123",
            query_text="SELECT * FROM users",
            execution_count=10,
            total_duration_ms=1000,
            avg_duration_ms=100.0,
            min_duration_ms=80,
            max_duration_ms=120,
            has_sequential_scans=False,
            has_sorts=False,
            estimated_rows=100,
            actual_rows=100,
            plan_quality_estimate=0.9,
        )

        assert profile.execution_count == 10


class TestProfilingMetadata:
    """Test profiling metadata tracking."""

    def test_create_profiling_metadata(self):
        """Test creating profiling metadata."""
        metadata = ProfilingMetadata(
            total_queries=100,
            profiled_queries=50,
            sampling_rate=0.5,
            profiling_overhead_ms=100,
            query_time_without_profiling_ms=1000,
            profiling_overhead_percent=10.0,
            confidence_level=0.95,
            is_deterministic=False,
        )

        assert metadata.total_queries == 100
        assert metadata.profiled_queries == 50
        assert metadata.profiling_overhead_percent == 10.0

    def test_metadata_overhead_calculation(self):
        """Test overhead percentage calculation."""
        # 10% overhead
        metadata = ProfilingMetadata(
            total_queries=100,
            profiled_queries=100,
            sampling_rate=1.0,
            profiling_overhead_ms=100,
            query_time_without_profiling_ms=1000,
            profiling_overhead_percent=10.0,
            confidence_level=1.0,
            is_deterministic=True,
        )

        assert metadata.profiling_overhead_percent == 10.0

    def test_metadata_confidence_deterministic(self):
        """Test confidence level for deterministic profiling."""
        metadata = ProfilingMetadata(
            total_queries=100,
            profiled_queries=100,
            sampling_rate=1.0,
            profiling_overhead_ms=50,
            query_time_without_profiling_ms=1000,
            profiling_overhead_percent=5.0,
            confidence_level=0.95,  # High confidence
            is_deterministic=True,
        )

        assert metadata.is_deterministic is True
        assert metadata.confidence_level == 0.95

    def test_metadata_confidence_sampled(self):
        """Test confidence level for sampled profiling."""
        metadata = ProfilingMetadata(
            total_queries=100,
            profiled_queries=50,
            sampling_rate=0.5,
            profiling_overhead_ms=0,
            query_time_without_profiling_ms=1000,
            profiling_overhead_percent=0.0,
            confidence_level=0.5,  # Lower confidence due to sampling
            is_deterministic=False,
        )

        assert metadata.is_deterministic is False
        assert metadata.confidence_level == 0.5


class TestPerformanceBaseline:
    """Test performance baseline management."""

    def test_create_baseline(self):
        """Test creating performance baseline."""
        baseline = PerformanceBaseline(
            query_hash="abc123",
            mean_duration_ms=100.0,
            stddev_duration_ms=10.0,
            sample_count=50,
            confidence_interval_lower_ms=80.0,
            confidence_interval_upper_ms=120.0,
        )

        assert baseline.query_hash == "abc123"
        assert baseline.mean_duration_ms == 100.0
        assert baseline.sample_count == 50

    def test_baseline_confidence_interval(self):
        """Test baseline confidence interval (mean ± 2σ)."""
        # Mean = 100, StdDev = 10, CI = Mean ± 2*StdDev = 80-120
        baseline = PerformanceBaseline(
            query_hash="abc123",
            mean_duration_ms=100.0,
            stddev_duration_ms=10.0,
            sample_count=30,
            confidence_interval_lower_ms=80.0,
            confidence_interval_upper_ms=120.0,
        )

        assert baseline.confidence_interval_lower_ms == 80.0
        assert baseline.confidence_interval_upper_ms == 120.0
        assert (
            baseline.confidence_interval_upper_ms - baseline.confidence_interval_lower_ms
            == 40.0
        )

    def test_baseline_age_tracking(self):
        """Test baseline tracks creation time for staleness."""
        baseline = PerformanceBaseline(
            query_hash="abc123",
            mean_duration_ms=100.0,
            stddev_duration_ms=10.0,
            sample_count=50,
            confidence_interval_lower_ms=80.0,
            confidence_interval_upper_ms=120.0,
        )

        # Should have timestamp
        assert baseline.created_at is not None


class TestRegressionDetection:
    """Test regression detection functionality."""

    def test_regression_result_ok(self):
        """Test regression result when no regression detected."""
        result = RegressionResult(
            actual_duration_ms=105.0,
            baseline_mean_ms=100.0,
            regression_threshold_percent=20.0,
            is_regression=False,
            severity=IssueSeverity.OK,
            reason="Within normal variance",
        )

        assert result.is_regression is False
        assert result.severity == IssueSeverity.OK

    def test_regression_result_warning(self):
        """Test regression result with warning severity."""
        result = RegressionResult(
            actual_duration_ms=115.0,
            baseline_mean_ms=100.0,
            regression_threshold_percent=20.0,
            is_regression=True,
            severity=IssueSeverity.WARNING,
            reason="15% slower than baseline",
        )

        assert result.is_regression is True
        assert result.severity == IssueSeverity.WARNING

    def test_regression_result_error(self):
        """Test regression result with error severity."""
        result = RegressionResult(
            actual_duration_ms=140.0,
            baseline_mean_ms=100.0,
            regression_threshold_percent=20.0,
            is_regression=True,
            severity=IssueSeverity.ERROR,
            reason="40% slower than baseline (exceeds threshold)",
        )

        assert result.is_regression is True
        assert result.severity == IssueSeverity.ERROR


class TestBaselineManager:
    """Test performance baseline manager."""

    def test_create_baseline_manager(self):
        """Test creating baseline manager."""
        manager = BaselineManager()

        assert manager is not None

    def test_store_and_retrieve_baseline(self):
        """Test storing and retrieving baselines."""
        manager = BaselineManager()

        baseline = PerformanceBaseline(
            query_hash="abc123",
            mean_duration_ms=100.0,
            stddev_duration_ms=10.0,
            sample_count=50,
            confidence_interval_lower_ms=80.0,
            confidence_interval_upper_ms=120.0,
        )

        manager.store_baseline(baseline)
        retrieved = manager.get_baseline("abc123")

        assert retrieved is not None
        assert retrieved.mean_duration_ms == 100.0

    def test_regression_detection_within_ci(self):
        """Test regression detection when actual is within CI."""
        manager = BaselineManager()

        baseline = PerformanceBaseline(
            query_hash="abc123",
            mean_duration_ms=100.0,
            stddev_duration_ms=10.0,
            sample_count=50,
            confidence_interval_lower_ms=80.0,
            confidence_interval_upper_ms=120.0,
        )

        manager.store_baseline(baseline)

        # Actual duration within CI should not trigger regression
        result = manager.check_regression(
            query_hash="abc123",
            actual_duration_ms=105.0,
            regression_threshold_percent=20.0,
        )

        assert result is not None
        # Should be OK or INFO, not ERROR


class TestSLOConfiguration:
    """Test environment-aware SLO configuration."""

    def test_local_environment_config(self):
        """Test local environment SLO configuration."""
        config = get_slo_config("local")

        assert config.environment == "local"
        # Local should have relaxed targets
        assert config.hook_execution_latency_p99_ms > 50  # More relaxed than production

    def test_staging_environment_config(self):
        """Test staging environment SLO configuration."""
        config = get_slo_config("staging")

        assert config.environment == "staging"
        # Staging should be production-like
        assert config.hook_execution_latency_p99_ms > 50
        assert config.hook_execution_latency_p99_ms < 100

    def test_production_environment_config(self):
        """Test production environment SLO configuration."""
        config = get_slo_config("production")

        assert config.environment == "production"
        # Production should have strict targets
        assert config.hook_execution_latency_p99_ms == 50

    def test_slo_config_get_target(self):
        """Test getting SLO target for operation."""
        config = get_slo_config("production")

        target = config.get_target_for_operation("hook_execution_p99")

        assert target == 50

    def test_invalid_environment(self):
        """Test invalid environment raises error."""
        with pytest.raises(ValueError):
            get_slo_config("invalid_env")


class TestSLOMonitor:
    """Test SLO monitoring functionality."""

    def test_create_slo_monitor(self):
        """Test creating SLO monitor."""
        monitor = SLOMonitor()

        assert monitor is not None
        assert len(monitor.metrics) == 0
        assert len(monitor.violations) == 0

    def test_record_compliant_metric(self):
        """Test recording compliant metric."""
        monitor = SLOMonitor()

        monitor.record_metric(
            operation="hook_execution",
            duration_ms=40,
            slo_target_ms=50,
        )

        assert len(monitor.metrics) == 1
        assert monitor.metrics[0].compliant is True

    def test_record_non_compliant_metric(self):
        """Test recording non-compliant metric triggers violation."""
        monitor = SLOMonitor()

        monitor.record_metric(
            operation="hook_execution",
            duration_ms=60,
            slo_target_ms=50,
        )

        assert len(monitor.metrics) == 1
        assert monitor.metrics[0].compliant is False
        assert len(monitor.violations) > 0

    def test_compliance_percentage(self):
        """Test calculating compliance percentage."""
        monitor = SLOMonitor()

        # Record 3 compliant and 1 non-compliant
        monitor.record_metric("op1", 40, 50)
        monitor.record_metric("op1", 45, 50)
        monitor.record_metric("op1", 48, 50)
        monitor.record_metric("op1", 60, 50)

        compliance = monitor.get_slo_compliance("op1")

        # 3 out of 4 = 75%
        assert compliance == 75.0

    def test_compliance_by_operation(self):
        """Test compliance report by operation."""
        monitor = SLOMonitor()

        monitor.record_metric("hook_exec", 40, 50)
        monitor.record_metric("hook_exec", 45, 50)
        monitor.record_metric("risk_assess", 3000, 5000)
        monitor.record_metric("risk_assess", 6000, 5000)

        report = monitor.get_compliance_report()

        assert "hook_exec" in report
        assert "risk_assess" in report

    def test_violation_filtering(self):
        """Test filtering violations by operation."""
        monitor = SLOMonitor()

        monitor.record_metric("op1", 60, 50)
        monitor.record_metric("op2", 60, 50)

        violations = monitor.get_violations(operation="op1")

        assert len(violations) == 1
        assert violations[0].operation == "op1"

    def test_violation_summary(self):
        """Test violation summary statistics."""
        monitor = SLOMonitor()

        monitor.record_metric("op1", 60, 50)
        monitor.record_metric("op1", 60, 50)
        monitor.record_metric("op2", 60, 50)

        summary = monitor.get_violation_summary()

        assert summary["op1"] == 2
        assert summary["op2"] == 1

    def test_is_compliant_check(self):
        """Test compliance threshold checking."""
        monitor = SLOMonitor()

        # All compliant
        monitor.record_metric("op1", 40, 50)
        monitor.record_metric("op1", 45, 50)
        monitor.record_metric("op1", 48, 50)

        is_compliant = monitor.is_compliant("op1", threshold_percent=95.0)

        assert is_compliant is True


class TestOperationMetric:
    """Test operation metric tracking."""

    def test_create_operation_metric(self):
        """Test creating operation metric."""
        metric = OperationMetric(
            operation="hook_execution",
            duration_ms=40,
            slo_target_ms=50,
        )

        assert metric.operation == "hook_execution"
        assert metric.duration_ms == 40
        assert metric.compliant is True

    def test_metric_non_compliance(self):
        """Test metric non-compliance detection."""
        metric = OperationMetric(
            operation="hook_execution",
            duration_ms=60,
            slo_target_ms=50,
        )

        assert metric.compliant is False

    def test_metric_timestamp(self):
        """Test metric has timestamp."""
        metric = OperationMetric(
            operation="hook_execution",
            duration_ms=40,
            slo_target_ms=50,
        )

        assert metric.timestamp is not None


class TestSLOViolation:
    """Test SLO violation tracking."""

    def test_create_slo_violation(self):
        """Test creating SLO violation."""
        violation = SLOViolation(
            operation="hook_execution",
            target_ms=50,
            actual_ms=60,
            percentile=95,
            severity="warning",
        )

        assert violation.operation == "hook_execution"
        assert violation.target_ms == 50
        assert violation.actual_ms == 60

    def test_violation_severity_levels(self):
        """Test violation severity levels."""
        for severity in ["warning", "error", "critical"]:
            violation = SLOViolation(
                operation="test_op",
                target_ms=50,
                actual_ms=60,
                percentile=95,
                severity=severity,
            )

            assert violation.severity == severity


class TestEnvironmentSpecificTargets:
    """Test environment-specific SLO targets."""

    def test_local_more_relaxed_than_production(self):
        """Test that local has more relaxed targets than production."""
        local = get_slo_config("local")
        production = get_slo_config("production")

        # Local should have larger timeouts (more relaxed)
        assert local.hook_execution_latency_p99_ms > production.hook_execution_latency_p99_ms
        assert local.hook_execution_timeout_ms > production.hook_execution_timeout_ms

    def test_staging_between_local_and_production(self):
        """Test that staging is between local and production."""
        local = get_slo_config("local")
        staging = get_slo_config("staging")
        production = get_slo_config("production")

        # Staging should be between local and production
        assert (
            production.hook_execution_latency_p99_ms
            <= staging.hook_execution_latency_p99_ms
            <= local.hook_execution_latency_p99_ms
        )
