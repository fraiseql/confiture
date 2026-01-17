"""Tests for observability features."""

import logging
from unittest.mock import MagicMock, Mock, patch

import pytest

from confiture.core.observability import (
    AuditConfig,
    AuditEntry,
    AuditTrail,
    LoggingConfig,
    MetricsConfig,
    MigrationMetrics,
    MigrationTracer,
    StructuredLogger,
    TracingConfig,
    configure_logging,
    create_metrics,
    create_tracer,
)


class TestTracingConfig:
    """Tests for TracingConfig."""

    def test_default_config(self):
        """Test default tracing config."""
        config = TracingConfig()
        assert config.enabled is False
        assert config.service_name == "confiture"
        assert config.endpoint is None
        assert config.sample_rate == 1.0

    def test_custom_config(self):
        """Test custom tracing config."""
        config = TracingConfig(
            enabled=True,
            service_name="my-service",
            endpoint="http://localhost:4317",
            sample_rate=0.5,
        )
        assert config.enabled is True
        assert config.service_name == "my-service"
        assert config.endpoint == "http://localhost:4317"
        assert config.sample_rate == 0.5


class TestMigrationTracer:
    """Tests for MigrationTracer."""

    def test_disabled_tracing_noop(self):
        """Test disabled tracing is no-op."""
        tracer = MigrationTracer(TracingConfig(enabled=False))
        assert not tracer.is_enabled

        with tracer.span("test.span", key="value") as span:
            assert span is None

    def test_create_tracer_factory(self):
        """Test create_tracer factory function."""
        tracer = create_tracer()
        assert isinstance(tracer, MigrationTracer)
        assert not tracer.is_enabled

    def test_record_migration_start_disabled(self):
        """Test record_migration_start when disabled."""
        tracer = MigrationTracer(TracingConfig(enabled=False))
        ctx = tracer.record_migration_start("001", "create_users")
        with ctx as span:
            assert span is None

    def test_record_error_disabled(self):
        """Test record_error when disabled is no-op."""
        tracer = MigrationTracer(TracingConfig(enabled=False))
        tracer.record_error(None, Exception("test"))  # Should not raise

    def test_record_success_disabled(self):
        """Test record_success when disabled is no-op."""
        tracer = MigrationTracer(TracingConfig(enabled=False))
        tracer.record_success(None, 100)  # Should not raise


class TestMetricsConfig:
    """Tests for MetricsConfig."""

    def test_default_config(self):
        """Test default metrics config."""
        config = MetricsConfig()
        assert config.enabled is False
        assert config.port == 9090
        assert config.path == "/metrics"


class TestMigrationMetrics:
    """Tests for MigrationMetrics."""

    def test_disabled_metrics_noop(self):
        """Test disabled metrics is no-op."""
        metrics = MigrationMetrics(MetricsConfig(enabled=False))
        assert not metrics.is_enabled

        # These should not raise
        metrics.record_migration("001", "test", 1.0, True)
        metrics.record_error("001", Exception("test"))
        metrics.start_server()

    def test_create_metrics_factory(self):
        """Test create_metrics factory function."""
        metrics = create_metrics()
        assert isinstance(metrics, MigrationMetrics)
        assert not metrics.is_enabled

    def test_record_migration_disabled(self):
        """Test record_migration when disabled."""
        metrics = MigrationMetrics(MetricsConfig(enabled=False))
        metrics.record_migration("001", "create_users", 2.5, True)
        # Should not raise


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_default_config(self):
        """Test default logging config."""
        config = LoggingConfig()
        assert config.enabled is True
        assert config.format == "json"
        assert config.level == "INFO"
        assert config.include_timestamp is True
        assert config.include_correlation_id is True


class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_logger_creation(self):
        """Test creating a structured logger."""
        logger = StructuredLogger("test.logger")
        assert logger._correlation_id is None

    def test_set_correlation_id(self):
        """Test setting correlation ID."""
        logger = StructuredLogger("test.logger")
        logger.set_correlation_id("abc123")
        assert logger._correlation_id == "abc123"

    def test_clear_correlation_id(self):
        """Test clearing correlation ID."""
        logger = StructuredLogger("test.logger")
        logger.set_correlation_id("abc123")
        logger.clear_correlation_id()
        assert logger._correlation_id is None

    def test_new_correlation_id(self):
        """Test generating new correlation ID."""
        logger = StructuredLogger("test.logger")
        cid = logger.new_correlation_id()
        assert len(cid) == 8
        assert logger._correlation_id == cid

    def test_log_methods(self):
        """Test all log methods."""
        logger = StructuredLogger("test.logger")

        # These should not raise
        with patch.object(logger._logger, "log"):
            logger.debug("debug message")
            logger.info("info message")
            logger.warning("warning message")
            logger.error("error message")


class TestConfigureLogging:
    """Tests for configure_logging function."""

    @pytest.fixture(autouse=True)
    def reset_logger(self):
        """Reset logger after each test to avoid affecting other tests."""
        yield
        # Reset the confiture logger to default state
        logger = logging.getLogger("confiture")
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)

    def test_configure_json_format(self):
        """Test configuring JSON format logging."""
        config = LoggingConfig(format="json", level="DEBUG")
        configure_logging(config)

        logger = logging.getLogger("confiture")
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1

    def test_configure_text_format(self):
        """Test configuring text format logging."""
        config = LoggingConfig(format="text", level="INFO")
        configure_logging(config)

        logger = logging.getLogger("confiture")
        assert logger.level == logging.INFO


