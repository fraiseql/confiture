"""Comprehensive tests for downtime prediction and historical analysis.

Tests the downtime predictor system including heuristic estimation,
historical data analysis, and confidence interval generation.
"""

import statistics

import pytest

from confiture.core.risk.predictor import (
    DowntimeEstimate,
    DowntimePredictor,
    HistoricalMigration,
    HistoricalMigrations,
    MigrationOperation,
)


class TestMigrationOperation:
    """Test MigrationOperation dataclass."""

    def test_create_migration_operation_basic(self):
        """Test creating basic migration operation."""
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=100,
            table_name="users",
        )
        assert op.id == "op-001"
        assert op.type == "ADD_COLUMN"
        assert op.table_size_mb == 100
        assert op.table_name == "users"

    def test_create_migration_operation_various_types(self):
        """Test creating operations of various types."""
        types = [
            "ADD_COLUMN",
            "DROP_COLUMN",
            "ALTER_TYPE",
            "ADD_INDEX",
            "DROP_INDEX",
        ]
        for op_type in types:
            op = MigrationOperation(
                id="op-test",
                type=op_type,
                table_size_mb=50,
                table_name="test",
            )
            assert op.type == op_type

    def test_create_migration_operation_various_sizes(self):
        """Test creating operations with various table sizes."""
        sizes = [1, 100, 1000, 10000, 1000000]
        for size in sizes:
            op = MigrationOperation(
                id="op-test",
                type="ADD_COLUMN",
                table_size_mb=size,
                table_name="test",
            )
            assert op.table_size_mb == size


class TestHistoricalMigration:
    """Test HistoricalMigration dataclass."""

    def test_create_historical_migration_basic(self):
        """Test creating basic historical migration record."""
        hm = HistoricalMigration(
            operation_type="ADD_COLUMN",
            table_size_mb=100,
            actual_downtime_ms=150,
        )
        assert hm.operation_type == "ADD_COLUMN"
        assert hm.table_size_mb == 100
        assert hm.actual_downtime_ms == 150
        assert hm.recorded_at == ""

    def test_create_historical_migration_with_timestamp(self):
        """Test creating historical migration with timestamp."""
        hm = HistoricalMigration(
            operation_type="ALTER_TYPE",
            table_size_mb=500,
            actual_downtime_ms=1200,
            recorded_at="2025-01-15T10:30:00Z",
        )
        assert hm.recorded_at == "2025-01-15T10:30:00Z"

    def test_historical_migration_zero_downtime(self):
        """Test historical migration with zero downtime."""
        hm = HistoricalMigration(
            operation_type="ADD_INDEX",
            table_size_mb=10,
            actual_downtime_ms=0,
        )
        assert hm.actual_downtime_ms == 0


class TestDowntimeEstimate:
    """Test DowntimeEstimate dataclass."""

    def test_create_downtime_estimate_basic(self):
        """Test creating basic downtime estimate."""
        est = DowntimeEstimate(
            estimated_downtime_ms=150,
            lower_bound_ms=100,
            upper_bound_ms=200,
            confidence_level=0.8,
            estimate_method="historical",
        )
        assert est.estimated_downtime_ms == 150
        assert est.lower_bound_ms == 100
        assert est.upper_bound_ms == 200
        assert est.confidence_level == 0.8
        assert est.estimate_method == "historical"
        assert est.contributing_factors == {}
        assert est.caveats == []

    def test_create_downtime_estimate_with_factors(self):
        """Test creating estimate with contributing factors."""
        factors = {
            "similar_migrations": 5,
            "average_downtime_ms": 140,
        }
        est = DowntimeEstimate(
            estimated_downtime_ms=150,
            lower_bound_ms=100,
            upper_bound_ms=200,
            confidence_level=0.8,
            estimate_method="historical",
            contributing_factors=factors,
        )
        assert est.contributing_factors == factors

    def test_create_downtime_estimate_with_caveats(self):
        """Test creating estimate with caveats."""
        caveats = ["Low historical sample size", "System load may differ"]
        est = DowntimeEstimate(
            estimated_downtime_ms=150,
            lower_bound_ms=100,
            upper_bound_ms=200,
            confidence_level=0.8,
            estimate_method="historical",
            caveats=caveats,
        )
        assert est.caveats == caveats

    def test_downtime_estimate_confidence_levels(self):
        """Test estimates with various confidence levels."""
        for confidence in [0.0, 0.3, 0.5, 0.8, 1.0]:
            est = DowntimeEstimate(
                estimated_downtime_ms=100,
                lower_bound_ms=50,
                upper_bound_ms=150,
                confidence_level=confidence,
                estimate_method="test",
            )
            assert est.confidence_level == confidence


