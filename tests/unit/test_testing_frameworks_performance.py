"""Unit tests for confiture.testing.frameworks.performance module.

Tests cover:
- OperationMetrics dataclass and properties
- PerformanceProfile methods and bottleneck detection
- RegressionReport properties
- PerformanceOptimizationRecommendation and Report
- MigrationPerformanceProfiler execution and tracking
- _SectionTracker context manager
- PerformanceBaseline loading, saving, and regression detection
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from confiture.testing.frameworks.performance import (
    MigrationPerformanceProfiler,
    OperationMetrics,
    PerformanceBaseline,
    PerformanceOptimizationRecommendation,
    PerformanceOptimizationReport,
    PerformanceProfile,
    RegressionReport,
    _SectionTracker,
)


class TestOperationMetrics:
    """Test OperationMetrics dataclass."""

    def test_creation(self):
        """Test creating OperationMetrics."""
        metrics = OperationMetrics(
            name="CREATE TABLE",
            start_time=100.0,
            end_time=100.5,
            duration_seconds=0.5,
            percent_of_total=25.0,
            memory_before_mb=100.0,
            memory_after_mb=110.0,
            io_operations=50,
        )

        assert metrics.name == "CREATE TABLE"
        assert metrics.duration_seconds == 0.5
        assert metrics.percent_of_total == 25.0

    def test_memory_delta_with_values(self):
        """Test memory_delta_mb property with valid values."""
        metrics = OperationMetrics(
            name="test",
            start_time=0.0,
            end_time=1.0,
            duration_seconds=1.0,
            percent_of_total=100.0,
            memory_before_mb=100.0,
            memory_after_mb=150.0,
            io_operations=None,
        )

        assert metrics.memory_delta_mb == 50.0

    def test_memory_delta_with_none_before(self):
        """Test memory_delta_mb when memory_before is None."""
        metrics = OperationMetrics(
            name="test",
            start_time=0.0,
            end_time=1.0,
            duration_seconds=1.0,
            percent_of_total=100.0,
            memory_before_mb=None,
            memory_after_mb=150.0,
            io_operations=None,
        )

        assert metrics.memory_delta_mb is None

    def test_memory_delta_with_none_after(self):
        """Test memory_delta_mb when memory_after is None."""
        metrics = OperationMetrics(
            name="test",
            start_time=0.0,
            end_time=1.0,
            duration_seconds=1.0,
            percent_of_total=100.0,
            memory_before_mb=100.0,
            memory_after_mb=None,
            io_operations=None,
        )

        assert metrics.memory_delta_mb is None


class TestPerformanceProfile:
    """Test PerformanceProfile dataclass and methods."""

    def test_creation(self):
        """Test creating PerformanceProfile."""
        profile = PerformanceProfile(
            migration_name="001_create_users",
            start_timestamp=1000.0,
            end_timestamp=1005.0,
            total_duration_seconds=5.0,
        )

        assert profile.migration_name == "001_create_users"
        assert profile.total_duration_seconds == 5.0

    def test_get_bottlenecks_empty(self):
        """Test get_bottlenecks with no operations."""
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        bottlenecks = profile.get_bottlenecks()
        assert bottlenecks == []

    def test_get_bottlenecks_filters_by_threshold(self):
        """Test get_bottlenecks filters operations below threshold."""
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        # Add operations with varying percentages
        profile.operations["fast_op"] = OperationMetrics(
            name="fast_op",
            start_time=0.0,
            end_time=0.01,
            duration_seconds=0.01,
            percent_of_total=1.0,  # 1% - below threshold
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile.operations["slow_op"] = OperationMetrics(
            name="slow_op",
            start_time=0.01,
            end_time=0.61,
            duration_seconds=0.6,
            percent_of_total=60.0,  # 60% - above threshold
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile.operations["medium_op"] = OperationMetrics(
            name="medium_op",
            start_time=0.61,
            end_time=0.81,
            duration_seconds=0.2,
            percent_of_total=20.0,  # 20% - above threshold
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )

        # Default threshold is 5%
        bottlenecks = profile.get_bottlenecks(threshold=0.05)

        assert len(bottlenecks) == 2
        # Should be sorted by duration descending
        assert bottlenecks[0].name == "slow_op"
        assert bottlenecks[1].name == "medium_op"

    def test_to_dict(self):
        """Test to_dict method."""
        profile = PerformanceProfile(
            migration_name="test_migration",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
            memory_peak_mb=256.0,
            cpu_avg_percent=50.0,
            total_io_operations=100,
        )

        profile.operations["op1"] = OperationMetrics(
            name="op1",
            start_time=0.0,
            end_time=0.5,
            duration_seconds=0.5,
            percent_of_total=50.0,
            memory_before_mb=100.0,
            memory_after_mb=150.0,
            io_operations=25,
        )

        result = profile.to_dict()

        assert result["migration_name"] == "test_migration"
        assert result["total_duration_seconds"] == 1.0
        assert result["memory_peak_mb"] == 256.0
        assert result["cpu_avg_percent"] == 50.0
        assert result["total_io_operations"] == 100
        assert len(result["operations"]) == 1
        assert result["operations"][0]["name"] == "op1"


class TestRegressionReport:
    """Test RegressionReport dataclass."""

    def test_has_regressions_false(self):
        """Test has_regressions when no regressions."""
        report = RegressionReport(migration_name="test")
        assert report.has_regressions is False

    def test_has_regressions_true(self):
        """Test has_regressions when regressions exist."""
        report = RegressionReport(migration_name="test")
        report.regressions.append({"regression_pct": 50.0})
        assert report.has_regressions is True

    def test_worst_regression_pct_empty(self):
        """Test worst_regression_pct with no regressions."""
        report = RegressionReport(migration_name="test")
        assert report.worst_regression_pct == 0.0

    def test_worst_regression_pct_multiple(self):
        """Test worst_regression_pct with multiple regressions."""
        report = RegressionReport(migration_name="test")
        report.regressions.append({"regression_pct": 25.0})
        report.regressions.append({"regression_pct": 75.0})
        report.regressions.append({"regression_pct": 50.0})
        assert report.worst_regression_pct == 75.0


class TestPerformanceOptimizationReport:
    """Test PerformanceOptimizationReport."""

    def test_to_dict(self):
        """Test to_dict method."""
        bottleneck = OperationMetrics(
            name="slow_op",
            start_time=0.0,
            end_time=1.0,
            duration_seconds=1.0,
            percent_of_total=80.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )

        recommendation = PerformanceOptimizationRecommendation(
            operation="slow_op",
            current_duration_seconds=1.0,
            percent_of_total=80.0,
            severity="CRITICAL",
            recommendation="Optimize this operation",
            potential_speedup="2-3x",
        )

        report = PerformanceOptimizationReport(
            migration_name="test",
            bottlenecks=[bottleneck],
            recommendations=[recommendation],
        )

        result = report.to_dict()

        assert result["migration_name"] == "test"
        assert result["bottleneck_count"] == 1
        assert len(result["recommendations"]) == 1
        assert result["recommendations"][0]["severity"] == "CRITICAL"


class TestMigrationPerformanceProfiler:
    """Test MigrationPerformanceProfiler."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock database connection."""
        return MagicMock()

    def test_init(self, mock_connection):
        """Test profiler initialization."""
        profiler = MigrationPerformanceProfiler(mock_connection)

        assert profiler.connection is mock_connection
        assert profiler.current_profile is None
        assert profiler.section_stack == []

    def test_profile_migration(self, mock_connection):
        """Test profile_migration method."""
        profiler = MigrationPerformanceProfiler(mock_connection)

        def execute_fn(p):
            time.sleep(0.01)

        profile = profiler.profile_migration("test_migration", execute_fn)

        assert profile.migration_name == "test_migration"
        assert profile.total_duration_seconds >= 0.01
        assert profile.start_timestamp > 0
        assert profile.end_timestamp > profile.start_timestamp

    def test_profile_migration_with_operations(self, mock_connection):
        """Test profile_migration records operations."""
        profiler = MigrationPerformanceProfiler(mock_connection)

        def execute_fn(p):
            p.record_operation("op1", 0.1)
            p.record_operation("op2", 0.2)

        profile = profiler.profile_migration("test", execute_fn)

        assert len(profile.operations) == 2
        assert "op1" in profile.operations
        assert "op2" in profile.operations

    def test_track_section_context_manager(self, mock_connection):
        """Test track_section returns context manager."""
        profiler = MigrationPerformanceProfiler(mock_connection)
        profiler.current_profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=time.time(),
            end_timestamp=0.0,
            total_duration_seconds=0.0,
        )

        with profiler.track_section("test_section"):
            time.sleep(0.01)

        assert "test_section" in profiler.current_profile.operations
        assert profiler.current_profile.operations["test_section"].duration_seconds >= 0.01

    def test_record_operation_with_memory(self, mock_connection):
        """Test record_operation with memory tracking."""
        profiler = MigrationPerformanceProfiler(mock_connection)
        profiler.current_profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=time.time(),
            end_timestamp=0.0,
            total_duration_seconds=0.0,
        )

        profiler.record_operation(
            name="mem_op",
            duration_seconds=0.5,
            memory_before_mb=100.0,
            memory_after_mb=150.0,
            io_operations=25,
        )

        op = profiler.current_profile.operations["mem_op"]
        assert op.memory_before_mb == 100.0
        assert op.memory_after_mb == 150.0
        assert op.io_operations == 25

    def test_record_operation_no_profile(self, mock_connection):
        """Test record_operation when no profile active."""
        profiler = MigrationPerformanceProfiler(mock_connection)

        # Should not raise error
        profiler.record_operation("op1", 0.1)

    def test_get_profile(self, mock_connection):
        """Test get_profile method."""
        profiler = MigrationPerformanceProfiler(mock_connection)
        assert profiler.get_profile() is None

        profiler.current_profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )
        assert profiler.get_profile() is not None

    def test_finalize_operations_calculates_percentages(self, mock_connection):
        """Test _finalize_operations calculates percent_of_total."""
        profiler = MigrationPerformanceProfiler(mock_connection)
        profiler.current_profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        profiler.record_operation("op1", 0.5)
        profiler.record_operation("op2", 0.3)

        profiler._finalize_operations()

        assert profiler.current_profile.operations["op1"].percent_of_total == 50.0
        assert profiler.current_profile.operations["op2"].percent_of_total == 30.0

    def test_finalize_operations_zero_duration(self, mock_connection):
        """Test _finalize_operations with zero total duration."""
        profiler = MigrationPerformanceProfiler(mock_connection)
        profiler.current_profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=0.0,
            total_duration_seconds=0.0,
        )

        profiler.record_operation("op1", 0.5)
        profiler._finalize_operations()

        # Should not divide by zero
        assert profiler.current_profile.operations["op1"].percent_of_total == 0.0


