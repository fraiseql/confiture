"""Integration tests for Phase 2 components.

Tests the integration of logging, metrics, and context with Phase 1 error codes.
"""

from io import StringIO
import json

import pytest

from confiture.core.logging import StructuredLogger
from confiture.core.metrics import ErrorMetrics
from confiture.core.context import AgentContext, set_context, get_context
from confiture.core.metrics_aggregator import MetricsAggregator
from confiture.exceptions import ConfigurationError, MigrationError


class TestPhase1Phase2Integration:
    """Test integration between Phase 1 (error codes) and Phase 2 (logging/metrics)."""

    def test_logger_uses_phase1_error_codes(self) -> None:
        """Test that StructuredLogger includes Phase 1 error codes."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfigurationError(
            "Missing config",
            error_code="CONFIG_001",
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        data = json.loads(log_line)

        # Phase 1 error code should be in log
        assert data.get("error_code") == "CONFIG_001"

    def test_metrics_tracks_error_codes(self) -> None:
        """Test that ErrorMetrics tracks Phase 1 error codes."""
        metrics = ErrorMetrics()

        error = MigrationError(
            "Migration failed",
            version="001",
            error_code="MIGR_100",
        )
        metrics.record(error)

        # Should track by code
        assert metrics.count_by_code("MIGR_100") == 1

    def test_context_includes_error_context(self) -> None:
        """Test that AgentContext can include error context."""
        error = ConfigurationError(
            "Config error",
            error_code="CONFIG_001",
            context={"file": "local.yaml"},
        )

        ctx = AgentContext(
            request_id="req-123",
            workflow_stage="initialization",
            custom_data={"error": error.to_dict()},
        )

        # Context should include error info
        assert ctx.custom_data["error"]["error_code"] == "CONFIG_001"

    def test_full_pipeline_logging_and_metrics(self) -> None:
        """Test complete pipeline: error -> logging -> metrics -> context."""
        output = StringIO()
        logger = StructuredLogger(output=output)
        metrics = ErrorMetrics()

        # Set up context
        ctx = AgentContext(
            request_id="req-123",
            workflow_stage="migration_up",
            operation_type="apply_migration",
        )

        with ctx:
            # Create and log error
            error = MigrationError(
                "Migration failed",
                version="001",
                error_code="MIGR_100",
            )

            # Log it
            logger.log_error(error, request_id=ctx.request_id)

            # Record metrics
            metrics.record(error)

            # Verify context is active
            assert get_context() == ctx

        # Verify logging
        log_line = output.getvalue().strip()
        log_data = json.loads(log_line)
        assert log_data["error_code"] == "MIGR_100"
        assert log_data["request_id"] == "req-123"

        # Verify metrics
        assert metrics.count_by_code("MIGR_100") == 1

    def test_json_output_includes_error_code_info(self) -> None:
        """Test that JSON logs include Phase 1 error code information."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        error = ConfigurationError(
            "Missing database URL",
            error_code="CONFIG_001",
            resolution_hint="Add database_url to config",
        )
        logger.log_error(error)

        log_line = output.getvalue().strip()
        data = json.loads(log_line)

        # Should have error code, message, and resolution hint
        assert data["error_code"] == "CONFIG_001"
        assert "Missing database URL" in data["message"]
        assert data.get("resolution_hint") == "Add database_url to config"

    def test_metrics_aggregator_with_phase1_codes(self) -> None:
        """Test MetricsAggregator works with Phase 1 error codes."""
        metrics = ErrorMetrics()

        # Record errors with different codes
        for i in range(3):
            error = ConfigurationError(
                f"Config error {i}",
                error_code="CONFIG_001",
            )
            metrics.record(error)

        for i in range(2):
            error = MigrationError(
                f"Migration error {i}",
                version="001",
                error_code="MIGR_100",
            )
            metrics.record(error)

        # Use aggregator
        agg = MetricsAggregator(metrics)

        # Query by code
        result = agg.query(code="CONFIG_001")
        assert result["results"]["count"] == 3

        # Get top errors
        top = agg.top_by_code(n=2)
        assert top[0][0] in ["CONFIG_001", "MIGR_100"]

    def test_context_propagates_through_logging(self) -> None:
        """Test that AgentContext info propagates to logs."""
        output = StringIO()
        logger = StructuredLogger(output=output)

        ctx = AgentContext(
            request_id="req-456",
            workflow_stage="schema_diff",
            operation_type="detect_changes",
        )

        with ctx:
            error = ConfigurationError("Config error")
            logger.log_error(
                error,
                request_id=ctx.request_id,
                workflow_stage=ctx.workflow_stage,
            )

        log_line = output.getvalue().strip()
        data = json.loads(log_line)

        # Context info should be in log
        assert data["request_id"] == "req-456"
        assert data["workflow_stage"] == "schema_diff"
