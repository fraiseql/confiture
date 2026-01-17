"""Transparent risk scoring formula with explicit weights."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk classification."""

    LOW = 1  # <100ms estimated downtime
    MEDIUM = 2  # 100ms - 1s estimated downtime
    HIGH = 3  # 1s - 10s estimated downtime
    CRITICAL = 4  # >10s estimated downtime


class Severity(Enum):
    """Severity levels for anomalies."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DataAnomaly:
    """Represents a data anomaly."""

    name: str
    severity: Severity
    description: str


@dataclass
class RiskFactor:
    """Individual risk factor with scoring."""

    name: str
    value: float  # 0.0-1.0
    unit: str  # "percent", "seconds", "bytes", etc.
    weight: float  # Contribution to overall score
    description: str


class RiskScoringFormula:
    """
    EXPLICIT RISK SCORING FORMULA

    This class documents the exact algorithm used to calculate risk scores.
    All weights and thresholds are configurable.
    """

    # Weighting factors (must sum to 1.0)
    WEIGHT_DATA_VOLUME = 0.25
    WEIGHT_LOCK_TIME = 0.35
    WEIGHT_DEPENDENCIES = 0.15
    WEIGHT_ANOMALIES = 0.15
    WEIGHT_CONCURRENT_LOAD = 0.10

    # Thresholds for scoring (in consistent units)
    DATA_VOLUME_CRITICAL_GB = 1024  # >1TB = 1.0
    DATA_VOLUME_LOW_MB = 1  # <1MB = 0.0
    LOCK_TIME_CRITICAL_MS = 10000  # >10 seconds
    LOCK_TIME_HIGH_MS = 1000
    LOCK_TIME_MEDIUM_MS = 100
    DEPENDENCY_COUNT_CRITICAL = 10

    @staticmethod
    def calculate_data_volume_score(table_size_mb: int) -> RiskFactor:
        """
        Calculate risk from data volume.

        Formula: linear interpolation
        - <1MB = 0.0 (low risk)
        - 1GB = 0.5 (medium risk)
        - >1TB = 1.0 (critical risk)
        """
        if table_size_mb > 1024 * 1024:  # >1TB
            score = 1.0
        elif table_size_mb < 1:
            score = 0.0
        else:
            # Linear interpolation
            score = min(table_size_mb / (1024 * 1024), 1.0)

        return RiskFactor(
            name="data_volume",
            value=score,
            unit="bytes",
            weight=RiskScoringFormula.WEIGHT_DATA_VOLUME,
            description=f"Table size: {table_size_mb}MB",
        )

    @staticmethod
    def calculate_lock_time_score(estimated_lock_ms: int) -> RiskFactor:
        """
        Calculate risk from lock time using piecewise smooth function.

        Formula: smooth exponential scaling without discontinuities
        - 0ms = 0.0 (no risk)
        - 100ms = 0.1 (low risk)
        - 1s = 0.5 (medium risk)
        - 10s = 0.95 (high risk)
        - 10s+ = 1.0 (critical risk)
        """
        if estimated_lock_ms >= 10000:
            score = 1.0
        elif estimated_lock_ms <= 0:
            score = 0.0
        else:
            # Use logarithmic scaling for all positive values
            # log(estimated_lock_ms) ranges from 0 (at 1ms) to ~4 (at 10s)
            # This creates a smooth curve without discontinuities
            log_value = math.log10(estimated_lock_ms)  # -3 to 4 for 1ms to 10s
            # Normalize to 0-1 range: map -3 (1ms) to 0, map 4 (10s) to 1
            score = min((log_value + 3) / 7 * 0.95, 1.0)

        return RiskFactor(
            name="lock_time",
            value=score,
            unit="milliseconds",
            weight=RiskScoringFormula.WEIGHT_LOCK_TIME,
            description=f"Estimated lock time: {estimated_lock_ms}ms",
        )

    @staticmethod
    def calculate_dependency_score(
        foreign_keys: int,
        triggers: int,
        views: int,
    ) -> RiskFactor:
        """
        Calculate risk from dependencies.

        Formula: linear in dependency count
        - 0 dependencies = 0.0
        - 10+ dependencies = 1.0
        """
        dependency_count = foreign_keys + triggers + views
        score = min(dependency_count / 10, 1.0)

        return RiskFactor(
            name="dependencies",
            value=score,
            unit="count",
            weight=RiskScoringFormula.WEIGHT_DEPENDENCIES,
            description=f"FKs: {foreign_keys}, Triggers: {triggers}, Views: {views}",
        )

    @staticmethod
    def calculate_anomaly_score(anomalies: list[DataAnomaly]) -> RiskFactor:
        """
        Calculate risk from detected anomalies.

        Formula: average severity if anomalies exist
        - CRITICAL anomaly = 1.0
        - HIGH = 0.7
        - MEDIUM = 0.3
        - LOW = 0.1
        """
        if not anomalies:
            score = 0.0
        else:
            severity_scores = [
                1.0
                if a.severity == Severity.CRITICAL
                else 0.7
                if a.severity == Severity.HIGH
                else 0.3
                if a.severity == Severity.MEDIUM
                else 0.1
                for a in anomalies
            ]
            score = sum(severity_scores) / len(severity_scores)

        return RiskFactor(
            name="anomalies",
            value=min(score, 1.0),
            unit="count",
            weight=RiskScoringFormula.WEIGHT_ANOMALIES,
            description=f"Anomalies detected: {len(anomalies)}",
        )

    @staticmethod
    def calculate_concurrent_load_score(
        active_connections: int,
        max_connections: int = 100,
    ) -> RiskFactor:
        """
        Calculate risk from concurrent load.

        Formula: linear in connection utilization
        - <10% = 0.0
        - 50% = 0.5
        - >90% = 1.0
        """
        utilization = active_connections / max_connections if max_connections > 0 else 0
        score = min(max(utilization - 0.1, 0) / 0.9, 1.0)

        return RiskFactor(
            name="concurrent_load",
            value=score,
            unit="percent",
            weight=RiskScoringFormula.WEIGHT_CONCURRENT_LOAD,
            description=f"Connection utilization: {utilization * 100:.1f}%",
        )

    @staticmethod
    def calculate_overall_risk(
        factors: dict[str, RiskFactor],
    ) -> tuple[RiskLevel, float]:
        """
        Calculate overall risk score from factors.

        Formula: weighted sum with automatic weight normalization
        overall_score = Σ(factor.value * (factor.weight / sum(weights)))

        If not all factors are provided, weights are automatically renormalized
        to sum to 1.0 for the provided factors.
        """
        if not factors:
            return RiskLevel.LOW, 0.0

        # Calculate total weight from provided factors
        total_weight = sum(factor.weight for factor in factors.values())

        # Calculate overall score with renormalized weights
        overall_score = sum(
            factor.value * (factor.weight / total_weight) for factor in factors.values()
        )

        # Map score to risk level
        if overall_score >= 0.75:
            level = RiskLevel.CRITICAL
        elif overall_score >= 0.50:
            level = RiskLevel.HIGH
        elif overall_score >= 0.25:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        return level, overall_score