class TestSectionTracker:
    """Test _SectionTracker context manager."""

    @pytest.fixture
    def mock_profiler(self):
        """Create mock profiler."""
        profiler = MagicMock(spec=MigrationPerformanceProfiler)
        return profiler

    def test_tracks_duration(self, mock_profiler):
        """Test tracker records duration."""
        tracker = _SectionTracker(mock_profiler, "test_section")

        with tracker:
            time.sleep(0.01)

        mock_profiler.record_operation.assert_called_once()
        call_args = mock_profiler.record_operation.call_args
        assert call_args.kwargs["name"] == "test_section"
        assert call_args.kwargs["duration_seconds"] >= 0.01

    def test_memory_tracking_without_psutil(self, mock_profiler):
        """Test memory tracking when psutil not available."""
        tracker = _SectionTracker(mock_profiler, "test")

        with patch.dict("sys.modules", {"psutil": None}):
            with tracker:
                pass

        # Should still complete without error

    def test_memory_tracking_with_psutil(self, mock_profiler):
        """Test memory tracking with psutil available."""
        mock_psutil = MagicMock()
        mock_process = MagicMock()
        mock_process.memory_info.return_value.rss = 100 * 1024 * 1024  # 100 MB

        tracker = _SectionTracker(mock_profiler, "test")

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            mock_psutil.Process.return_value = mock_process
            result = tracker._get_memory_usage_mb()

        assert result == 100.0


