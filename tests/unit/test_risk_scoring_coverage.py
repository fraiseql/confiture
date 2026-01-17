"""Comprehensive tests for risk scoring formulas and factors.

Tests the transparent risk scoring system including individual factor scoring,
anomaly detection, and overall risk level calculations.
"""

from confiture.core.risk.scoring import (
    DataAnomaly,
    RiskFactor,
    RiskLevel,
    RiskScoringFormula,
    Severity,
)


class TestRiskLevel:
    """Test RiskLevel enum."""

    def test_risk_level_low(self):
        """Test LOW risk level."""
        assert RiskLevel.LOW.value == 1

    def test_risk_level_medium(self):
        """Test MEDIUM risk level."""
        assert RiskLevel.MEDIUM.value == 2

    def test_risk_level_high(self):
        """Test HIGH risk level."""
        assert RiskLevel.HIGH.value == 3

    def test_risk_level_critical(self):
        """Test CRITICAL risk level."""
        assert RiskLevel.CRITICAL.value == 4

    def test_all_risk_levels_defined(self):
        """Test all risk levels are defined."""
        levels = list(RiskLevel)
        assert len(levels) == 4


class TestSeverity:
    """Test Severity enum."""

    def test_severity_low(self):
        """Test LOW severity."""
        assert Severity.LOW.value == "low"

    def test_severity_medium(self):
        """Test MEDIUM severity."""
        assert Severity.MEDIUM.value == "medium"

    def test_severity_high(self):
        """Test HIGH severity."""
        assert Severity.HIGH.value == "high"

    def test_severity_critical(self):
        """Test CRITICAL severity."""
        assert Severity.CRITICAL.value == "critical"

    def test_all_severities_defined(self):
        """Test all severities are defined."""
        severities = list(Severity)
        assert len(severities) == 4


class TestDataAnomaly:
    """Test DataAnomaly dataclass."""

    def test_create_data_anomaly_basic(self):
        """Test creating basic data anomaly."""
        anomaly = DataAnomaly(
            name="null_values",
            severity=Severity.MEDIUM,
            description="Found 1000 null values in email column",
        )
        assert anomaly.name == "null_values"
        assert anomaly.severity == Severity.MEDIUM
        assert anomaly.description == "Found 1000 null values in email column"

    def test_create_data_anomaly_critical(self):
        """Test creating critical anomaly."""
        anomaly = DataAnomaly(
            name="data_loss",
            severity=Severity.CRITICAL,
            description="Missing 100k records",
        )
        assert anomaly.severity == Severity.CRITICAL

    def test_create_data_anomaly_low(self):
        """Test creating low severity anomaly."""
        anomaly = DataAnomaly(
            name="formatting",
            severity=Severity.LOW,
            description="Inconsistent date formats",
        )
        assert anomaly.severity == Severity.LOW

    def test_multiple_anomalies(self):
        """Test creating multiple anomalies."""
        anomalies = [
            DataAnomaly("issue1", Severity.LOW, "Minor issue"),
            DataAnomaly("issue2", Severity.HIGH, "Major issue"),
            DataAnomaly("issue3", Severity.CRITICAL, "Critical issue"),
        ]
        assert len(anomalies) == 3
        assert anomalies[0].severity == Severity.LOW
        assert anomalies[2].severity == Severity.CRITICAL


class TestRiskFactor:
    """Test RiskFactor dataclass."""

    def test_create_risk_factor_basic(self):
        """Test creating basic risk factor."""
        factor = RiskFactor(
            name="data_volume",
            value=0.5,
            unit="bytes",
            weight=0.25,
            description="Table size: 500MB",
        )
        assert factor.name == "data_volume"
        assert factor.value == 0.5
        assert factor.unit == "bytes"
        assert factor.weight == 0.25
        assert factor.description == "Table size: 500MB"

    def test_create_risk_factor_max_value(self):
        """Test creating risk factor with max value."""
        factor = RiskFactor(
            name="critical_factor",
            value=1.0,
            unit="percent",
            weight=0.35,
            description="Critical risk detected",
        )
        assert factor.value == 1.0

    def test_create_risk_factor_min_value(self):
        """Test creating risk factor with min value."""
        factor = RiskFactor(
            name="safe_factor",
            value=0.0,
            unit="milliseconds",
            weight=0.1,
            description="No risk",
        )
        assert factor.value == 0.0

    def test_risk_factor_units(self):
        """Test various risk factor units."""
        units = ["bytes", "milliseconds", "percent", "count", "seconds"]
        for unit in units:
            factor = RiskFactor(
                name="test",
                value=0.5,
                unit=unit,
                weight=0.2,
                description=f"Test {unit}",
            )
            assert factor.unit == unit


