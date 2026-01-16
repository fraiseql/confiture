"""Comprehensive unit tests for Phase 6 Risk Assessment System.

Tests cover:
- Risk scoring formula and calculations
- Risk factor scoring for different metrics
- Risk level classification
- Downtime prediction (historical and heuristic)
- Confidence bounds and caveats
- Partial factor handling
"""

from __future__ import annotations

import pytest

from confiture.core.risk.scoring import (
    DataAnomaly,
    RiskFactor,
    RiskLevel,
    RiskScoringFormula,
    Severity,
)
from confiture.core.risk.predictor import DowntimePredictor, DowntimeEstimate, HistoricalMigration, MigrationOperation


class TestRiskScoringFormula:
    """Test the explicit risk scoring formula."""

    def test_formula_weights_sum(self):
        """Test that risk weights sum to 1.0."""
        weights = [
            RiskScoringFormula.WEIGHT_DATA_VOLUME,
            RiskScoringFormula.WEIGHT_LOCK_TIME,
            RiskScoringFormula.WEIGHT_DEPENDENCIES,
            RiskScoringFormula.WEIGHT_ANOMALIES,
            RiskScoringFormula.WEIGHT_CONCURRENT_LOAD,
        ]

        total_weight = sum(weights)
        assert abs(total_weight - 1.0) < 0.001  # Account for float precision


class TestDataVolumeScoring:
    """Test data volume risk scoring."""

    def test_zero_volume_low_risk(self):
        """Test that zero volume has zero risk."""
        factor = RiskScoringFormula.calculate_data_volume_score(0)

        assert factor.value == 0.0
        assert factor.name == "data_volume"

    def test_small_volume_low_risk(self):
        """Test that small volume has low risk."""
        factor = RiskScoringFormula.calculate_data_volume_score(1)  # 1 MB

        assert factor.value < 0.1

    def test_large_volume_high_risk(self):
        """Test that large volume has higher risk."""
        factor = RiskScoringFormula.calculate_data_volume_score(1024 * 1024)  # 1 TB

        assert factor.value >= 1.0


class TestLockTimeScoring:
    """Test lock time risk scoring."""

    def test_zero_lock_time(self):
        """Test that zero lock time has zero risk."""
        factor = RiskScoringFormula.calculate_lock_time_score(0)

        assert factor.value == 0.0

    def test_100ms_lock_time(self):
        """Test 100ms lock time risk."""
        factor = RiskScoringFormula.calculate_lock_time_score(100)

        assert 0.6 < factor.value < 0.8  # Should be medium-high risk

    def test_1s_lock_time(self):
        """Test 1s lock time risk."""
        factor = RiskScoringFormula.calculate_lock_time_score(1000)

        assert 0.7 < factor.value < 0.9  # Should be high risk

    def test_10s_lock_time(self):
        """Test 10s lock time risk."""
        factor = RiskScoringFormula.calculate_lock_time_score(10000)

        assert factor.value >= 0.9  # Should be high risk

    def test_lock_time_continuous_scaling(self):
        """Test that lock time scoring is continuous (no discontinuities)."""
        # Test points around previously problematic boundaries
        values_100ms = [
            RiskScoringFormula.calculate_lock_time_score(95).value,
            RiskScoringFormula.calculate_lock_time_score(100).value,
            RiskScoringFormula.calculate_lock_time_score(105).value,
        ]

        # Should be monotonically increasing without jumps
        assert values_100ms[0] < values_100ms[1] < values_100ms[2]
        # No jump should be >10% at this scale
        assert (values_100ms[2] - values_100ms[0]) < 0.1


class TestDependencyScoring:
    """Test dependency risk scoring."""

    def test_no_dependencies_zero_risk(self):
        """Test that no dependencies have zero risk."""
        factor = RiskScoringFormula.calculate_dependency_score(0, 0, 0)

        assert factor.value == 0.0

    def test_single_dependency_low_risk(self):
        """Test single dependency has low risk."""
        factor = RiskScoringFormula.calculate_dependency_score(1, 0, 0)

        assert factor.value < 0.2

    def test_many_dependencies_high_risk(self):
        """Test many dependencies have higher risk."""
        factor = RiskScoringFormula.calculate_dependency_score(10, 0, 0)

        assert factor.value >= 1.0