class TestAuditConfig:
    """Tests for AuditConfig."""

    def test_default_config(self):
        """Test default audit config."""
        config = AuditConfig()
        assert config.enabled is True
        assert config.table_name == "confiture_audit_log"


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_entry_creation(self):
        """Test creating an audit entry."""
        entry = AuditEntry(
            migration_version="001",
            migration_name="create_users",
            action="apply",
            status="started",
            user="testuser",
            hostname="testhost",
        )
        assert entry.migration_version == "001"
        assert entry.action == "apply"
        assert entry.duration_ms is None

    def test_entry_to_dict(self):
        """Test converting entry to dictionary."""
        entry = AuditEntry(
            migration_version="001",
            migration_name="create_users",
            action="apply",
            status="completed",
            user="testuser",
            hostname="testhost",
            duration_ms=1500,
        )
        result = entry.to_dict()
        assert result["migration_version"] == "001"
        assert result["duration_ms"] == 1500
        assert "timestamp" in result


class TestAuditTrail:
    """Tests for AuditTrail."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = []
        cursor.description = [("id",), ("migration_version",)]
        return conn, cursor

    def test_disabled_audit_noop(self, mock_connection):
        """Test disabled audit trail is no-op."""
        conn, _ = mock_connection
        audit = AuditTrail(conn, AuditConfig(enabled=False))
        assert not audit.is_enabled

        # These should not raise or execute anything
        audit.initialize()
        entry_id = audit.record_start("001", "test", "apply")
        assert entry_id == -1
        audit.record_complete(entry_id, 100)
        history = audit.get_history()
        assert history == []

    def test_initialize_creates_table(self, mock_connection):
        """Test initialize creates audit table."""
        conn, cursor = mock_connection
        audit = AuditTrail(conn, AuditConfig(enabled=True))
        audit.initialize()

        # Should have called execute for CREATE TABLE and indexes
        assert cursor.execute.called
        assert conn.commit.called

    def test_record_start(self, mock_connection):
        """Test recording migration start."""
        conn, cursor = mock_connection
        audit = AuditTrail(conn, AuditConfig(enabled=True))

        entry_id = audit.record_start("001", "create_users", "apply")

        assert entry_id == 1
        assert cursor.execute.called
        assert conn.commit.called

    def test_record_complete(self, mock_connection):
        """Test recording migration completion."""
        conn, cursor = mock_connection
        audit = AuditTrail(conn, AuditConfig(enabled=True))

        audit.record_complete(1, 1500)

        assert cursor.execute.called
        assert conn.commit.called

    def test_record_complete_with_error(self, mock_connection):
        """Test recording failed migration."""
        conn, cursor = mock_connection
        audit = AuditTrail(conn, AuditConfig(enabled=True))

        audit.record_complete(1, 500, error_message="Migration failed")

        assert cursor.execute.called
        # Check that error message was passed
        call_args = cursor.execute.call_args
        assert "Migration failed" in str(call_args)

    def test_get_history(self, mock_connection):
        """Test getting audit history."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = [
            (1, "001", "create_users", "apply", "completed", "user", "host", None, None, 100, None, "{}")
        ]
        cursor.description = [
            ("id",), ("migration_version",), ("migration_name",),
            ("action",), ("status",), ("username",), ("hostname",),
            ("started_at",), ("completed_at",), ("duration_ms",),
            ("error_message",), ("metadata",),
        ]

        audit = AuditTrail(conn, AuditConfig(enabled=True))
        history = audit.get_history(limit=10)

        assert len(history) == 1
        assert history[0]["migration_version"] == "001"

    def test_get_history_filtered(self, mock_connection):
        """Test getting filtered audit history."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []
        cursor.description = []

        audit = AuditTrail(conn, AuditConfig(enabled=True))
        audit.get_history(migration_version="001", action="apply")

        # Should have WHERE clause
        call_args = cursor.execute.call_args
        assert "WHERE" in str(call_args)

    def test_get_recent_failures(self, mock_connection):
        """Test getting recent failures."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []
        cursor.description = []

        audit = AuditTrail(conn, AuditConfig(enabled=True))
        failures = audit.get_recent_failures()

        assert failures == []
        assert cursor.execute.called


class TestAuditTrailIntegration:
    """Integration tests for audit trail with real database."""

    @pytest.fixture
    def db_connection(self):
        """Create test database connection if available."""
        try:
            import psycopg
            conn = psycopg.connect("postgresql://localhost/confiture_test")
            yield conn
            conn.close()
        except Exception:
            pytest.skip("Test database not available")

    def test_full_audit_cycle(self, db_connection):
        """Test complete audit trail cycle."""
        audit = AuditTrail(db_connection, AuditConfig(enabled=True))
        audit.initialize()

        # Record start
        entry_id = audit.record_start(
            "test_001",
            "test_migration",
            "apply",
            metadata={"test": True},
        )
        assert entry_id > 0

        # Record complete
        audit.record_complete(entry_id, 100)

        # Get history
        history = audit.get_history(migration_version="test_001")
        assert len(history) >= 1

        # Cleanup
        with db_connection.cursor() as cur:
            cur.execute(
                "DELETE FROM confiture_audit_log WHERE migration_version = %s",
                ("test_001",),
            )
        db_connection.commit()
