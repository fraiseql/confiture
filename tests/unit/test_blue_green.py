"""Tests for blue-green migration orchestration."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.blue_green import (
    BlueGreenConfig,
    BlueGreenOrchestrator,
    HealthCheckResult,
    MigrationPhase,
    MigrationState,
    TrafficController,
)


class TestMigrationPhase:
    """Tests for MigrationPhase enum."""

    def test_all_phases_exist(self):
        """Test all expected phases exist."""
        phases = [
            "INIT",
            "SCHEMA_CREATED",
            "DATA_SYNCING",
            "DATA_SYNCED",
            "VERIFYING",
            "TRAFFIC_SWITCHING",
            "TRAFFIC_SWITCHED",
            "CLEANUP_PENDING",
            "COMPLETE",
            "FAILED",
            "ROLLED_BACK",
        ]
        for phase in phases:
            assert hasattr(MigrationPhase, phase)

    def test_phase_values(self):
        """Test phase values are strings."""
        assert MigrationPhase.INIT.value == "init"
        assert MigrationPhase.COMPLETE.value == "complete"
        assert MigrationPhase.ROLLED_BACK.value == "rolled_back"


class TestBlueGreenConfig:
    """Tests for BlueGreenConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = BlueGreenConfig()
        assert config.source_schema == "public"
        assert config.target_schema == "public_new"
        assert config.health_check_interval == 5.0
        assert config.health_check_retries == 3
        assert config.sync_timeout == 3600
        assert config.traffic_switch_delay == 10.0
        assert config.skip_cleanup is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = BlueGreenConfig(
            source_schema="app",
            target_schema="app_v2",
            health_check_retries=5,
            traffic_switch_delay=0,
        )
        assert config.source_schema == "app"
        assert config.target_schema == "app_v2"
        assert config.health_check_retries == 5
        assert config.traffic_switch_delay == 0


class TestMigrationState:
    """Tests for MigrationState dataclass."""

    def test_default_state(self):
        """Test default state values."""
        state = MigrationState()
        assert state.phase == MigrationPhase.INIT
        assert state.source_schema == "public"
        assert state.target_schema == "public_new"
        assert state.started_at is None
        assert state.error is None
        assert state.rollback_available is True

    def test_to_dict(self):
        """Test converting state to dictionary."""
        state = MigrationState(
            phase=MigrationPhase.COMPLETE,
            source_schema="app",
            target_schema="app_v2",
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:10:00",
        )
        result = state.to_dict()

        assert result["phase"] == "complete"
        assert result["source_schema"] == "app"
        assert result["started_at"] == "2024-01-01T00:00:00"


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_passed_result(self):
        """Test passed health check result."""
        result = HealthCheckResult(name="api", passed=True, duration_ms=50)
        assert result.name == "api"
        assert result.passed is True
        assert result.duration_ms == 50

    def test_failed_result_with_message(self):
        """Test failed health check with message."""
        result = HealthCheckResult(name="db", passed=False, message="Connection timeout")
        assert result.passed is False
        assert result.message == "Connection timeout"