class TestHistoricalMigrationsManager:
    """Test HistoricalMigrations manager class."""

    def test_create_empty_manager(self):
        """Test creating empty historical migrations manager."""
        hm = HistoricalMigrations()
        assert hm.migrations == []

    def test_add_single_migration(self):
        """Test adding single migration record."""
        hm = HistoricalMigrations()
        migration = HistoricalMigration(
            operation_type="ADD_COLUMN",
            table_size_mb=100,
            actual_downtime_ms=150,
        )

        hm.add(migration)

        assert len(hm.migrations) == 1
        assert hm.migrations[0] == migration

    def test_add_multiple_migrations(self):
        """Test adding multiple migration records."""
        hm = HistoricalMigrations()
        migrations = [
            HistoricalMigration("ADD_COLUMN", 100, 150),
            HistoricalMigration("ALTER_TYPE", 200, 450),
            HistoricalMigration("ADD_INDEX", 50, 50),
        ]

        for migration in migrations:
            hm.add(migration)

        assert len(hm.migrations) == 3

    def test_find_similar_exact_match(self):
        """Test finding similar migrations with exact size match."""
        hm = HistoricalMigrations()
        hm.add(HistoricalMigration("ADD_COLUMN", 100, 150))
        hm.add(HistoricalMigration("ADD_COLUMN", 100, 160))
        hm.add(HistoricalMigration("ADD_COLUMN", 200, 200))

        similar = hm.find_similar(table_size_mb=100, operation_type="ADD_COLUMN")

        assert len(similar) == 2
        assert all(m.table_size_mb in [100] for m in similar)

    def test_find_similar_with_tolerance(self):
        """Test finding similar migrations within 20% size tolerance."""
        hm = HistoricalMigrations()
        hm.add(HistoricalMigration("ADD_COLUMN", 100, 150))
        hm.add(HistoricalMigration("ADD_COLUMN", 110, 160))  # 10% difference
        hm.add(HistoricalMigration("ADD_COLUMN", 125, 165))  # 25% difference
        hm.add(HistoricalMigration("ADD_COLUMN", 200, 300))

        similar = hm.find_similar(table_size_mb=100, operation_type="ADD_COLUMN")

        # Should include 100 and 110 (within 20%), but not 125 (outside 20%)
        assert len(similar) == 2
        assert 100 in [m.table_size_mb for m in similar]
        assert 110 in [m.table_size_mb for m in similar]

    def test_find_similar_no_matches(self):
        """Test finding similar when no matches exist."""
        hm = HistoricalMigrations()
        hm.add(HistoricalMigration("ALTER_TYPE", 100, 150))

        similar = hm.find_similar(
            table_size_mb=100,
            operation_type="ADD_COLUMN",
        )

        assert similar == []

    def test_find_similar_respects_max_results(self):
        """Test that find_similar respects max_results parameter."""
        hm = HistoricalMigrations()
        for i in range(15):
            hm.add(HistoricalMigration("ADD_COLUMN", 100 + i, 150 + i))

        similar = hm.find_similar(
            table_size_mb=100,
            operation_type="ADD_COLUMN",
            max_results=5,
        )

        assert len(similar) == 5

    def test_find_similar_operation_type_filtering(self):
        """Test that find_similar filters by operation type."""
        hm = HistoricalMigrations()
        hm.add(HistoricalMigration("ADD_COLUMN", 100, 150))
        hm.add(HistoricalMigration("ALTER_TYPE", 100, 500))
        hm.add(HistoricalMigration("ADD_COLUMN", 105, 160))

        add_column = hm.find_similar(
            table_size_mb=100,
            operation_type="ADD_COLUMN",
        )
        alter_type = hm.find_similar(
            table_size_mb=100,
            operation_type="ALTER_TYPE",
        )

        assert len(add_column) == 2
        assert len(alter_type) == 1


