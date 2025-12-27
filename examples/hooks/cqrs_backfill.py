"""Example: CQRS Read Model Backfill Hook

This example shows how to use hooks to backfill read models after schema changes.

Common in event-sourced architectures where:
- w_* tables: Write model (transactional)
- r_* tables: Read model (denormalized for queries)

When modifying w_* tables, r_* tables need to be backfilled.
"""

import time

import psycopg

from confiture.core.hooks import Hook, HookContext, HookPhase, HookResult
from confiture.models.migration import Migration


class CaptureTableStatsHook(Hook):
    """Capture initial table statistics before DDL changes."""

    phase = HookPhase.BEFORE_DDL

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        """Capture row counts before schema changes for validation."""
        start = time.time()

        tables_to_monitor = ["customers", "orders", "order_items"]
        stats = {}

        with conn.cursor() as cursor:
            for table in tables_to_monitor:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                stats[f"{table}_initial_count"] = count

        context.set_stat("initial_stats", stats)

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats=stats,
        )


class BackfillCustomerLTVReadModelHook(Hook):
    """Backfill r_customer_lifetime_value after adding new discount column."""

    phase = HookPhase.AFTER_DDL

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:  # noqa: ARG002
        """
        Insert/update read model with lifetime value calculations.

        This hook assumes:
        - DDL has added a 'discount' column to orders
        - r_customer_lifetime_value read model exists
        - We need to recalculate LTV including discounts
        """
        start = time.time()

        with conn.cursor() as cursor:
            # Backfill read model with new LTV calculations
            cursor.execute(
                """
                INSERT INTO r_customer_lifetime_value (
                    customer_id,
                    lifetime_value,
                    total_orders,
                    total_discount_value,
                    updated_at
                )
                SELECT
                    c.id,
                    COALESCE(SUM(o.amount - COALESCE(o.discount, 0)), 0) as ltv,
                    COUNT(o.id) as total_orders,
                    COALESCE(SUM(o.discount), 0) as total_discount_value,
                    NOW()
                FROM customers c
                LEFT JOIN orders o ON c.id = o.customer_id
                GROUP BY c.id
                ON CONFLICT (customer_id) DO UPDATE SET
                    lifetime_value = EXCLUDED.lifetime_value,
                    total_orders = EXCLUDED.total_orders,
                    total_discount_value = EXCLUDED.total_discount_value,
                    updated_at = NOW()
                """
            )
            rows_affected = cursor.rowcount

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=rows_affected,
            execution_time_ms=elapsed_ms,
            stats={
                "read_model_updated": True,
                "rows_affected": rows_affected,
            },
        )


class ValidateDataConsistencyHook(Hook):
    """Validate that read model matches write model after backfill."""

    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:  # noqa: ARG002
        """Verify consistency between write and read models."""
        start = time.time()

        with conn.cursor() as cursor:
            # Check that all customers in w_customers have corresponding r_ entries
            cursor.execute(
                """
                SELECT COUNT(*) as missing_count
                FROM customers c
                LEFT JOIN r_customer_lifetime_value r ON c.id = r.customer_id
                WHERE r.customer_id IS NULL
                """
            )
            missing = cursor.fetchone()[0]

            if missing > 0:
                raise ValueError(
                    f"Consistency check failed: {missing} customers missing from read model"
                )

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            execution_time_ms=elapsed_ms,
            stats={"consistency_verified": True},
        )


class AddOrderDiscountColumn(Migration):
    """Add discount column to orders and backfill read model.

    Example migration showing hook integration:
    1. BEFORE_DDL: Capture initial statistics
    2. Add discount column to orders (DDL)
    3. AFTER_DDL: Backfill read model with new calculations
    4. AFTER_VALIDATION: Verify consistency between models
    """

    version = "042"
    name = "add_order_discount_column"

    # Define hooks for this migration
    before_ddl_hooks = [CaptureTableStatsHook()]
    after_ddl_hooks = [BackfillCustomerLTVReadModelHook()]
    after_validation_hooks = [ValidateDataConsistencyHook()]

    def up(self):
        """Add discount column to write model."""
        self.execute(
            """
            ALTER TABLE orders
            ADD COLUMN discount DECIMAL(5, 2) DEFAULT 0 NOT NULL
            """
        )

    def down(self):
        """Remove discount column."""
        self.execute("ALTER TABLE orders DROP COLUMN discount")


if __name__ == "__main__":
    """
    Usage example:

    # In your confiture migrations directory:
    # db/migrations/042_add_order_discount_column.py

    # Apply migration with hooks:
    # $ confiture migrate up
    # [cyan]⚡ Applying 042_add_order_discount_column...[/cyan] [green]✅[/green]
    #
    # Hooks executed:
    # - BEFORE_DDL: CaptureTableStatsHook (captured 5000 customers, 15000 orders)
    # - DDL: ALTER TABLE orders ADD COLUMN discount
    # - AFTER_DDL: BackfillCustomerLTVReadModelHook (updated 5000 rows)
    # - AFTER_VALIDATION: ValidateDataConsistencyHook (verified consistency)
    #
    # [green]✅ Successfully applied 1 migration(s)![/green]
    """
    print(__doc__)