class TestPerformanceBaseline:
    """Test PerformanceBaseline class."""

    @pytest.fixture
    def temp_baseline_file(self, tmp_path):
        """Create temporary baseline file path."""
        return tmp_path / "baselines.json"

    def test_init_creates_empty_baselines(self, temp_baseline_file):
        """Test init with non-existent file."""
        baseline = PerformanceBaseline(temp_baseline_file)
        assert baseline.baselines == {}

    def test_load_baselines_from_file(self, temp_baseline_file):
        """Test loading baselines from existing file."""
        data = {"baselines": {"migration1": {"total_duration_seconds": 5.0}}}
        temp_baseline_file.write_text(json.dumps(data))

        baseline = PerformanceBaseline(temp_baseline_file)

        assert "migration1" in baseline.baselines
        assert baseline.baselines["migration1"]["total_duration_seconds"] == 5.0

    def test_save_baselines(self, temp_baseline_file):
        """Test saving baselines to file."""
        baseline = PerformanceBaseline(temp_baseline_file)
        baseline.baselines["test"] = {"total_duration_seconds": 1.0}

        baseline.save_baselines()

        assert temp_baseline_file.exists()
        saved_data = json.loads(temp_baseline_file.read_text())
        assert saved_data["baselines"]["test"]["total_duration_seconds"] == 1.0

    def test_set_baseline(self, temp_baseline_file):
        """Test set_baseline method."""
        baseline = PerformanceBaseline(temp_baseline_file)

        profile = PerformanceProfile(
            migration_name="test_migration",
            start_timestamp=0.0,
            end_timestamp=5.0,
            total_duration_seconds=5.0,
            memory_peak_mb=256.0,
        )
        profile.operations["op1"] = OperationMetrics(
            name="op1",
            start_time=0.0,
            end_time=2.0,
            duration_seconds=2.0,
            percent_of_total=40.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )

        baseline.set_baseline("test_migration", profile)

        assert "test_migration" in baseline.baselines
        assert baseline.baselines["test_migration"]["total_duration_seconds"] == 5.0
        assert baseline.baselines["test_migration"]["operations"]["op1"] == 2.0

    def test_detect_regression_no_baseline(self, temp_baseline_file):
        """Test detect_regression when no baseline exists."""
        baseline = PerformanceBaseline(temp_baseline_file)

        profile = PerformanceProfile(
            migration_name="new_migration",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        report = baseline.detect_regression(profile)

        assert report.migration_name == "new_migration"
        assert not report.has_regressions

    def test_detect_regression_total_duration(self, temp_baseline_file):
        """Test detect_regression catches total duration regression."""
        baseline = PerformanceBaseline(temp_baseline_file)
        baseline.baselines["test"] = {
            "total_duration_seconds": 1.0,
            "memory_peak_mb": 100.0,
            "operations": {},
        }

        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=2.0,
            total_duration_seconds=2.0,  # 100% regression
        )

        report = baseline.detect_regression(profile, threshold_pct=20.0)

        assert report.has_regressions
        assert len(report.regressions) == 1
        assert report.regressions[0]["type"] == "total_duration"
        assert report.regressions[0]["regression_pct"] == 100.0

    def test_detect_regression_operation_duration(self, temp_baseline_file):
        """Test detect_regression catches operation regression."""
        baseline = PerformanceBaseline(temp_baseline_file)
        baseline.baselines["test"] = {
            "total_duration_seconds": 1.0,
            "memory_peak_mb": 100.0,
            "operations": {"slow_op": 0.5},
        }

        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )
        profile.operations["slow_op"] = OperationMetrics(
            name="slow_op",
            start_time=0.0,
            end_time=1.5,
            duration_seconds=1.5,  # 200% regression from 0.5
            percent_of_total=100.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )

        report = baseline.detect_regression(profile, threshold_pct=20.0)

        assert report.has_regressions
        regression = next(r for r in report.regressions if r["type"] == "operation_duration")
        assert regression["operation"] == "slow_op"
        assert regression["regression_pct"] == 200.0

    def test_generate_optimization_report(self, temp_baseline_file):
        """Test generate_optimization_report."""
        baseline = PerformanceBaseline(temp_baseline_file)

        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )
        profile.operations["UPDATE users"] = OperationMetrics(
            name="UPDATE users",
            start_time=0.0,
            end_time=0.8,
            duration_seconds=0.8,
            percent_of_total=80.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )

        report = baseline.generate_optimization_report(profile)

        assert report.migration_name == "test"
        assert len(report.bottlenecks) == 1
        assert len(report.recommendations) == 1
        assert "CRITICAL" in report.recommendations[0].severity

    def test_generate_recommendation_update(self, temp_baseline_file):
        """Test _generate_recommendation for UPDATE operation."""
        baseline = PerformanceBaseline(temp_baseline_file)

        bottleneck = OperationMetrics(
            name="UPDATE large_table",
            start_time=0.0,
            end_time=0.5,
            duration_seconds=0.5,
            percent_of_total=50.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        recommendation = baseline._generate_recommendation(bottleneck, profile)

        assert recommendation is not None
        assert "UPDATE" in recommendation.recommendation
        assert recommendation.severity == "IMPORTANT"

    def test_generate_recommendation_insert(self, temp_baseline_file):
        """Test _generate_recommendation for INSERT operation."""
        baseline = PerformanceBaseline(temp_baseline_file)

        bottleneck = OperationMetrics(
            name="INSERT INTO users",
            start_time=0.0,
            end_time=0.5,
            duration_seconds=0.5,
            percent_of_total=50.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        recommendation = baseline._generate_recommendation(bottleneck, profile)

        assert recommendation is not None
        assert "INSERT" in recommendation.recommendation or "COPY" in recommendation.recommendation

    def test_generate_recommendation_index(self, temp_baseline_file):
        """Test _generate_recommendation for INDEX operation."""
        baseline = PerformanceBaseline(temp_baseline_file)

        # Use a name that contains INDEX but not CREATE to hit the INDEX branch
        bottleneck = OperationMetrics(
            name="Build INDEX idx_users",
            start_time=0.0,
            end_time=0.5,
            duration_seconds=0.5,
            percent_of_total=50.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        recommendation = baseline._generate_recommendation(bottleneck, profile)

        assert recommendation is not None
        assert "CONCURRENTLY" in recommendation.recommendation

    def test_generate_recommendation_unknown_operation(self, temp_baseline_file):
        """Test _generate_recommendation for unknown operation type."""
        baseline = PerformanceBaseline(temp_baseline_file)

        bottleneck = OperationMetrics(
            name="some_unknown_op",
            start_time=0.0,
            end_time=0.5,
            duration_seconds=0.005,  # Below threshold
            percent_of_total=50.0,
            memory_before_mb=None,
            memory_after_mb=None,
            io_operations=None,
        )
        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=1.0,
            total_duration_seconds=1.0,
        )

        recommendation = baseline._generate_recommendation(bottleneck, profile)

        assert recommendation is None

    def test_extract_operation_type(self, temp_baseline_file):
        """Test _extract_operation_type method."""
        baseline = PerformanceBaseline(temp_baseline_file)

        assert baseline._extract_operation_type("UPDATE users SET") == "UPDATE"
        assert baseline._extract_operation_type("insert into table") == "INSERT"
        assert baseline._extract_operation_type("DELETE FROM") == "DELETE"
        assert baseline._extract_operation_type("ALTER TABLE") == "ALTER"
        assert baseline._extract_operation_type("CREATE TABLE") == "CREATE"
        # CREATE INDEX matches CREATE first (per implementation order)
        assert baseline._extract_operation_type("CREATE INDEX") == "CREATE"
        # Pure INDEX without CREATE matches INDEX
        assert baseline._extract_operation_type("Build INDEX") == "INDEX"
        assert baseline._extract_operation_type("random operation") == "UNKNOWN"

    def test_export_baseline(self, temp_baseline_file, tmp_path):
        """Test export_baseline method."""
        baseline = PerformanceBaseline(temp_baseline_file)
        baseline.baselines["migration1"] = {"total_duration_seconds": 5.0}

        export_path = tmp_path / "exported" / "baselines.json"
        baseline.export_baseline(export_path)

        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["baselines"]["migration1"]["total_duration_seconds"] == 5.0

    def test_export_comparison(self, temp_baseline_file, tmp_path):
        """Test export_comparison method."""
        baseline = PerformanceBaseline(temp_baseline_file)
        baseline.baselines["test"] = {
            "total_duration_seconds": 1.0,
            "memory_peak_mb": 0.0,
            "operations": {},
        }

        profile = PerformanceProfile(
            migration_name="test",
            start_timestamp=0.0,
            end_timestamp=2.0,
            total_duration_seconds=2.0,
        )

        export_path = tmp_path / "comparison" / "result.json"
        baseline.export_comparison(profile, export_path)

        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["migration"] == "test"
        assert "regression" in data
        assert "optimization" in data