class TestDowntimePredictorHeuristic:
    """Test heuristic downtime prediction."""

    @pytest.mark.asyncio
    async def test_heuristic_prediction_add_column(self):
        """Test heuristic prediction for ADD_COLUMN."""
        predictor = DowntimePredictor()
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=100,
            table_name="users",
        )

        estimate = await predictor.predict_downtime(op)

        assert estimate.estimate_method == "heuristic"
        assert estimate.confidence_level == 0.3
        assert estimate.estimated_downtime_ms > 0
        assert estimate.lower_bound_ms < estimate.estimated_downtime_ms
        assert estimate.upper_bound_ms > estimate.estimated_downtime_ms

    @pytest.mark.asyncio
    async def test_heuristic_prediction_alter_type(self):
        """Test heuristic prediction for ALTER_TYPE (full rewrite)."""
        predictor = DowntimePredictor()
        op_small = MigrationOperation(
            id="op-small",
            type="ALTER_TYPE",
            table_size_mb=10,
            table_name="small_table",
        )
        op_large = MigrationOperation(
            id="op-large",
            type="ALTER_TYPE",
            table_size_mb=1000,
            table_name="large_table",
        )

        est_small = await predictor.predict_downtime(op_small)
        est_large = await predictor.predict_downtime(op_large)

        # Larger table should have higher downtime
        assert est_large.estimated_downtime_ms > est_small.estimated_downtime_ms

    @pytest.mark.asyncio
    async def test_heuristic_prediction_add_index(self):
        """Test heuristic prediction for ADD_INDEX (slower scale)."""
        predictor = DowntimePredictor()
        op = MigrationOperation(
            id="op-001",
            type="ADD_INDEX",
            table_size_mb=1000,
            table_name="big_table",
        )

        estimate = await predictor.predict_downtime(op)

        # ADD_INDEX scales at 0.5ms per GB, so 1000MB = 0.5GB = 250ms adjustment
        assert estimate.estimated_downtime_ms > 250

    @pytest.mark.asyncio
    async def test_heuristic_prediction_unknown_type(self):
        """Test heuristic prediction for unknown operation type."""
        predictor = DowntimePredictor()
        op = MigrationOperation(
            id="op-001",
            type="CUSTOM_OPERATION",
            table_size_mb=100,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        # Should use default base time and 1ms per GB adjustment
        assert estimate.estimated_downtime_ms > 0

    @pytest.mark.asyncio
    async def test_heuristic_confidence_is_low(self):
        """Test that heuristic predictions have low confidence."""
        predictor = DowntimePredictor()
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=50,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        assert estimate.confidence_level == 0.3
        assert len(estimate.caveats) > 0


class TestDowntimePredictorHistorical:
    """Test historical data based prediction."""

    @pytest.mark.asyncio
    async def test_historical_prediction_with_data(self):
        """Test prediction with historical data available."""
        historical_data = HistoricalMigrations()
        historical_data.add(
            HistoricalMigration("ADD_COLUMN", 100, 150)
        )
        historical_data.add(
            HistoricalMigration("ADD_COLUMN", 105, 160)
        )
        historical_data.add(
            HistoricalMigration("ADD_COLUMN", 95, 140)
        )

        predictor = DowntimePredictor(historical_data=historical_data)
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=100,
            table_name="users",
        )

        estimate = await predictor.predict_downtime(op)

        assert estimate.estimate_method == "historical"
        # Should be average of the three values: (150 + 160 + 140) / 3 = 150
        assert abs(estimate.estimated_downtime_ms - 150) < 5

    @pytest.mark.asyncio
    async def test_historical_prediction_single_sample(self):
        """Test prediction with single historical sample."""
        historical_data = HistoricalMigrations()
        historical_data.add(
            HistoricalMigration("ALTER_TYPE", 100, 500)
        )

        predictor = DowntimePredictor(historical_data=historical_data)
        op = MigrationOperation(
            id="op-001",
            type="ALTER_TYPE",
            table_size_mb=100,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        assert estimate.estimate_method == "historical"
        assert estimate.estimated_downtime_ms == 500

    @pytest.mark.asyncio
    async def test_historical_prediction_no_similar(self):
        """Test prediction falls back to heuristic when no similar data."""
        historical_data = HistoricalMigrations()
        historical_data.add(
            HistoricalMigration("ALTER_TYPE", 100, 500)
        )

        predictor = DowntimePredictor(historical_data=historical_data)
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",  # Different operation type
            table_size_mb=100,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        # Should fall back to heuristic
        assert estimate.estimate_method == "heuristic"
        assert estimate.confidence_level == 0.3

    @pytest.mark.asyncio
    async def test_historical_confidence_includes_stddev(self):
        """Test that historical predictions include standard deviation in confidence."""
        historical_data = HistoricalMigrations()
        # Add data with significant variation
        historical_data.add(
            HistoricalMigration("ADD_COLUMN", 100, 100)
        )
        historical_data.add(
            HistoricalMigration("ADD_COLUMN", 105, 500)
        )

        predictor = DowntimePredictor(historical_data=historical_data)
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=100,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        # Confidence should be less than 1.0 due to variance
        assert estimate.confidence_level < 1.0
        assert estimate.estimate_method == "historical"

    @pytest.mark.asyncio
    async def test_historical_bounds_include_variance(self):
        """Test that confidence bounds account for standard deviation."""
        historical_data = HistoricalMigrations()
        # Add data with known mean and variance
        values = [100, 120, 140, 160, 180]  # mean=140, stdev~32
        for val in values:
            historical_data.add(
                HistoricalMigration("ADD_COLUMN", 100, val)
            )

        predictor = DowntimePredictor(historical_data=historical_data)
        op = MigrationOperation(
            id="op-001",
            type="ADD_COLUMN",
            table_size_mb=100,
            table_name="table",
        )

        estimate = await predictor.predict_downtime(op)

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)

        # Check bounds are approximately mean ± 2*stdev
        assert abs(estimate.estimated_downtime_ms - mean) < 2
        assert estimate.lower_bound_ms <= mean - 2 * stdev + 1
        assert estimate.upper_bound_ms >= mean + 2 * stdev - 1


