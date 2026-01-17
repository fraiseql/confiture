"""Downtime prediction with confidence bounds."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MigrationOperation:
    """Represents a migration operation."""

    id: str
    type: str  # "ADD_COLUMN", "ALTER_TYPE", etc.
    table_size_mb: int
    table_name: str


@dataclass
class HistoricalMigration:
    """Historical migration record."""

    operation_type: str
    table_size_mb: int
    actual_downtime_ms: int
    recorded_at: str = ""


@dataclass
class DowntimeEstimate:
    """Downtime estimate with explicit uncertainty."""

    estimated_downtime_ms: int  # Point estimate
    lower_bound_ms: int  # 80% confidence lower
    upper_bound_ms: int  # 80% confidence upper
    confidence_level: float  # 0.0-1.0
    estimate_method: str  # "heuristic", "historical"
    contributing_factors: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)


class HistoricalMigrations:
    """Manage historical migration data."""

    def __init__(self):
        self.migrations: list[HistoricalMigration] = []

    def add(self, migration: HistoricalMigration) -> None:
        """Add migration record."""
        self.migrations.append(migration)

    def find_similar(
        self,
        table_size_mb: int,
        operation_type: str,
        max_results: int = 10,
    ) -> list[HistoricalMigration]:
        """Find similar past migrations."""
        similar = [
            m
            for m in self.migrations
            if m.operation_type == operation_type
            and abs(m.table_size_mb - table_size_mb) / max(table_size_mb, 1) < 0.2
        ]
        return similar[:max_results]


class DowntimePredictor:
    """Predict migration downtime with confidence."""

    def __init__(self, historical_data: HistoricalMigrations | None = None):
        self.historical_data = historical_data
        self.prediction_method = "historical" if historical_data else "heuristic"

    async def predict_downtime(
        self,
        operation: MigrationOperation,
    ) -> DowntimeEstimate:
        """Predict downtime with confidence intervals."""

        if self.prediction_method == "historical":
            return await self._predict_from_history(operation)
        else:
            return await self._predict_heuristic(operation)

    async def _predict_from_history(
        self,
        operation: MigrationOperation,
    ) -> DowntimeEstimate:
        """Use historical data to predict downtime."""

        # Find similar past migrations
        similar = self.historical_data.find_similar(
            table_size_mb=operation.table_size_mb,
            operation_type=operation.type,
            max_results=10,
        )

        if not similar:
            # Fall back to heuristic
            return await self._predict_heuristic(operation)

        actual_downtimes = [m.actual_downtime_ms for m in similar]

        mean = statistics.mean(actual_downtimes)
        stdev = statistics.stdev(actual_downtimes) if len(actual_downtimes) > 1 else 0

        return DowntimeEstimate(
            estimated_downtime_ms=int(mean),
            lower_bound_ms=max(0, int(mean - 2 * stdev)),
            upper_bound_ms=int(mean + 2 * stdev),
            confidence_level=1.0 - (stdev / mean) if mean > 0 else 0.5,
            estimate_method="historical",
            contributing_factors={
                "similar_migrations": len(similar),
                "average_actual_downtime_ms": int(mean),
                "std_deviation_ms": int(stdev),
            },
            caveats=[
                f"Based on {len(similar)} similar migrations",
                f"Standard deviation: {stdev:.0f}ms",
                "System load on current date may differ",
                "Database statistics may have changed",
            ],
        )

    async def _predict_heuristic(
        self,
        operation: MigrationOperation,
    ) -> DowntimeEstimate:
        """Heuristic prediction (no historical data)."""

        # Base times in milliseconds
        base_time_ms = {
            "ADD_COLUMN": 100,
            "DROP_COLUMN": 100,
            "RENAME_COLUMN": 50,
            "ALTER_TYPE": 500,
            "ADD_INDEX": 50,
            "DROP_INDEX": 20,
            "ADD_CONSTRAINT": 200,
            "DROP_CONSTRAINT": 50,
        }.get(operation.type, 100)

        # Adjust by table size (size in GB)
        size_gb = operation.table_size_mb / 1024

        # Different operation types scale differently
        if operation.type == "ALTER_TYPE":
            # Full table rewrite - 2ms per GB
            size_adjustment = int(size_gb * 2000)
        elif operation.type == "ADD_INDEX":
            # Index build - 0.5ms per GB
            size_adjustment = int(size_gb * 500)
        else:
            # Most operations - 1ms per GB
            size_adjustment = int(size_gb * 1000)

        estimated = base_time_ms + size_adjustment

        # High uncertainty for heuristic
        return DowntimeEstimate(
            estimated_downtime_ms=estimated,
            lower_bound_ms=max(0, int(estimated * 0.5)),  # -50%
            upper_bound_ms=int(estimated * 2.0),  # +100%
            confidence_level=0.3,  # Low confidence (heuristic only)
            estimate_method="heuristic",
            contributing_factors={
                "base_time_ms": base_time_ms,
                "size_adjustment_ms": size_adjustment,
                "table_size_mb": operation.table_size_mb,
            },
            caveats=[
                "⚠️ HEURISTIC ESTIMATE - Low confidence (0.3/1.0)",
                "No historical data available for calibration",
                "Actual downtime depends on:",
                "  - System load and concurrent queries",
                "  - Database configuration (work_mem, etc.)",
                "  - Lock contention from other operations",
                "  - Hardware capabilities (SSD vs HDD)",
                "RECOMMENDATION: Record actual downtime to improve predictions",
                "Next prediction will be more accurate if historical data collected",
            ],
        )
