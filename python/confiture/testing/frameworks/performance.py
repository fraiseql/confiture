"""Performance profiling system for database migrations.

Provides detailed performance metrics and regression detection for migrations.

Architecture:
- MigrationPerformanceProfiler: Profiles migration execution with detailed metrics
- PerformanceProfile: Detailed metrics for a single migration
- PerformanceBaseline: Reference metrics for regression detection
- PerformanceOptimizationReport: Bottleneck identification and recommendations
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psycopg


@dataclass
class OperationMetrics:
    """Metrics for a single operation."""
    name: str                          # Operation name (e.g., "ALTER TABLE")
    start_time: float                  # Timestamp when operation started
    end_time: float                    # Timestamp when operation ended
    duration_seconds: float            # Total duration in seconds
    percent_of_total: float            # Percentage of migration time
    memory_before_mb: float | None  # Memory before operation (if tracked)
    memory_after_mb: float | None   # Memory after operation (if tracked)
    io_operations: int | None       # Number of I/O operations (if tracked)

    @property
    def memory_delta_mb(self) -> float | None:
        """Calculate memory change during operation."""
        if self.memory_before_mb is not None and self.memory_after_mb is not None:
            return self.memory_after_mb - self.memory_before_mb
        return None


@dataclass
class PerformanceProfile:
    """Performance profile for a migration execution."""
    migration_name: str
    start_timestamp: float
    end_timestamp: float
    total_duration_seconds: float

    operations: dict[str, OperationMetrics] = field(default_factory=dict)
    memory_peak_mb: float | None = None
    cpu_avg_percent: float | None = None
    total_io_operations: int | None = None

    def get_bottlenecks(self, threshold: float = 0.05) -> list[OperationMetrics]:
        """Get operations consuming more than threshold of total time.

        Args:
            threshold: Percentage threshold (e.g., 0.05 for 5%)

        Returns:
            List of bottleneck operations sorted by duration descending
        """
        bottlenecks = [
            op for op in self.operations.values()
            if op.percent_of_total >= (threshold * 100)
        ]
        return sorted(bottlenecks, key=lambda x: x.duration_seconds, reverse=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary for JSON serialization."""
        return {
            "migration_name": self.migration_name,
            "total_duration_seconds": self.total_duration_seconds,
            "memory_peak_mb": self.memory_peak_mb,
            "cpu_avg_percent": self.cpu_avg_percent,
            "total_io_operations": self.total_io_operations,
            "operations": [asdict(op) for op in self.operations.values()],
        }


@dataclass
class RegressionReport:
    """Report of performance regressions detected."""
    migration_name: str
    regressions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        """Whether any regressions were detected."""
        return len(self.regressions) > 0

    @property
    def worst_regression_pct(self) -> float:
        """Worst regression percentage if any."""
        if not self.regressions:
            return 0.0
        return max(r["regression_pct"] for r in self.regressions)


@dataclass
class PerformanceOptimizationRecommendation:
    """A recommendation for performance optimization."""
    operation: str
    current_duration_seconds: float
    percent_of_total: float
    severity: str  # "CRITICAL", "IMPORTANT", "MINOR"
    recommendation: str
    potential_speedup: str  # e.g., "2-3x"


@dataclass
class PerformanceOptimizationReport:
    """Report with optimization recommendations."""
    migration_name: str
    bottlenecks: list[OperationMetrics]
    recommendations: list[PerformanceOptimizationRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "migration_name": self.migration_name,
            "bottleneck_count": len(self.bottlenecks),
            "recommendations": [asdict(r) for r in self.recommendations],
        }


