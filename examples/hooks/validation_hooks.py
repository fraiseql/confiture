"""Example: Data Validation Hooks

This example shows how to use hooks to validate data before, during, and after migrations.

Useful for:
- Pre-flight checks (backup exists, database responsive, etc.)
- Data quality validation (no null values in critical columns)
- Constraint verification (referential integrity, uniqueness)
- Performance validation (query performance before/after)
"""

import time

import psycopg

from confiture.core.hooks import Hook, HookContext, HookPhase, HookResult
from confiture.models.migration import Migration


class VerifyDatabaseHealthHook(Hook):
    """Check database is responsive and has sufficient space."""

    phase = HookPhase.BEFORE_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Verify database health before migration."""
        start = time.time()

        with conn.cursor() as cursor:
            # Check database connectivity
            cursor.execute("SELECT now()")
            db_time = cursor.fetchone()[0]

            # Check available space in tablespace (PostgreSQL specific)
            cursor.execute(
                """
                SELECT
                    spcname as tablespace,
                    pg_size_pretty(pg_tablespace_size(oid)) as size
                FROM pg_tablespace
                WHERE spcname = 'pg_default'
                """
            )
            space_info = cursor.fetchone()

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats={
                "database_responsive": True,
                "database_time": str(db_time),
                "tablespace": space_info[0] if space_info else "unknown",
                "space_available": space_info[1] if space_info else "unknown",
            },
        )


class ValidateReferentialIntegrityHook(Hook):
    """Check referential integrity before schema changes."""

    phase = HookPhase.BEFORE_DDL

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Validate no orphaned foreign keys exist."""
        start = time.time()

        with conn.cursor() as cursor:
            # Check for orphaned order items (orders with missing customers)
            cursor.execute(
                """
                SELECT COUNT(*) as orphaned_count
                FROM order_items oi
                WHERE NOT EXISTS (
                    SELECT 1 FROM orders o WHERE o.id = oi.order_id
                )
                """
            )
            orphaned = cursor.fetchone()[0]

            if orphaned > 0:
                raise ValueError(
                    f"Data integrity error: {orphaned} orphaned order items found. "
                    "Please fix data before migration."
                )

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats={"referential_integrity_verified": True},
        )


class ValidateDataQualityHook(Hook):
    """Check data quality in critical columns."""

    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Validate no null values in required columns."""
        start = time.time()

        with conn.cursor() as cursor:
            # Check for null values in required columns
            cursor.execute(
                """
                SELECT COUNT(*) as null_count
                FROM customers
                WHERE email IS NULL
                OR name IS NULL
                OR created_at IS NULL
                """
            )
            null_count = cursor.fetchone()[0]

            if null_count > 0:
                raise ValueError(
                    f"Data quality issue: {null_count} customers with null required fields"
                )

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats={"data_quality_verified": True},
        )


class MeasureQueryPerformanceHook(Hook):
    """Measure query performance to detect regression."""

    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Measure execution time of critical queries."""
        start = time.time()

        # Critical query that should stay fast
        query = """
            SELECT c.id, c.name, COUNT(o.id) as order_count
            FROM customers c
            LEFT JOIN orders o ON c.id = o.customer_id
            GROUP BY c.id, c.name
        """

        with conn.cursor() as cursor:
            query_start = time.perf_counter()
            cursor.execute(query)
            results = cursor.fetchall()
            query_time_ms = int((time.perf_counter() - query_start) * 1000)

            # Alert if query got significantly slower
            threshold_ms = 1000  # 1 second
            if query_time_ms > threshold_ms:
                raise PerformanceWarning(
                    f"Query took {query_time_ms}ms (threshold: {threshold_ms}ms). "
                    "Schema changes may have degraded performance."
                )

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=len(results),
            execution_time_ms=elapsed_ms,
            stats={
                "query_time_ms": query_time_ms,
                "rows_returned": len(results),
                "performance_acceptable": query_time_ms < 1000,
            },
        )


class NotifyOnErrorHook(Hook):
    """Send notification when migration fails."""

    phase = HookPhase.ON_ERROR

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Log error details for ops team."""
        start = time.time()

        # In real scenario, this would send to monitoring system
        error_context = {
            "migration": context.migration_name,
            "version": context.migration_version,
            "direction": context.direction,
            "timestamp": time.time(),
        }

        # Example: log to monitoring system
        # monitoring_client.send_alert("migration_failed", error_context)

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats={
                "notification_sent": True,
                "error_context": error_context,
            },
        )


class PerformanceWarning(Exception):
    """Raised when performance threshold exceeded."""

    pass


class AddOrderStatusIndex(Migration):
    """Add index to orders.status for query performance.

    Example migration showing comprehensive validation hooks:
    1. BEFORE_VALIDATION: Health check
    2. BEFORE_DDL: Verify referential integrity
    3. Create index (DDL)
    4. AFTER_VALIDATION: Verify data quality and measure performance
    5. ON_ERROR: Notify if anything fails
    """

    version = "050"
    name = "add_order_status_index"

    before_validation_hooks = [VerifyDatabaseHealthHook()]
    before_ddl_hooks = [ValidateReferentialIntegrityHook()]
    after_validation_hooks = [
        ValidateDataQualityHook(),
        MeasureQueryPerformanceHook(),
    ]
    error_hooks = [NotifyOnErrorHook()]

    def up(self):
        """Create index on status column."""
        self.execute(
            """
            CREATE INDEX idx_orders_status
            ON orders(status)
            WHERE status IS NOT NULL
            """
        )

    def down(self):
        """Drop the index."""
        self.execute("DROP INDEX IF EXISTS idx_orders_status")


if __name__ == "__main__":
    """
    Usage example:

    # Apply migration with validation hooks:
    # $ confiture migrate up

    # Output:
    # [cyan]⚡ Applying 050_add_order_status_index...[/cyan] [green]✅[/green]
    #
    # Hooks executed:
    # - BEFORE_VALIDATION: VerifyDatabaseHealthHook (responsive, 10GB available)
    # - BEFORE_DDL: ValidateReferentialIntegrityHook (verified)
    # - DDL: CREATE INDEX idx_orders_status
    # - AFTER_VALIDATION:
    #   - ValidateDataQualityHook (verified)
    #   - MeasureQueryPerformanceHook (125ms, within threshold)
    #
    # [green]✅ Successfully applied 1 migration(s)![/green]
    """
    print(__doc__)