class TestRiskScoringFormulaDataVolume:
    """Test risk scoring for data volume."""

    def test_data_volume_very_small(self):
        """Test data volume scoring for very small table."""
        factor = RiskScoringFormula.calculate_data_volume_score(0)
        assert factor.value == 0.0
        assert factor.name == "data_volume"
        assert factor.weight == 0.25

    def test_data_volume_small(self):
        """Test data volume scoring for small table."""
        factor = RiskScoringFormula.calculate_data_volume_score(1)
        assert 0.0 <= factor.value <= 0.01

    def test_data_volume_medium(self):
        """Test data volume scoring for medium table."""
        factor = RiskScoringFormula.calculate_data_volume_score(512)  # 512MB
        assert 0.0 < factor.value < 1.0

    def test_data_volume_large(self):
        """Test data volume scoring for large table."""
        factor = RiskScoringFormula.calculate_data_volume_score(1024 * 1024)  # 1TB
        assert factor.value == 1.0

    def test_data_volume_very_large(self):
        """Test data volume scoring for very large table."""
        factor = RiskScoringFormula.calculate_data_volume_score(1024 * 1024 + 1)
        assert factor.value == 1.0

    def test_data_volume_1gb_threshold(self):
        """Test data volume at 1GB threshold."""
        factor = RiskScoringFormula.calculate_data_volume_score(1024)  # 1GB
        # 1024 / (1024 * 1024) = 1024 / 1048576 = 0.0009765625
        assert abs(factor.value - 0.001) < 0.001


class TestRiskScoringFormulaLockTime:
    """Test risk scoring for lock time."""

    def test_lock_time_zero(self):
        """Test lock time scoring for zero milliseconds."""
        factor = RiskScoringFormula.calculate_lock_time_score(0)
        assert factor.value == 0.0
        assert factor.name == "lock_time"
        assert factor.weight == 0.35

    def test_lock_time_negative(self):
        """Test lock time scoring for negative value."""
        factor = RiskScoringFormula.calculate_lock_time_score(-100)
        assert factor.value == 0.0

    def test_lock_time_1ms(self):
        """Test lock time at 1ms."""
        factor = RiskScoringFormula.calculate_lock_time_score(1)
        # log10(1) = 0, so (0 + 3) / 7 * 0.95 = 0.407
        assert 0.4 < factor.value < 0.45

    def test_lock_time_100ms(self):
        """Test lock time at 100ms (low risk)."""
        factor = RiskScoringFormula.calculate_lock_time_score(100)
        # log10(100) = 2, so (2 + 3) / 7 * 0.95 = 0.678
        assert 0.65 < factor.value < 0.70

    def test_lock_time_1000ms(self):
        """Test lock time at 1 second (medium risk)."""
        factor = RiskScoringFormula.calculate_lock_time_score(1000)
        # log10(1000) = 3, so (3 + 3) / 7 * 0.95 = 0.814
        assert 0.80 < factor.value < 0.82

    def test_lock_time_10000ms(self):
        """Test lock time at 10 seconds (high/critical risk)."""
        factor = RiskScoringFormula.calculate_lock_time_score(10000)
        assert factor.value == 1.0

    def test_lock_time_over_10000ms(self):
        """Test lock time over 10 seconds."""
        factor = RiskScoringFormula.calculate_lock_time_score(20000)
        assert factor.value == 1.0

    def test_lock_time_smooth_scaling(self):
        """Test lock time uses smooth scaling without discontinuities."""
        scores = [
            RiskScoringFormula.calculate_lock_time_score(ms).value
            for ms in [1, 10, 100, 1000, 10000]
        ]
        # Verify monotonic increase
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]