class MigrationPerformanceProfiler:
    """Profile database migration performance."""

    def __init__(self, db_connection: psycopg.Connection):
        self.connection = db_connection
        self.current_profile: PerformanceProfile | None = None
        self.section_stack: list[tuple[str, float]] = []

    def profile_migration(self, migration_name: str, execute_fn) -> PerformanceProfile:
        """Profile migration execution.

        Args:
            migration_name: Name of the migration
            execute_fn: Function to execute (receives profiler as argument)

        Returns:
            PerformanceProfile with detailed metrics
        """
        start_time = time.time()

        self.current_profile = PerformanceProfile(
            migration_name=migration_name,
            start_timestamp=start_time,
            end_timestamp=0.0,
            total_duration_seconds=0.0,
        )

        try:
            # Execute migration with profiling
            execute_fn(self)
        finally:
            end_time = time.time()
            self.current_profile.end_timestamp = end_time
            self.current_profile.total_duration_seconds = end_time - start_time

            # Finalize operation metrics
            self._finalize_operations()

        return self.current_profile

    def track_section(self, section_name: str):
        """Context manager for tracking operation duration.

        Usage:
            with profiler.track_section("operation_name"):
                # Do work
                pass
        """
        return _SectionTracker(self, section_name)

    def record_operation(
        self,
        name: str,
        duration_seconds: float,
        memory_before_mb: float | None = None,
        memory_after_mb: float | None = None,
        io_operations: int | None = None,
    ):
        """Record an operation's metrics.

        Args:
            name: Operation name
            duration_seconds: Operation duration
            memory_before_mb: Memory before (optional)
            memory_after_mb: Memory after (optional)
            io_operations: Number of I/O ops (optional)
        """
        if self.current_profile is None:
            return

        metrics = OperationMetrics(
            name=name,
            start_time=time.time(),
            end_time=time.time() + duration_seconds,
            duration_seconds=duration_seconds,
            percent_of_total=0.0,  # Will be calculated later
            memory_before_mb=memory_before_mb,
            memory_after_mb=memory_after_mb,
            io_operations=io_operations,
        )

        self.current_profile.operations[name] = metrics

    def _finalize_operations(self):
        """Calculate percentages and finalize operation metrics."""
        if self.current_profile is None:
            return

        total = self.current_profile.total_duration_seconds
        if total <= 0:
            return

        for operation in self.current_profile.operations.values():
            operation.percent_of_total = (operation.duration_seconds / total) * 100

    def get_profile(self) -> PerformanceProfile | None:
        """Get current profile."""
        return self.current_profile


class _SectionTracker:
    """Context manager for tracking operation sections."""

    def __init__(self, profiler: MigrationPerformanceProfiler, section_name: str):
        self.profiler = profiler
        self.section_name = section_name
        self.start_time = 0.0
        self.memory_before_mb: float | None = None
        self.memory_after_mb: float | None = None

    def __enter__(self):
        self.start_time = time.time()
        self.memory_before_mb = self._get_memory_usage_mb()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.time()
        duration = end_time - self.start_time
        self.memory_after_mb = self._get_memory_usage_mb()

        self.profiler.record_operation(
            name=self.section_name,
            duration_seconds=duration,
            memory_before_mb=self.memory_before_mb,
            memory_after_mb=self.memory_after_mb,
        )

    def _get_memory_usage_mb(self) -> float | None:
        """Get current memory usage (best effort)."""
        try:
            import psutil  # type: ignore[import-untyped]
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return None