class TestBlueGreenOrchestrator:
    """Tests for BlueGreenOrchestrator class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = []
        cursor.description = []
        return conn, cursor

    def test_init_default_config(self, mock_connection):
        """Test initialization with default config."""
        conn, _ = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        assert orchestrator.config.source_schema == "public"
        assert orchestrator.config.target_schema == "public_new"
        assert orchestrator.current_phase == MigrationPhase.INIT

    def test_init_custom_config(self, mock_connection):
        """Test initialization with custom config."""
        conn, _ = mock_connection
        config = BlueGreenConfig(target_schema="app_v2")
        orchestrator = BlueGreenOrchestrator(conn, config)

        assert orchestrator.config.target_schema == "app_v2"

    def test_add_health_check(self, mock_connection):
        """Test adding health checks."""
        conn, _ = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        check1 = Mock(return_value=True)
        check2 = Mock(return_value=True)

        orchestrator.add_health_check("api", check1)
        orchestrator.add_health_check("db", check2)

        assert len(orchestrator._health_checks) == 2

    def test_on_phase_change_callback(self, mock_connection):
        """Test phase change callbacks are called."""
        conn, _ = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        phases_seen = []

        def track_phases(old, new):
            phases_seen.append((old.value, new.value))

        orchestrator.on_phase_change(track_phases)
        orchestrator._set_phase(MigrationPhase.SCHEMA_CREATED)
        orchestrator._set_phase(MigrationPhase.DATA_SYNCING)

        assert len(phases_seen) == 2
        assert phases_seen[0] == ("init", "schema_created")
        assert phases_seen[1] == ("schema_created", "data_syncing")

    def test_set_data_sync_function(self, mock_connection):
        """Test setting custom data sync function."""
        conn, _ = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        sync_called = []

        def custom_sync():
            sync_called.append(True)

        orchestrator.set_data_sync_function(custom_sync)
        orchestrator._sync_data()

        assert len(sync_called) == 1

    def test_create_target_schema(self, mock_connection):
        """Test creating target schema."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        orchestrator._create_target_schema()

        cursor.execute.assert_called()
        assert orchestrator.current_phase == MigrationPhase.SCHEMA_CREATED

    def test_run_health_checks_all_pass(self, mock_connection):
        """Test health checks when all pass."""
        conn, _ = mock_connection
        config = BlueGreenConfig(health_check_interval=0)
        orchestrator = BlueGreenOrchestrator(conn, config)

        orchestrator.add_health_check("check1", lambda: True)
        orchestrator.add_health_check("check2", lambda: True)

        results = orchestrator._run_health_checks()

        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_run_health_checks_with_failure(self, mock_connection):
        """Test health checks when one fails."""
        conn, _ = mock_connection
        config = BlueGreenConfig(health_check_interval=0, health_check_retries=1)
        orchestrator = BlueGreenOrchestrator(conn, config)

        orchestrator.add_health_check("pass", lambda: True)
        orchestrator.add_health_check("fail", lambda: False)

        results = orchestrator._run_health_checks()

        assert len(results) == 2
        assert not all(r.passed for r in results)

    def test_run_health_checks_with_exception(self, mock_connection):
        """Test health checks when one raises exception."""
        conn, _ = mock_connection
        config = BlueGreenConfig(health_check_interval=0, health_check_retries=1)
        orchestrator = BlueGreenOrchestrator(conn, config)

        def failing_check():
            raise RuntimeError("Check error")

        orchestrator.add_health_check("error", failing_check)

        results = orchestrator._run_health_checks()

        assert len(results) == 1
        assert results[0].passed is False
        assert "Check error" in results[0].message

    def test_run_health_checks_retry(self, mock_connection):
        """Test health check retries on failure."""
        conn, _ = mock_connection
        config = BlueGreenConfig(health_check_interval=0, health_check_retries=3)
        orchestrator = BlueGreenOrchestrator(conn, config)

        # Fail first 2 times, pass on 3rd
        call_count = [0]

        def flaky_check():
            call_count[0] += 1
            return call_count[0] >= 3

        orchestrator.add_health_check("flaky", flaky_check)

        results = orchestrator._run_health_checks()

        assert call_count[0] == 3
        assert results[0].passed is True

    def test_run_health_checks_empty(self, mock_connection):
        """Test with no health checks configured."""
        conn, _ = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        results = orchestrator._run_health_checks()

        assert results == []

    def test_compare_schemas(self, mock_connection):
        """Test schema comparison."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = [
            ("public", "users", 100),
            ("public_new", "users", 100),
            ("public", "orders", 50),
            ("public_new", "orders", 45),  # Mismatch
        ]
        orchestrator = BlueGreenOrchestrator(conn)

        discrepancies = orchestrator._compare_schemas()

        assert "orders" in discrepancies
        assert discrepancies["orders"]["source"] == 50
        assert discrepancies["orders"]["target"] == 45
        assert "users" not in discrepancies

    def test_switch_traffic(self, mock_connection):
        """Test traffic switching."""
        conn, cursor = mock_connection
        config = BlueGreenConfig(traffic_switch_delay=0)
        orchestrator = BlueGreenOrchestrator(conn, config)

        orchestrator._switch_traffic()

        assert orchestrator.current_phase == MigrationPhase.TRAFFIC_SWITCHED
        assert "backup_schema" in orchestrator.state.metadata

    def test_rollback_drop_target(self, mock_connection):
        """Test rollback by dropping target schema."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.phase = MigrationPhase.DATA_SYNCING

        orchestrator._rollback_drop_target()

        assert orchestrator.current_phase == MigrationPhase.ROLLED_BACK
        cursor.execute.assert_called()

    def test_rollback_swap_back(self, mock_connection):
        """Test rollback by swapping schemas back."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.phase = MigrationPhase.TRAFFIC_SWITCHED
        orchestrator.state.metadata["backup_schema"] = "public_backup_123"

        orchestrator._rollback_swap_back()

        assert orchestrator.current_phase == MigrationPhase.ROLLED_BACK

    def test_rollback_no_backup_schema(self, mock_connection):
        """Test rollback fails without backup schema."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.phase = MigrationPhase.TRAFFIC_SWITCHED
        # No backup_schema in metadata

        orchestrator._rollback_swap_back()

        # Should not change phase
        assert orchestrator.current_phase == MigrationPhase.TRAFFIC_SWITCHED

    def test_manual_rollback(self, mock_connection):
        """Test manual rollback method."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.phase = MigrationPhase.DATA_SYNCING

        success = orchestrator.rollback()

        assert success is True
        assert orchestrator.current_phase == MigrationPhase.ROLLED_BACK

    def test_manual_rollback_unavailable(self, mock_connection):
        """Test manual rollback when not available."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.rollback_available = False

        success = orchestrator.rollback()

        assert success is False

    def test_cleanup_backup(self, mock_connection):
        """Test cleaning up backup schema."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)
        orchestrator.state.metadata["backup_schema"] = "public_backup_123"

        success = orchestrator.cleanup_backup()

        assert success is True
        assert orchestrator.state.rollback_available is False

    def test_cleanup_backup_no_schema(self, mock_connection):
        """Test cleanup when no backup schema."""
        conn, cursor = mock_connection
        orchestrator = BlueGreenOrchestrator(conn)

        success = orchestrator.cleanup_backup()

        assert success is False

    def test_execute_full_success(self, mock_connection):
        """Test successful full execution."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []  # No discrepancies
        config = BlueGreenConfig(
            traffic_switch_delay=0,
            skip_cleanup=True,
        )
        orchestrator = BlueGreenOrchestrator(conn, config)

        state = orchestrator.execute()

        assert state.phase == MigrationPhase.COMPLETE
        assert state.error is None
        assert state.started_at is not None
        assert state.completed_at is not None

    def test_execute_health_check_failure(self, mock_connection):
        """Test execution fails on health check failure."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []
        config = BlueGreenConfig(
            traffic_switch_delay=0,
            health_check_interval=0,
            health_check_retries=1,
        )
        orchestrator = BlueGreenOrchestrator(conn, config)
        orchestrator.add_health_check("fail", lambda: False)

        with pytest.raises(RuntimeError, match="Health checks failed"):
            orchestrator.execute()

        assert orchestrator.state.error is not None
        assert orchestrator.current_phase == MigrationPhase.ROLLED_BACK


class TestTrafficController:
    """Tests for TrafficController class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_init_no_clients(self):
        """Test initialization without external clients."""
        controller = TrafficController()
        assert controller.redis is None
        assert controller.feature_flags is None

    def test_init_with_redis(self):
        """Test initialization with Redis client."""
        redis = Mock()
        controller = TrafficController(redis_client=redis)
        assert controller.redis is redis

    def test_set_read_only_enabled(self, mock_connection):
        """Test enabling read-only mode."""
        conn, cursor = mock_connection
        controller = TrafficController()

        controller.set_read_only(conn, True)

        cursor.execute.assert_called()
        call_args = str(cursor.execute.call_args)
        assert "read_only" in call_args.lower()

    def test_set_read_only_disabled(self, mock_connection):
        """Test disabling read-only mode."""
        conn, cursor = mock_connection
        controller = TrafficController()

        controller.set_read_only(conn, False)

        cursor.execute.assert_called()

    def test_set_read_only_with_redis(self, mock_connection):
        """Test read-only mode with Redis."""
        conn, _ = mock_connection
        redis = Mock()
        controller = TrafficController(redis_client=redis)

        controller.set_read_only(conn, True)

        redis.set.assert_called_with("confiture:read_only", "1")

    def test_set_read_only_disable_with_redis(self, mock_connection):
        """Test disabling read-only with Redis."""
        conn, _ = mock_connection
        redis = Mock()
        controller = TrafficController(redis_client=redis)

        controller.set_read_only(conn, False)

        redis.delete.assert_called_with("confiture:read_only")

    def test_set_read_only_with_feature_flags(self, mock_connection):
        """Test read-only mode with feature flags."""
        conn, _ = mock_connection
        ff = Mock()
        controller = TrafficController(feature_flag_client=ff)

        controller.set_read_only(conn, True)

        ff.set.assert_called_with("database_read_only", True)

    def test_is_read_only_from_redis(self):
        """Test checking read-only from Redis."""
        redis = Mock()
        redis.get.return_value = "1"
        controller = TrafficController(redis_client=redis)

        assert controller.is_read_only() is True

    def test_is_read_only_from_redis_bytes(self):
        """Test checking read-only from Redis (bytes)."""
        redis = Mock()
        redis.get.return_value = b"1"
        controller = TrafficController(redis_client=redis)

        assert controller.is_read_only() is True

    def test_is_read_only_false(self):
        """Test read-only is False by default."""
        controller = TrafficController()
        assert controller.is_read_only() is False

    def test_get_active_connections(self, mock_connection):
        """Test getting active connections."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = [
            (123, "app", "myapp", "10.0.0.1", "active", None, None, None),
        ]
        cursor.description = [
            ("pid",),
            ("usename",),
            ("application_name",),
            ("client_addr",),
            ("state",),
            ("query_start",),
            ("wait_event_type",),
            ("wait_event",),
        ]
        controller = TrafficController()

        connections = controller.get_active_connections(conn)

        assert len(connections) == 1
        assert connections[0]["pid"] == 123
        assert connections[0]["application_name"] == "myapp"

    def test_drain_connections_success(self, mock_connection):
        """Test draining connections successfully."""
        conn, cursor = mock_connection
        # First call: active connections, second call: empty
        cursor.fetchall.side_effect = [
            [(123, "app", "myapp", "10.0.0.1", "active", None, None, None)],
            [],
        ]
        cursor.description = [
            ("pid",),
            ("usename",),
            ("application_name",),
            ("client_addr",),
            ("state",),
            ("query_start",),
            ("wait_event_type",),
            ("wait_event",),
        ]
        controller = TrafficController()

        success = controller.drain_connections(conn, timeout=5, check_interval=0.1)

        assert success is True

    def test_drain_connections_timeout(self, mock_connection):
        """Test draining connections timeout."""
        conn, cursor = mock_connection
        # Always return active connections
        cursor.fetchall.return_value = [
            (123, "app", "myapp", "10.0.0.1", "active", None, None, None),
        ]
        cursor.description = [
            ("pid",),
            ("usename",),
            ("application_name",),
            ("client_addr",),
            ("state",),
            ("query_start",),
            ("wait_event_type",),
            ("wait_event",),
        ]
        controller = TrafficController()

        success = controller.drain_connections(conn, timeout=0.2, check_interval=0.1)

        assert success is False

    def test_drain_connections_excludes_idle(self, mock_connection):
        """Test draining ignores idle connections."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = [
            (123, "app", "myapp", "10.0.0.1", "idle", None, None, None),
        ]
        cursor.description = [
            ("pid",),
            ("usename",),
            ("application_name",),
            ("client_addr",),
            ("state",),
            ("query_start",),
            ("wait_event_type",),
            ("wait_event",),
        ]
        controller = TrafficController()

        success = controller.drain_connections(conn, timeout=1, check_interval=0.1)

        assert success is True

    def test_terminate_connections(self, mock_connection):
        """Test terminating connections."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = [
            (123, "app", "myapp", "10.0.0.1", "active", None, None, None),
            (456, "app", "confiture", "10.0.0.1", "active", None, None, None),
        ]
        cursor.description = [
            ("pid",),
            ("usename",),
            ("application_name",),
            ("client_addr",),
            ("state",),
            ("query_start",),
            ("wait_event_type",),
            ("wait_event",),
        ]
        controller = TrafficController()

        terminated = controller.terminate_connections(conn)

        # Should terminate myapp but not confiture
        assert terminated == 1