class TestRiskScoringFormulaDependencies:
    """Test risk scoring for dependencies."""

    def test_dependencies_none(self):
        """Test dependency scoring with no dependencies."""
        factor = RiskScoringFormula.calculate_dependency_score(0, 0, 0)
        assert factor.value == 0.0
        assert factor.name == "dependencies"
        assert factor.weight == 0.15

    def test_dependencies_single(self):
        """Test dependency scoring with one dependency."""
        factor = RiskScoringFormula.calculate_dependency_score(1, 0, 0)
        assert abs(factor.value - 0.1) < 0.01

    def test_dependencies_multiple_fks(self):
        """Test dependency scoring with multiple foreign keys."""
        factor = RiskScoringFormula.calculate_dependency_score(5, 0, 0)
        assert abs(factor.value - 0.5) < 0.01

    def test_dependencies_multiple_triggers(self):
        """Test dependency scoring with triggers."""
        factor = RiskScoringFormula.calculate_dependency_score(0, 3, 0)
        assert abs(factor.value - 0.3) < 0.01

    def test_dependencies_multiple_views(self):
        """Test dependency scoring with views."""
        factor = RiskScoringFormula.calculate_dependency_score(0, 0, 7)
        assert abs(factor.value - 0.7) < 0.01

    def test_dependencies_mixed(self):
        """Test dependency scoring with mixed dependencies."""
        factor = RiskScoringFormula.calculate_dependency_score(2, 3, 1)  # 6 total
        assert abs(factor.value - 0.6) < 0.01

    def test_dependencies_critical(self):
        """Test dependency scoring at critical threshold."""
        factor = RiskScoringFormula.calculate_dependency_score(5, 3, 2)  # 10 total
        assert factor.value == 1.0

    def test_dependencies_over_critical(self):
        """Test dependency scoring over critical threshold."""
        factor = RiskScoringFormula.calculate_dependency_score(7, 5, 3)  # 15 total
        assert factor.value == 1.0


class TestRiskScoringFormulaAnomalies:
    """Test risk scoring for anomalies."""

    def test_anomalies_none(self):
        """Test anomaly scoring with no anomalies."""
        factor = RiskScoringFormula.calculate_anomaly_score([])
        assert factor.value == 0.0
        assert factor.name == "anomalies"
        assert factor.weight == 0.15

    def test_anomalies_single_low(self):
        """Test anomaly scoring with single low severity."""
        anomalies = [DataAnomaly("issue1", Severity.LOW, "Minor issue")]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        assert abs(factor.value - 0.1) < 0.01

    def test_anomalies_single_medium(self):
        """Test anomaly scoring with single medium severity."""
        anomalies = [DataAnomaly("issue1", Severity.MEDIUM, "Medium issue")]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        assert abs(factor.value - 0.3) < 0.01

    def test_anomalies_single_high(self):
        """Test anomaly scoring with single high severity."""
        anomalies = [DataAnomaly("issue1", Severity.HIGH, "High issue")]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        assert abs(factor.value - 0.7) < 0.01

    def test_anomalies_single_critical(self):
        """Test anomaly scoring with single critical severity."""
        anomalies = [DataAnomaly("issue1", Severity.CRITICAL, "Critical issue")]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        assert abs(factor.value - 1.0) < 0.01

    def test_anomalies_multiple_mixed(self):
        """Test anomaly scoring with mixed severities."""
        anomalies = [
            DataAnomaly("issue1", Severity.LOW, "Low"),
            DataAnomaly("issue2", Severity.HIGH, "High"),
        ]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        # Average of 0.1 and 0.7 = 0.4
        assert abs(factor.value - 0.4) < 0.01

    def test_anomalies_all_critical(self):
        """Test anomaly scoring with all critical."""
        anomalies = [
            DataAnomaly("issue1", Severity.CRITICAL, "C1"),
            DataAnomaly("issue2", Severity.CRITICAL, "C2"),
        ]
        factor = RiskScoringFormula.calculate_anomaly_score(anomalies)
        assert abs(factor.value - 1.0) < 0.01