class TestDowntimePredictorMethodSelection:
    """Test prediction method selection."""

    def test_predictor_method_heuristic_no_data(self):
        """Test that predictor selects heuristic when no historical data."""
        predictor = DowntimePredictor()
        assert predictor.prediction_method == "heuristic"

    def test_predictor_method_historical_with_data(self):
        """Test that predictor selects historical when data provided."""
        historical_data = HistoricalMigrations()
        predictor = DowntimePredictor(historical_data=historical_data)
        assert predictor.prediction_method == "historical"


class TestDowntimePredictionIntegration:
    """Integration tests for downtime prediction."""

    @pytest.mark.asyncio
    async def test_complete_prediction_workflow_heuristic(self):
        """Test complete prediction workflow using heuristic."""
        predictor = DowntimePredictor()

        operations = [
            MigrationOperation("op1", "ADD_COLUMN", 100, "users"),
            MigrationOperation("op2", "ALTER_TYPE", 500, "orders"),
            MigrationOperation("op3", "ADD_INDEX", 1000, "large_table"),
        ]

        estimates = []
        for op in operations:
            estimate = await predictor.predict_downtime(op)
            estimates.append(estimate)

        # Verify all estimates generated successfully
        assert len(estimates) == 3
        for est in estimates:
            assert est.estimated_downtime_ms > 0
            assert est.lower_bound_ms >= 0
            assert est.upper_bound_ms > est.estimated_downtime_ms

    @pytest.mark.asyncio
    async def test_complete_prediction_workflow_historical(self):
        """Test complete prediction workflow using historical data."""
        # Build historical data
        historical_data = HistoricalMigrations()
        for i in range(10):
            historical_data.add(
                HistoricalMigration("ADD_COLUMN", 100 + i * 10, 150 + i * 10)
            )

        predictor = DowntimePredictor(historical_data=historical_data)

        op = MigrationOperation("op1", "ADD_COLUMN", 105, "users")
        estimate = await predictor.predict_downtime(op)

        assert estimate.estimate_method == "historical"
        assert estimate.confidence_level > 0.5  # Should be fairly confident
        assert len(estimate.caveats) > 0

    @pytest.mark.asyncio
    async def test_prediction_scaling_with_table_size(self):
        """Test that predictions scale appropriately with table size."""
        predictor = DowntimePredictor()

        estimates = []
        for size_mb in [10, 100, 1000, 10000]:
            op = MigrationOperation(
                id=f"op-{size_mb}",
                type="ADD_COLUMN",
                table_size_mb=size_mb,
                table_name="table",
            )
            est = await predictor.predict_downtime(op)
            estimates.append((size_mb, est.estimated_downtime_ms))

        # Verify monotonic increase
        for i in range(1, len(estimates)):
            assert estimates[i][1] > estimates[i - 1][1]
