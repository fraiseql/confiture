"""Hook event categorization for Phase 6 - Refined Architecture.

Three categories with distinct semantics:
1. LIFECYCLE EVENTS - Fired before/after specific operations
2. STATE EVENTS - Fired when migration enters/leaves a state
3. ALERT EVENTS - Fired when metrics cross thresholds
"""

from enum import Enum


class HookPhase(Enum):
    """Lifecycle events - operation boundaries."""

    BEFORE_ANALYZE_SCHEMA = "before_analyze_schema"
    AFTER_ANALYZE_SCHEMA = "after_analyze_schema"
    BEFORE_DIFF_SCHEMAS = "before_diff_schemas"
    AFTER_DIFF_SCHEMAS = "after_diff_schemas"
    BEFORE_PLAN_MIGRATION = "before_plan_migration"
    AFTER_PLAN_MIGRATION = "after_plan_migration"
    BEFORE_DRY_RUN = "before_dry_run"
    AFTER_DRY_RUN = "after_dry_run"
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    BEFORE_VALIDATE = "before_validate"
    AFTER_VALIDATE = "after_validate"
    BEFORE_ROLLBACK = "before_rollback"
    AFTER_ROLLBACK = "after_rollback"


class HookEvent(Enum):
    """State change events - observable state transitions."""

    MIGRATION_STARTED = "migration_started"
    MIGRATION_PAUSED = "migration_paused"
    MIGRATION_RESUMED = "migration_resumed"
    MIGRATION_COMPLETED = "migration_completed"
    MIGRATION_FAILED = "migration_failed"
    MIGRATION_ROLLED_BACK = "migration_rolled_back"
    MIGRATION_CANCELLED = "migration_cancelled"


class HookAlert(Enum):
    """Threshold alerts - reactive to metric crossings."""

    DATA_ANOMALY_DETECTED = "data_anomaly_detected"
    LOCK_TIMEOUT_EXCEEDED = "lock_timeout_exceeded"
    PERFORMANCE_DEGRADED = "performance_degraded"
    MEMORY_THRESHOLD_EXCEEDED = "memory_threshold_exceeded"
    LONG_TRANSACTION_DETECTED = "long_transaction_detected"
    CONNECTION_POOL_EXHAUSTED = "connection_pool_exhausted"