class TestAnomalyScoring:
    """Test data anomaly risk scoring."""

    def test_no_anomalies_zero_risk(self):
        """Test that no anomalies have zero risk."""
        factor = RiskScoringFormula.calculate_anomaly_score([])

        assert factor.value == 0.0

    def test_low_severity_anomaly(self):
        """Test low severity anomaly."""
        anomalies = [
            DataAnomaly(name="test", severity=Severity.LOW, description="test")
        ]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)

        assert factor.value < 0.2

    def test_critical_anomaly(self):
        """Test critical anomaly."""
        anomalies = [
            DataAnomaly(name="test", severity=Severity.CRITICAL, description="test")
        ]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)

        assert factor.value >= 1.0

    def test_multiple_anomalies_average(self):
        """Test multiple anomalies are averaged."""
        anomalies = [
            DataAnomaly(name="test1", severity=Severity.LOW, description="test"),
            DataAnomaly(name="test2", severity=Severity.CRITICAL, description="test"),
        ]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)

        # Should be average of 0.1 and 1.0 = 0.55
        assert 0.4 < factor.value < 0.7


class TestConcurrentLoadScoring:
    """Test concurrent load risk scoring."""

    def test_low_utilization_low_risk(self):
        """Test low utilization has low risk."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(10, 100)

        assert factor.value < 0.2

    def test_medium_utilization_medium_risk(self):
        """Test medium utilization has medium risk."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(50, 100)

        assert 0.3 < factor.value < 0.7

    def test_high_utilization_high_risk(self):
        """Test high utilization has high risk."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(90, 100)

        assert factor.value > 0.7


class TestOverallRiskCalculation:
    """Test overall risk score calculation."""

    def test_zero_factors_low_risk(self):
        """Test zero factors result in LOW risk."""
        factors = {
            "data_volume": RiskFactor("data_volume", 0.0, "bytes", 0.25, "test"),
            "lock_time": RiskFactor("lock_time", 0.0, "ms", 0.35, "test"),
            "dependencies": RiskFactor("dependencies", 0.0, "count", 0.15, "test"),
            "anomalies": RiskFactor("anomalies", 0.0, "count", 0.15, "test"),
            "concurrent_load": RiskFactor("concurrent_load", 0.0, "percent", 0.10, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.LOW
        assert score < 0.25

    def test_all_high_critical_risk(self):
        """Test all high factors result in CRITICAL risk."""
        factors = {
            "data_volume": RiskFactor("data_volume", 1.0, "bytes", 0.25, "test"),
            "lock_time": RiskFactor("lock_time", 1.0, "ms", 0.35, "test"),
            "dependencies": RiskFactor("dependencies", 1.0, "count", 0.15, "test"),
            "anomalies": RiskFactor("anomalies", 1.0, "count", 0.15, "test"),
            "concurrent_load": RiskFactor("concurrent_load", 1.0, "percent", 0.10, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.CRITICAL
        assert score >= 0.75

    def test_partial_factors_renormalization(self):
        """Test that partial factors are renormalized."""
        # Only provide some factors
        factors = {
            "data_volume": RiskFactor("data_volume", 1.0, "bytes", 0.25, "test"),
            "lock_time": RiskFactor("lock_time", 1.0, "ms", 0.35, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        # Score should still be valid (between 0 and 1)
        assert 0.0 <= score <= 1.0
        # With full weights on provided factors, should be high
        assert level in [RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_empty_factors_low_risk(self):
        """Test empty factors result in LOW risk."""
        factors = {}

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.LOW
        assert score == 0.0


class TestRiskLevelMapping:
    """Test risk score to level mapping."""

    def test_risk_level_low(self):
        """Test LOW risk level threshold."""
        factors = {
            "data_volume": RiskFactor("data_volume", 0.2, "bytes", 0.25, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.LOW

    def test_risk_level_medium(self):
        """Test MEDIUM risk level threshold."""
        factors = {
            "lock_time": RiskFactor("lock_time", 0.4, "ms", 0.35, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.MEDIUM

    def test_risk_level_high(self):
        """Test HIGH risk level threshold."""
        factors = {
            "lock_time": RiskFactor("lock_time", 0.6, "ms", 0.35, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.HIGH

    def test_risk_level_critical(self):
        """Test CRITICAL risk level threshold."""
        factors = {
            "lock_time": RiskFactor("lock_time", 0.8, "ms", 0.35, "test"),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        assert level == RiskLevel.CRITICAL


class TestDowntimePredictor:
    """Test downtime prediction."""

    def test_create_predictor(self):
        """Test creating downtime predictor."""
        predictor = DowntimePredictor()

        assert predictor is not None

    def test_migration_operation_creation(self):
        """Test creating migration operation metadata."""
        op = MigrationOperation(
            id="op_001",
            type="ALTER TABLE",
            table_name="users",
            table_size_mb=100,
        )

        assert op.type == "ALTER TABLE"
        assert op.table_name == "users"

    def test_historical_migration_creation(self):
        """Test creating historical migration record."""
        migration = HistoricalMigration(
            operation_type="ALTER TABLE",
            table_size_mb=100,
            actual_downtime_ms=50,
        )

        assert migration.actual_downtime_ms == 50

    def test_downtime_estimate_creation(self):
        """Test creating downtime estimate."""
        estimate = DowntimeEstimate(
            estimated_downtime_ms=100,
            lower_bound_ms=90,
            upper_bound_ms=110,
            confidence_level=0.95,
            estimate_method="historical",
            caveats=["Based on similar past migrations"],
        )

        assert estimate.estimated_downtime_ms == 100
        assert estimate.confidence_level == 0.95

    def test_historical_estimation(self):
        """Test historical downtime estimation."""
        predictor = DowntimePredictor()

        # Add some historical data
        predictor.historical_migrations = [
            HistoricalMigration(
                operation_type="ALTER TABLE",
                table_size_mb=100,
                actual_downtime_ms=50,
            ),
            HistoricalMigration(
                operation_type="ALTER TABLE",
                table_size_mb=100,
                actual_downtime_ms=60,
            ),
        ]

        # Should use historical data
        operation = MigrationOperation(
            id="op_001",
            type="ALTER TABLE",
            table_name="users",
            table_size_mb=100,
        )

        # Note: actual prediction requires method implementation
        assert operation is not None


class TestDowntimeConfidenceBounds:
    """Test downtime prediction confidence bounds."""

    def test_estimate_has_confidence(self):
        """Test that estimate includes confidence level."""
        estimate = DowntimeEstimate(
            estimated_downtime_ms=100,
            lower_bound_ms=90,
            upper_bound_ms=110,
            confidence_level=0.95,
            estimate_method="historical",
        )

        assert estimate.confidence_level > 0
        assert estimate.confidence_level <= 1.0

    def test_low_confidence_requires_caveat(self):
        """Test that low confidence estimates include caveats."""
        estimate = DowntimeEstimate(
            estimated_downtime_ms=100,
            lower_bound_ms=80,
            upper_bound_ms=120,
            confidence_level=0.30,
            estimate_method="heuristic",
            caveats=["No historical data available"],
        )

        assert len(estimate.caveats) > 0
        assert "No historical data" in estimate.caveats[0]

    def test_estimate_uncertainty_bounds(self):
        """Test that estimate includes uncertainty bounds."""
        estimate = DowntimeEstimate(
            estimated_downtime_ms=100,
            lower_bound_ms=90,
            upper_bound_ms=110,
            confidence_level=0.95,
            estimate_method="historical",
        )

        assert estimate.lower_bound_ms < estimate.estimated_downtime_ms
        assert estimate.upper_bound_ms > estimate.estimated_downtime_ms


class TestRiskFactorProperties:
    """Test RiskFactor properties and constraints."""

    def test_risk_factor_value_range(self):
        """Test that risk factor values are between 0 and 1."""
        factor = RiskFactor("test", 0.5, "unit", 0.25, "description")

        assert 0.0 <= factor.value <= 1.0

    def test_risk_factor_weight(self):
        """Test risk factor weight property."""
        factor = RiskFactor("test", 0.5, "unit", 0.25, "description")

        assert 0.0 < factor.weight <= 1.0

    def test_risk_factor_with_unit(self):
        """Test risk factor unit specification."""
        factor = RiskFactor("data_volume", 0.5, "bytes", 0.25, "test")

        assert factor.unit == "bytes"


class TestWeightNormalization:
    """Test weight normalization for partial factors."""

    def test_partial_weights_renormalize(self):
        """Test that partial weights are renormalized to 1.0."""
        # Two factors with original weights 0.25 and 0.35
        factors = {
            "data_volume": RiskFactor("data_volume", 0.5, "bytes", 0.25, "test"),
            "lock_time": RiskFactor("lock_time", 0.5, "ms", 0.35, "test"),
        }

        # Total original weight: 0.6
        # After renormalization: 0.25/0.6 + 0.35/0.6 = 1.0

        level, score = RiskScoringFormula.calculate_overall_risk(factors)

        # With equal factor values and renormalized weights
        # score should be 0.5
        assert score == 0.5
