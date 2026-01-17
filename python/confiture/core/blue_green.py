"""Blue-green migration orchestration.

Provides utilities for zero-downtime database migrations using
blue-green deployment patterns with atomic schema swapping.
"""

import datetime
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MigrationPhase(Enum):
    """Phases of blue-green migration."""

    INIT = "init"
    SCHEMA_CREATED = "schema_created"
    DATA_SYNCING = "data_syncing"
    DATA_SYNCED = "data_synced"
    VERIFYING = "verifying"
    TRAFFIC_SWITCHING = "traffic_switching"
    TRAFFIC_SWITCHED = "traffic_switched"
    CLEANUP_PENDING = "cleanup_pending"
    COMPLETE = "complete"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class BlueGreenConfig:
    """Configuration for blue-green migration.

    Attributes:
        source_schema: Current production schema (default: public)
        target_schema: New schema to migrate to
        health_check_interval: Seconds between health check retries
        health_check_retries: Number of health check attempts
        sync_timeout: Maximum seconds for data sync
        traffic_switch_delay: Seconds to wait before switching
        skip_cleanup: If True, don't drop old schema
    """

    source_schema: str = "public"
    target_schema: str = "public_new"
    health_check_interval: float = 5.0
    health_check_retries: int = 3
    sync_timeout: int = 3600
    traffic_switch_delay: float = 10.0
    skip_cleanup: bool = False


@dataclass
class MigrationState:
    """Current state of blue-green migration.

    Tracks the migration progress and any errors that occur.
    """

    phase: MigrationPhase = MigrationPhase.INIT
    source_schema: str = "public"
    target_schema: str = "public_new"
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    rollback_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "phase": self.phase.value,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "rollback_available": self.rollback_available,
            "metadata": self.metadata,
        }


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    passed: bool
    message: str | None = None
    duration_ms: int = 0