class PerformanceBaseline:
    """Baseline performance metrics for regression detection."""

    def __init__(self, baselines_file: Path):
        self.baselines_file = baselines_file
        self.baselines: dict[str, dict[str, Any]] = {}
        self._load_baselines()

    def _load_baselines(self):
        """Load baseline metrics from file."""
        if self.baselines_file.exists():
            with open(self.baselines_file) as f:
                data = json.load(f)
                self.baselines = data.get("baselines", {})

    def save_baselines(self):
        """Save baseline metrics to file."""
        data = {"baselines": self.baselines}
        self.baselines_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.baselines_file, "w") as f:
            json.dump(data, f, indent=2)

    def set_baseline(self, migration_name: str, profile: PerformanceProfile):
        """Set baseline for a migration."""
        self.baselines[migration_name] = {
            "total_duration_seconds": profile.total_duration_seconds,
            "memory_peak_mb": profile.memory_peak_mb or 0.0,
            "operations": {
                name: op.duration_seconds
                for name, op in profile.operations.items()
            },
        }

    def detect_regression(
        self,
        current_profile: PerformanceProfile,
        threshold_pct: float = 20.0,
    ) -> RegressionReport:
        """Detect performance regressions.

        Args:
            current_profile: Current performance profile
            threshold_pct: Regression threshold percentage (default 20%)

        Returns:
            RegressionReport with detected regressions
        """
        report = RegressionReport(migration_name=current_profile.migration_name)

        baseline = self.baselines.get(current_profile.migration_name)
        if not baseline:
            # No baseline to compare against
            return report

        # Check total duration regression
        baseline_total = baseline["total_duration_seconds"]
        current_total = current_profile.total_duration_seconds

        if current_total > baseline_total * (1.0 + threshold_pct / 100.0):
            regression_pct = ((current_total / baseline_total) - 1.0) * 100
            report.regressions.append({
                "type": "total_duration",
                "operation": "Overall migration",
                "baseline": baseline_total,
                "current": current_total,
                "regression_pct": regression_pct,
            })

        # Check individual operation regressions
        baseline_ops = baseline.get("operations", {})
        for op_name, current_duration in current_profile.operations.items():
            baseline_duration = baseline_ops.get(op_name)
            if baseline_duration is None:
                continue

            if current_duration.duration_seconds > baseline_duration * (
                1.0 + threshold_pct / 100.0
            ):
                regression_pct = (
                    (current_duration.duration_seconds / baseline_duration) - 1.0
                ) * 100
                report.regressions.append({
                    "type": "operation_duration",
                    "operation": op_name,
                    "baseline": baseline_duration,
                    "current": current_duration.duration_seconds,
                    "regression_pct": regression_pct,
                })

        return report

    def generate_optimization_report(
        self,
        profile: PerformanceProfile,
    ) -> PerformanceOptimizationReport:
        """Generate optimization recommendations based on profile.

        Args:
            profile: Performance profile to analyze

        Returns:
            PerformanceOptimizationReport with recommendations
        """
        bottlenecks = profile.get_bottlenecks(threshold=0.05)
        report = PerformanceOptimizationReport(
            migration_name=profile.migration_name,
            bottlenecks=bottlenecks,
        )

        # Generate recommendations for each bottleneck
        for bottleneck in bottlenecks:
            recommendation = self._generate_recommendation(bottleneck, profile)
            if recommendation:
                report.recommendations.append(recommendation)

        return report

    def _generate_recommendation(
        self,
        bottleneck: OperationMetrics,
        _profile: PerformanceProfile,
    ) -> PerformanceOptimizationRecommendation | None:
        """Generate optimization recommendation for a bottleneck."""
        operation_type = self._extract_operation_type(bottleneck.name)

        if operation_type == "UPDATE" and bottleneck.duration_seconds > 0.01:
            return PerformanceOptimizationRecommendation(
                operation=bottleneck.name,
                current_duration_seconds=bottleneck.duration_seconds,
                percent_of_total=bottleneck.percent_of_total,
                severity="CRITICAL" if bottleneck.percent_of_total > 50 else "IMPORTANT",
                recommendation=(
                    "UPDATE operation is slow. Consider:\n"
                    "  - Use bulk update with WHERE clause\n"
                    "  - Add index on filter columns\n"
                    "  - Batch processing with LIMIT\n"
                    "  - Analyze query plan with EXPLAIN"
                ),
                potential_speedup="2-5x",
            )

        elif operation_type == "INSERT" and bottleneck.duration_seconds > 0.01:
            return PerformanceOptimizationRecommendation(
                operation=bottleneck.name,
                current_duration_seconds=bottleneck.duration_seconds,
                percent_of_total=bottleneck.percent_of_total,
                severity="IMPORTANT",
                recommendation=(
                    "INSERT operation is slow. Consider:\n"
                    "  - Use COPY command for bulk insert\n"
                    "  - Disable triggers during insert\n"
                    "  - Increase work_mem for sort operations\n"
                    "  - Batch insert in smaller chunks"
                ),
                potential_speedup="3-10x",
            )

        elif operation_type == "INDEX" and bottleneck.duration_seconds > 0.01:
            return PerformanceOptimizationRecommendation(
                operation=bottleneck.name,
                current_duration_seconds=bottleneck.duration_seconds,
                percent_of_total=bottleneck.percent_of_total,
                severity="IMPORTANT",
                recommendation=(
                    "Index creation is slow. Consider:\n"
                    "  - Create index CONCURRENTLY\n"
                    "  - Use FILLFACTOR for indexes on volatile tables\n"
                    "  - Create in parallel on replicas first\n"
                    "  - Consider partial index if possible"
                ),
                potential_speedup="1.5-3x",
            )

        return None

    def _extract_operation_type(self, operation_name: str) -> str:
        """Extract operation type from operation name."""
        name_upper = operation_name.upper()

        for op_type in ["UPDATE", "INSERT", "DELETE", "ALTER", "CREATE", "INDEX"]:
            if op_type in name_upper:
                return op_type

        return "UNKNOWN"

    def export_baseline(self, path: Path):
        """Export baselines to file."""
        data = {"baselines": self.baselines}
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def export_comparison(self, profile: PerformanceProfile, path: Path):
        """Export comparison with baseline."""
        regression = self.detect_regression(profile)
        optimization = self.generate_optimization_report(profile)

        comparison = {
            "migration": profile.migration_name,
            "profile": profile.to_dict(),
            "regression": {
                "has_regressions": regression.has_regressions,
                "regressions": regression.regressions,
            },
            "optimization": optimization.to_dict(),
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(comparison, f, indent=2)