class TestRiskScoringFormulaConcurrentLoad:
    """Test risk scoring for concurrent load."""

    def test_concurrent_load_zero_connections(self):
        """Test concurrent load with zero active connections."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(0, 100)
        assert factor.value == 0.0
        assert factor.name == "concurrent_load"
        assert factor.weight == 0.10

    def test_concurrent_load_low_utilization(self):
        """Test concurrent load at 5% utilization."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(5, 100)
        assert factor.value == 0.0  # Below 10% threshold

    def test_concurrent_load_threshold(self):
        """Test concurrent load at 10% utilization (threshold)."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(10, 100)
        assert abs(factor.value - 0.0) < 0.01

    def test_concurrent_load_medium_utilization(self):
        """Test concurrent load at 50% utilization."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(50, 100)
        assert abs(factor.value - 0.444) < 0.05

    def test_concurrent_load_high_utilization(self):
        """Test concurrent load at 90% utilization."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(90, 100)
        assert abs(factor.value - 0.888) < 0.05

    def test_concurrent_load_critical_utilization(self):
        """Test concurrent load at 100% utilization."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(100, 100)
        assert factor.value == 1.0

    def test_concurrent_load_over_100_percent(self):
        """Test concurrent load over 100%."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(110, 100)
        assert factor.value == 1.0

    def test_concurrent_load_zero_max_connections(self):
        """Test concurrent load with zero max connections."""
        factor = RiskScoringFormula.calculate_concurrent_load_score(50, 0)
        assert factor.value == 0.0


class TestRiskScoringFormulaOverall:
    """Test overall risk calculation."""

    def test_overall_risk_no_factors(self):
        """Test overall risk with no factors."""
        level, score = RiskScoringFormula.calculate_overall_risk({})
        assert level == RiskLevel.LOW
        assert score == 0.0

    def test_overall_risk_single_low_factor(self):
        """Test overall risk with single low factor."""
        factor = RiskFactor("test", 0.2, "unit", 1.0, "Test factor")
        level, score = RiskScoringFormula.calculate_overall_risk({"test": factor})
        assert level == RiskLevel.LOW
        assert abs(score - 0.2) < 0.01

    def test_overall_risk_single_medium_factor(self):
        """Test overall risk with single medium factor."""
        factor = RiskFactor("test", 0.5, "unit", 1.0, "Test factor")
        level, score = RiskScoringFormula.calculate_overall_risk({"test": factor})
        assert level == RiskLevel.HIGH
        assert abs(score - 0.5) < 0.01

    def test_overall_risk_single_high_factor(self):
        """Test overall risk with single high factor."""
        factor = RiskFactor("test", 0.8, "unit", 1.0, "Test factor")
        level, score = RiskScoringFormula.calculate_overall_risk({"test": factor})
        assert level == RiskLevel.CRITICAL
        assert abs(score - 0.8) < 0.01

    def test_overall_risk_weighted_factors(self):
        """Test overall risk with weighted factors."""
        factors = {
            "factor1": RiskFactor("factor1", 0.5, "unit", 0.6, "Factor 1"),
            "factor2": RiskFactor("factor2", 1.0, "unit", 0.4, "Factor 2"),
        }
        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        # Weighted average: 0.5 * 0.6 + 1.0 * 0.4 = 0.3 + 0.4 = 0.7
        assert abs(score - 0.7) < 0.01
        assert level == RiskLevel.HIGH

    def test_overall_risk_all_factors(self):
        """Test overall risk with all available factors."""
        factors = {
            "data_volume": RiskFactor("data_volume", 0.2, "bytes", 0.25, "DV"),
            "lock_time": RiskFactor("lock_time", 0.4, "ms", 0.35, "LT"),
            "dependencies": RiskFactor("dependencies", 0.3, "count", 0.15, "Dep"),
            "anomalies": RiskFactor("anomalies", 0.5, "count", 0.15, "Anom"),
            "concurrent_load": RiskFactor("concurrent_load", 0.6, "%", 0.10, "Load"),
        }
        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        # Manual verification:
        # 0.2*0.25 + 0.4*0.35 + 0.3*0.15 + 0.5*0.15 + 0.6*0.10 = 0.05 + 0.14 + 0.045 + 0.075 + 0.06 = 0.365
        assert 0.3 < score < 0.4
        assert level == RiskLevel.MEDIUM

    def test_overall_risk_level_boundaries(self):
        """Test risk level thresholds."""
        # Test LOW boundary (< 0.25)
        factor_low = RiskFactor("test", 0.24, "unit", 1.0, "Low")
        level, _ = RiskScoringFormula.calculate_overall_risk({"test": factor_low})
        assert level == RiskLevel.LOW

        # Test MEDIUM boundary (0.25-0.49)
        factor_med = RiskFactor("test", 0.30, "unit", 1.0, "Medium")
        level, _ = RiskScoringFormula.calculate_overall_risk({"test": factor_med})
        assert level == RiskLevel.MEDIUM

        # Test HIGH boundary (0.50-0.74)
        factor_high = RiskFactor("test", 0.60, "unit", 1.0, "High")
        level, _ = RiskScoringFormula.calculate_overall_risk({"test": factor_high})
        assert level == RiskLevel.HIGH

        # Test CRITICAL boundary (>= 0.75)
        factor_crit = RiskFactor("test", 0.75, "unit", 1.0, "Critical")
        level, _ = RiskScoringFormula.calculate_overall_risk({"test": factor_crit})
        assert level == RiskLevel.CRITICAL

    def test_overall_risk_weight_normalization(self):
        """Test that weights are normalized when not all factors provided."""
        # Provide only 2 factors with custom weights
        factors = {
            "factor1": RiskFactor("factor1", 0.5, "unit", 0.3, "F1"),
            "factor2": RiskFactor("factor2", 1.0, "unit", 0.7, "F2"),
        }
        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        # Weights sum to 1.0, no normalization needed
        # 0.5 * (0.3/1.0) + 1.0 * (0.7/1.0) = 0.15 + 0.7 = 0.85
        assert abs(score - 0.85) < 0.01
        assert level == RiskLevel.CRITICAL


class TestRiskScoringIntegration:
    """Integration tests for risk scoring system."""

    def test_complete_risk_assessment_low_risk(self):
        """Test complete risk assessment for low-risk scenario."""
        # Small table, no lock time, no dependencies, no anomalies
        factors = {
            "data_volume": RiskScoringFormula.calculate_data_volume_score(100),
            "lock_time": RiskScoringFormula.calculate_lock_time_score(10),
            "dependencies": RiskScoringFormula.calculate_dependency_score(0, 0, 0),
            "anomalies": RiskScoringFormula.calculate_anomaly_score([]),
            "concurrent_load": RiskScoringFormula.calculate_concurrent_load_score(5, 100),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        assert level == RiskLevel.LOW
        assert score < 0.25

    def test_complete_risk_assessment_high_risk(self):
        """Test complete risk assessment for high-risk scenario."""
        # Large table, high lock time, many dependencies, anomalies present
        factors = {
            "data_volume": RiskScoringFormula.calculate_data_volume_score(100000),
            "lock_time": RiskScoringFormula.calculate_lock_time_score(5000),
            "dependencies": RiskScoringFormula.calculate_dependency_score(3, 2, 1),
            "anomalies": RiskScoringFormula.calculate_anomaly_score([
                DataAnomaly("issue1", Severity.HIGH, "Issue 1")
            ]),
            "concurrent_load": RiskScoringFormula.calculate_concurrent_load_score(80, 100),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        assert level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert score > 0.5

    def test_complete_risk_assessment_critical_risk(self):
        """Test complete risk assessment for critical-risk scenario."""
        # Very large table, very high lock time, many dependencies, critical anomalies
        factors = {
            "data_volume": RiskScoringFormula.calculate_data_volume_score(1024 * 1024),
            "lock_time": RiskScoringFormula.calculate_lock_time_score(20000),
            "dependencies": RiskScoringFormula.calculate_dependency_score(5, 4, 3),
            "anomalies": RiskScoringFormula.calculate_anomaly_score([
                DataAnomaly("data_loss", Severity.CRITICAL, "Critical issue")
            ]),
            "concurrent_load": RiskScoringFormula.calculate_concurrent_load_score(95, 100),
        }

        level, score = RiskScoringFormula.calculate_overall_risk(factors)
        assert level == RiskLevel.CRITICAL
        assert score >= 0.75

    def test_risk_factors_have_consistent_weights(self):
        """Test that all scoring methods return factors with expected weights."""
        all_factors = [
            RiskScoringFormula.calculate_data_volume_score(100),
            RiskScoringFormula.calculate_lock_time_score(100),
            RiskScoringFormula.calculate_dependency_score(2, 1, 1),
            RiskScoringFormula.calculate_anomaly_score([]),
            RiskScoringFormula.calculate_concurrent_load_score(50, 100),
        ]

        expected_weights = [0.25, 0.35, 0.15, 0.15, 0.10]
        for factor, expected_weight in zip(all_factors, expected_weights, strict=True):
            assert factor.weight == expected_weight