class BlueGreenOrchestrator:
    """Orchestrate blue-green database migrations.

    Provides a structured approach to zero-downtime migrations:
    1. Create target schema
    2. Sync data (via FDW or other mechanism)
    3. Verify data integrity
    4. Run health checks
    5. Atomic schema swap
    6. Cleanup (optional)

    Example:
        >>> config = BlueGreenConfig(target_schema="public_v2")
        >>> orchestrator = BlueGreenOrchestrator(conn, config)
        >>> orchestrator.add_health_check("api_health", check_api)
        >>> state = orchestrator.execute()
        >>> print(f"Migration: {state.phase.value}")
    """

    def __init__(self, connection: Any, config: BlueGreenConfig | None = None):
        """Initialize orchestrator.

        Args:
            connection: Database connection
            config: Migration configuration
        """
        self.connection = connection
        self.config = config or BlueGreenConfig()
        self.state = MigrationState(
            source_schema=self.config.source_schema,
            target_schema=self.config.target_schema,
        )
        self._health_checks: list[tuple[str, Callable[[], bool]]] = []
        self._on_phase_change: list[Callable[[MigrationPhase, MigrationPhase], None]] = []
        self._data_sync_fn: Callable[[], None] | None = None

    @property
    def current_phase(self) -> MigrationPhase:
        """Get current migration phase."""
        return self.state.phase

    def add_health_check(self, name: str, check: Callable[[], bool]) -> None:
        """Add a health check function.

        Health checks are run before traffic switch. All must pass.

        Args:
            name: Name for this health check
            check: Function returning True if healthy

        Example:
            >>> def check_api():
            ...     response = requests.get("http://localhost/health")
            ...     return response.status_code == 200
            >>> orchestrator.add_health_check("api", check_api)
        """
        self._health_checks.append((name, check))

    def on_phase_change(self, callback: Callable[[MigrationPhase, MigrationPhase], None]) -> None:
        """Register callback for phase changes.

        Args:
            callback: Function called with (old_phase, new_phase)

        Example:
            >>> def log_phase(old, new):
            ...     print(f"Phase changed: {old.value} -> {new.value}")
            >>> orchestrator.on_phase_change(log_phase)
        """
        self._on_phase_change.append(callback)

    def set_data_sync_function(self, fn: Callable[[], None]) -> None:
        """Set custom data sync function.

        By default, sync is a placeholder. Set this to integrate
        with your data sync mechanism (FDW, pg_dump, etc.).

        Args:
            fn: Function to sync data from source to target
        """
        self._data_sync_fn = fn

    def _set_phase(self, phase: MigrationPhase) -> None:
        """Update phase and notify callbacks."""
        old_phase = self.state.phase
        self.state.phase = phase
        logger.info(f"Phase: {old_phase.value} -> {phase.value}")

        for callback in self._on_phase_change:
            try:
                callback(old_phase, phase)
            except Exception as e:
                logger.warning(f"Phase callback failed: {e}")

    def execute(self) -> MigrationState:
        """Execute full blue-green migration.

        Returns:
            MigrationState with final status

        Raises:
            RuntimeError: If migration fails and cannot be rolled back
        """
        self.state.started_at = datetime.datetime.now(datetime.UTC).isoformat()

        try:
            self._create_target_schema()
            self._sync_data()
            self._verify_sync()

            health_results = self._run_health_checks()
            if not all(r.passed for r in health_results):
                failed = [r.name for r in health_results if not r.passed]
                raise RuntimeError(f"Health checks failed: {', '.join(failed)}")

            self._switch_traffic()

            if not self.config.skip_cleanup:
                self._cleanup()

            self.state.completed_at = datetime.datetime.now(datetime.UTC).isoformat()
            self._set_phase(MigrationPhase.COMPLETE)

        except Exception as e:
            self.state.error = str(e)
            self._set_phase(MigrationPhase.FAILED)
            logger.error(f"Migration failed: {e}")
            self._attempt_rollback()
            raise

        return self.state

    def _create_target_schema(self) -> None:
        """Create target schema for new version."""
        with self.connection.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.target_schema}")
        self.connection.commit()
        self._set_phase(MigrationPhase.SCHEMA_CREATED)
        logger.info(f"Created schema: {self.config.target_schema}")

    def _sync_data(self) -> None:
        """Sync data from source to target schema."""
        self._set_phase(MigrationPhase.DATA_SYNCING)

        if self._data_sync_fn:
            self._data_sync_fn()
        else:
            logger.info(
                "No data sync function set. "
                "Use set_data_sync_function() to integrate with FDW or other sync."
            )

        self._set_phase(MigrationPhase.DATA_SYNCED)

    def _verify_sync(self) -> None:
        """Verify data sync is complete."""
        self._set_phase(MigrationPhase.VERIFYING)

        discrepancies = self._compare_schemas()
        if discrepancies:
            for table, diff in discrepancies.items():
                logger.warning(
                    f"Row count mismatch in {table}: "
                    f"source={diff['source']}, target={diff['target']}"
                )
            self.state.metadata["sync_discrepancies"] = discrepancies

        logger.info("Data sync verification complete")

    def _compare_schemas(self) -> dict[str, dict[str, int]]:
        """Compare row counts between schemas.

        Returns:
            Dictionary of tables with mismatched counts
        """
        discrepancies: dict[str, dict[str, int]] = {}

        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT schemaname, relname, n_live_tup
                FROM pg_stat_user_tables
                WHERE schemaname IN (%s, %s)
                ORDER BY relname, schemaname
            """,
                (self.config.source_schema, self.config.target_schema),
            )

            stats: dict[str, dict[str, int]] = {}
            for row in cur.fetchall():
                schema, table, count = row
                if table not in stats:
                    stats[table] = {}
                stats[table][schema] = count or 0

            for table, counts in stats.items():
                source_count = counts.get(self.config.source_schema, 0)
                target_count = counts.get(self.config.target_schema, 0)

                if source_count != target_count:
                    discrepancies[table] = {
                        "source": source_count,
                        "target": target_count,
                    }

        return discrepancies

    def _run_health_checks(self) -> list[HealthCheckResult]:
        """Run all health checks with retries.

        Returns:
            List of health check results
        """
        if not self._health_checks:
            logger.info("No health checks configured, proceeding")
            return []

        results: list[HealthCheckResult] = []

        for attempt in range(self.config.health_check_retries):
            results = []
            all_passed = True

            for name, check in self._health_checks:
                start_time = time.perf_counter()
                try:
                    passed = check()
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    results.append(
                        HealthCheckResult(
                            name=name,
                            passed=passed,
                            duration_ms=duration_ms,
                        )
                    )
                    if not passed:
                        logger.warning(f"Health check '{name}' failed")
                        all_passed = False
                except Exception as e:
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    results.append(
                        HealthCheckResult(
                            name=name,
                            passed=False,
                            message=str(e),
                            duration_ms=duration_ms,
                        )
                    )
                    logger.warning(f"Health check '{name}' error: {e}")
                    all_passed = False

            if all_passed:
                logger.info(f"All {len(self._health_checks)} health checks passed")
                break

            if attempt < self.config.health_check_retries - 1:
                logger.info(
                    f"Retrying health checks in {self.config.health_check_interval}s "
                    f"(attempt {attempt + 2}/{self.config.health_check_retries})"
                )
                time.sleep(self.config.health_check_interval)

        self.state.metadata["health_check_results"] = [r.__dict__ for r in results]
        return results

    def _switch_traffic(self) -> None:
        """Switch traffic by renaming schemas atomically."""
        self._set_phase(MigrationPhase.TRAFFIC_SWITCHING)

        if self.config.traffic_switch_delay > 0:
            logger.info(f"Waiting {self.config.traffic_switch_delay}s before traffic switch...")
            time.sleep(self.config.traffic_switch_delay)

        backup_schema = f"{self.config.source_schema}_backup_{int(time.time())}"

        with self.connection.cursor() as cur:
            # Atomic schema swap using a single transaction
            cur.execute(
                f"""
                ALTER SCHEMA {self.config.source_schema} RENAME TO {backup_schema};
                ALTER SCHEMA {self.config.target_schema}
                    RENAME TO {self.config.source_schema};
            """
            )
        self.connection.commit()

        self.state.metadata["backup_schema"] = backup_schema
        self.state.rollback_available = True
        self._set_phase(MigrationPhase.TRAFFIC_SWITCHED)
        logger.info(f"Traffic switched. Old schema backed up as: {backup_schema}")

    def _cleanup(self) -> None:
        """Mark cleanup as pending (actual cleanup is manual)."""
        self._set_phase(MigrationPhase.CLEANUP_PENDING)

        backup_schema = self.state.metadata.get("backup_schema")
        if backup_schema:
            logger.info(f"Old schema preserved as: {backup_schema}")
            logger.info(
                f"To remove: DROP SCHEMA {backup_schema} CASCADE; "
                "or run 'confiture migrate cleanup'"
            )

    def _attempt_rollback(self) -> None:
        """Attempt to rollback on failure."""
        if not self.state.rollback_available:
            logger.warning("Rollback not available from current state")
            return

        phase = self.state.phase

        if phase in (
            MigrationPhase.INIT,
            MigrationPhase.SCHEMA_CREATED,
            MigrationPhase.DATA_SYNCING,
            MigrationPhase.DATA_SYNCED,
            MigrationPhase.VERIFYING,
            MigrationPhase.FAILED,
        ):
            # Safe to rollback - just drop target schema
            self._rollback_drop_target()

        elif phase == MigrationPhase.TRAFFIC_SWITCHED:
            # Need to swap schemas back
            self._rollback_swap_back()

        else:
            logger.warning(f"Cannot auto-rollback from phase: {phase.value}")

    def _rollback_drop_target(self) -> None:
        """Rollback by dropping target schema."""
        try:
            with self.connection.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {self.config.target_schema} CASCADE")
            self.connection.commit()
            self._set_phase(MigrationPhase.ROLLED_BACK)
            logger.info(f"Rolled back: dropped {self.config.target_schema}")
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            self.state.rollback_available = False

    def _rollback_swap_back(self) -> None:
        """Rollback by swapping schemas back."""
        backup_schema = self.state.metadata.get("backup_schema")
        if not backup_schema:
            logger.error("Cannot rollback: backup schema not found")
            return

        try:
            temp_schema = f"_rollback_temp_{int(time.time())}"
            with self.connection.cursor() as cur:
                # Swap back: current -> temp, backup -> current
                cur.execute(
                    f"""
                    ALTER SCHEMA {self.config.source_schema} RENAME TO {temp_schema};
                    ALTER SCHEMA {backup_schema} RENAME TO {self.config.source_schema};
                    DROP SCHEMA {temp_schema} CASCADE;
                """
                )
            self.connection.commit()
            self._set_phase(MigrationPhase.ROLLED_BACK)
            logger.info("Rolled back: restored original schema")
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            self.state.rollback_available = False

    def rollback(self) -> bool:
        """Manually trigger rollback.

        Returns:
            True if rollback succeeded
        """
        if not self.state.rollback_available:
            logger.warning("Rollback not available")
            return False

        self._attempt_rollback()
        return self.state.phase == MigrationPhase.ROLLED_BACK

    def cleanup_backup(self) -> bool:
        """Remove the backup schema.

        Returns:
            True if cleanup succeeded
        """
        backup_schema = self.state.metadata.get("backup_schema")
        if not backup_schema:
            logger.warning("No backup schema to clean up")
            return False

        try:
            with self.connection.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {backup_schema} CASCADE")
            self.connection.commit()
            self.state.rollback_available = False
            logger.info(f"Cleaned up backup schema: {backup_schema}")
            return True
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return False


class TrafficController:
    """Control application traffic during migration.

    Provides utilities for managing read-only mode and draining
    connections during blue-green migrations.

    Example:
        >>> controller = TrafficController()
        >>> controller.set_read_only(conn, True)
        >>> # ... perform migration ...
        >>> controller.set_read_only(conn, False)
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        feature_flag_client: Any | None = None,
    ):
        """Initialize traffic controller.

        Args:
            redis_client: Optional Redis client for state storage
            feature_flag_client: Optional feature flag client
        """
        self.redis = redis_client
        self.feature_flags = feature_flag_client
        self._read_only = False

    def set_read_only(self, connection: Any, enabled: bool) -> None:
        """Enable/disable read-only mode.

        When enabled, sets the database connection to read-only
        and optionally updates Redis/feature flags.

        Args:
            connection: Database connection
            enabled: True to enable read-only mode
        """
        self._read_only = enabled

        # Set database connection to read-only transaction
        if enabled:
            with connection.cursor() as cur:
                cur.execute("SET default_transaction_read_only = ON")
            connection.commit()
            logger.info("Database connection set to read-only")
        else:
            with connection.cursor() as cur:
                cur.execute("SET default_transaction_read_only = OFF")
            connection.commit()
            logger.info("Database connection set to read-write")

        # Update external state stores
        if self.redis:
            if enabled:
                self.redis.set("confiture:read_only", "1")
            else:
                self.redis.delete("confiture:read_only")
            logger.info(f"Redis read_only flag: {enabled}")

        if self.feature_flags:
            self.feature_flags.set("database_read_only", enabled)
            logger.info(f"Feature flag database_read_only: {enabled}")

    def is_read_only(self) -> bool:
        """Check if read-only mode is enabled.

        Returns:
            True if read-only mode is active
        """
        if self.redis:
            value = self.redis.get("confiture:read_only")
            return value == "1" or value == b"1"
        return self._read_only

    def get_active_connections(self, connection: Any) -> list[dict[str, Any]]:
        """Get list of active database connections.

        Args:
            connection: Database connection

        Returns:
            List of connection info dictionaries
        """
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pid,
                    usename,
                    application_name,
                    client_addr,
                    state,
                    query_start,
                    wait_event_type,
                    wait_event
                FROM pg_stat_activity
                WHERE datname = current_database()
                AND pid != pg_backend_pid()
                ORDER BY query_start DESC
            """
            )

            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    def drain_connections(
        self,
        connection: Any,
        timeout: int = 30,
        check_interval: float = 1.0,
        exclude_apps: list[str] | None = None,
    ) -> bool:
        """Wait for active connections to drain.

        Args:
            connection: Database connection
            timeout: Maximum seconds to wait
            check_interval: Seconds between checks
            exclude_apps: Application names to exclude from check

        Returns:
            True if all connections drained within timeout
        """
        exclude_apps = exclude_apps or ["confiture"]
        start_time = time.time()

        logger.info(f"Draining connections (timeout={timeout}s)...")

        while time.time() - start_time < timeout:
            active = self.get_active_connections(connection)

            # Filter out excluded applications
            active = [
                c
                for c in active
                if c.get("application_name") not in exclude_apps and c.get("state") != "idle"
            ]

            if not active:
                logger.info("All connections drained")
                return True

            logger.info(f"Waiting for {len(active)} active connections...")
            time.sleep(check_interval)

        logger.warning("Timeout waiting for connections to drain")
        return False

    def terminate_connections(
        self,
        connection: Any,
        exclude_apps: list[str] | None = None,
    ) -> int:
        """Terminate active connections (use with caution).

        Args:
            connection: Database connection
            exclude_apps: Application names to exclude

        Returns:
            Number of connections terminated
        """
        exclude_apps = exclude_apps or ["confiture"]
        terminated = 0

        active = self.get_active_connections(connection)

        with connection.cursor() as cur:
            for conn_info in active:
                app_name = conn_info.get("application_name", "")
                if app_name in exclude_apps:
                    continue

                pid = conn_info["pid"]
                try:
                    cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
                    terminated += 1
                    logger.info(f"Terminated connection: pid={pid}, app={app_name}")
                except Exception as e:
                    logger.warning(f"Failed to terminate pid={pid}: {e}")

        connection.commit()
        logger.info(f"Terminated {terminated} connections")
        return terminated
