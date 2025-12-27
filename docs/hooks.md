# Migration Hooks Guide

**Phase 4 Feature 1**: Execute custom code before and after database migrations

---

## Overview

Migration hooks allow you to execute custom Python code during the migration lifecycle. This enables:

- **CQRS Read Model Backfilling**: Sync read models after schema changes
- **Data Validation**: Verify data consistency before/after migrations
- **Pre-flight Checks**: Ensure database health before structural changes
- **Cleanup Operations**: Remove temporary data or indexes after migrations
- **Error Handling**: Execute cleanup or notifications if migrations fail

---

## Hook Phases

Confiture executes hooks in 6 distinct phases during migration execution:

### 1. BEFORE_VALIDATION Phase

**When**: Before any migration work begins

**Use Cases**:
- Health checks (database responsive, sufficient disk space)
- Backup verification
- Lock acquisition
- Connection pool warmup

```python
class PreFlightCheckHook(Hook):
    phase = HookPhase.BEFORE_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        # Verify database is healthy
        cursor = conn.cursor()
        cursor.execute("SELECT NOW()")
        cursor.fetchone()

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            execution_time_ms=10,
            stats={"database_healthy": True}
        )
```

### 2. BEFORE_DDL Phase

**When**: After validation, before structural changes

**Use Cases**:
- Capture initial row counts
- Store current index definitions
- Disable triggers temporarily
- Prepare shadow tables for data migration

```python
class CaptureStatsHook(Hook):
    phase = HookPhase.BEFORE_DDL

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]

        context.set_stat("initial_user_count", count)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=0,
            stats={"user_count": count}
        )
```

### 3. AFTER_DDL Phase

**When**: After structural changes (migrations up/down), before validation

**Use Cases**:
- Backfill new columns
- Update denormalized tables
- Rebuild materialized views
- Sync read models (CQRS)
- Create computed columns

```python
class BackfillReadModelHook(Hook):
    phase = HookPhase.AFTER_DDL

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        with conn.cursor() as cursor:
            # Backfill r_* read model after w_* changes
            cursor.execute("""
                INSERT INTO r_user_summary (user_id, order_count, total_spent)
                SELECT u.id, COUNT(o.id), SUM(o.amount)
                FROM users u
                LEFT JOIN orders o ON u.id = o.user_id
                GROUP BY u.id
                ON CONFLICT (user_id) DO UPDATE SET
                    order_count = EXCLUDED.order_count,
                    total_spent = EXCLUDED.total_spent
            """)
            rows = cursor.rowcount

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=rows,
            stats={"rows_backfilled": rows}
        )
```

### 4. AFTER_VALIDATION Phase

**When**: After DDL, before final cleanup

**Use Cases**:
- Verify data integrity
- Check constraint compliance
- Validate referential integrity
- Measure query performance
- Log migration metrics

```python
class ValidateConsistencyHook(Hook):
    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        with conn.cursor() as cursor:
            # Verify all customers have read model entries
            cursor.execute("""
                SELECT COUNT(*) FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM r_user_summary r WHERE r.user_id = u.id
                )
            """)
            missing = cursor.fetchone()[0]

            if missing > 0:
                raise ValueError(f"{missing} users missing from read model")

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            stats={"consistency_verified": True}
        )
```

### 5. CLEANUP Phase

**When**: After validation, before transaction commit

**Use Cases**:
- Drop temporary tables
- Reset sequences
- Rebuild statistics (ANALYZE)
- Clear caches
- Remove temporary indexes

```python
class CleanupTemporaryDataHook(Hook):
    phase = HookPhase.CLEANUP

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        with conn.cursor() as cursor:
            # Drop temporary staging table
            cursor.execute("DROP TABLE IF EXISTS temp_user_migration")

            # Refresh statistics
            cursor.execute("ANALYZE users")

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            stats={"cleanup_completed": True}
        )
```

### 6. ON_ERROR Phase

**When**: Only if migration or previous phases fail

**Use Cases**:
- Send alerts/notifications
- Log detailed error context
- Trigger automated remediation
- Clean up partial state
- Notify ops team

```python
class AlertOnErrorHook(Hook):
    phase = HookPhase.ON_ERROR

    def execute(self, conn: psycopg.Connection, context: HookContext) -> HookResult:
        # Send alert to monitoring system
        alert_msg = f"Migration {context.migration_version} failed"
        # monitoring_client.send_alert(alert_msg, context.stats)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            stats={"alert_sent": True}
        )
```

---

## Hook Context

Hooks receive a `HookContext` object that provides migration metadata and allows hooks to exchange data:

```python
class HookContext:
    migration_name: str        # e.g., "add_users_table"
    migration_version: str     # e.g., "001"
    direction: str            # "forward" or "backward"
    stats: dict[str, Any]     # Shared statistics dict

    def get_stat(key: str) -> Any:
        """Get a stored statistic from previous hooks"""

    def set_stat(key: str, value: Any) -> None:
        """Store a statistic for later hooks"""
```

### Example: Sharing Data Between Hooks

```python
# BEFORE_DDL hook captures initial count
class CaptureCountHook(Hook):
    phase = HookPhase.BEFORE_DDL

    def execute(self, conn, context):
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]

        context.set_stat("initial_count", count)  # Store for later

        return HookResult(...)

# AFTER_VALIDATION hook retrieves and validates
class ValidateCountHook(Hook):
    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn, context):
        initial = context.get_stat("initial_count")  # Retrieve

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        final = cursor.fetchone()[0]

        if final < initial:
            raise ValueError("Data was lost during migration!")

        return HookResult(...)
```

---

## Defining Hooks in Migrations

Add hook attributes to your migration class:

```python
from confiture.models.migration import Migration
from confiture.core.hooks import Hook, HookPhase

class MyHook(Hook):
    phase = HookPhase.AFTER_DDL

    def execute(self, conn, context):
        # Hook implementation
        pass

class MyMigration(Migration):
    version = "001"
    name = "create_users"

    # Define hooks (all optional, default to empty lists)
    before_validation_hooks = [PreFlightCheckHook()]
    before_ddl_hooks = [CaptureStatsHook()]
    after_ddl_hooks = [BackfillReadModelHook()]
    after_validation_hooks = [ValidateConsistencyHook()]
    cleanup_hooks = [CleanupTemporaryDataHook()]
    error_hooks = [AlertOnErrorHook()]

    def up(self):
        self.execute("CREATE TABLE users (...)")

    def down(self):
        self.execute("DROP TABLE users")
```

---

## Hook Execution Flow

When you run `confiture migrate up`, hooks execute in this order:

```
┌──────────────────────────────────────────────────────────┐
│              Migration: 001_create_users                 │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ 1️⃣  BEFORE_VALIDATION Phase                              │
│    └─ PreFlightCheckHook                                │
│       └─ Check database health, disk space, locks  ✅   │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 2️⃣  BEFORE_DDL Phase                                     │
│    └─ CaptureStatsHook                                  │
│       └─ Save initial row counts, index definitions ✅  │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 3️⃣  [DDL EXECUTION]                                      │
│    └─ migration.up()                                    │
│       └─ CREATE TABLE users (...)                       │
│       └─ ALTER TABLE ADD COLUMN                         │
│       └─ CREATE INDEX ... ✅                            │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 4️⃣  AFTER_DDL Phase                                      │
│    └─ BackfillReadModelHook                             │
│       └─ INSERT INTO read_model SELECT...               │
│       └─ UPDATE denormalized_table...                   │
│       └─ Populate new columns ✅                        │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 5️⃣  AFTER_VALIDATION Phase                               │
│    └─ ValidateConsistencyHook                           │
│       └─ Check data integrity, FK constraints ✅        │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 6️⃣  CLEANUP Phase                                        │
│    └─ CleanupTemporaryDataHook                          │
│       └─ DROP temporary tables                          │
│       └─ ANALYZE indexes                                │
│       └─ Reset sequences ✅                             │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 7️⃣  Commit Transaction                                   │
│    └─ All changes saved to database                     │
│    └─ Migration recorded in migration_history ✅        │
└──────────────────────────────────────────────────────────┘
                           ↓
                   ✅ SUCCESS
```

### Error Handling

If any hook fails:

```
┌──────────────────────────────────────────────────────────┐
│ 3️⃣  [DDL EXECUTION]                                      │
│    └─ migration.up()                                    │
│       └─ CREATE TABLE users (...) ✅                    │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 4️⃣  AFTER_DDL Phase                                      │
│    └─ BackfillReadModelHook                             │
│       └─ INSERT INTO read_model SELECT...               │
│       └─ ❌ ERROR: SQL syntax error!                    │
└──────────────────────────────────────────────────────────┘
                           ↓
       ⚠️  TRANSACTION ROLLBACK TRIGGERED
                           ↓
┌──────────────────────────────────────────────────────────┐
│ ROLLBACK Phase                                           │
│ ├─ Undo DDL EXECUTION                                   │
│ ├─ Release savepoints                                   │
│ ├─ Reset transaction to start                           │
│ └─ All changes discarded ✅                             │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 6️⃣  ON_ERROR Phase                                       │
│    └─ AlertOnErrorHook                                  │
│       └─ Send alert to monitoring system                │
│       └─ Log error details                              │
│       └─ Notify ops team ✅                             │
└──────────────────────────────────────────────────────────┘
                           ↓
                   ❌ MIGRATION FAILED
                   Database unchanged
```

---

## Creating Custom Hooks

### 1. Extend the Hook base class

```python
from confiture.core.hooks import Hook, HookPhase, HookResult, HookContext
import psycopg

class MyCustomHook(Hook):
    """Description of what this hook does."""

    phase = HookPhase.AFTER_DDL  # Choose your phase

    def execute(self,
                conn: psycopg.Connection,
                context: HookContext) -> HookResult:
        """
        Execute hook logic.

        Args:
            conn: Database connection
            context: Migration context (metadata + stats)

        Returns:
            HookResult with execution details

        Raises:
            Any exception to fail the migration
        """
        start = time.time()

        # Your hook logic here
        with conn.cursor() as cursor:
            cursor.execute("SELECT ...")

        elapsed_ms = int((time.time() - start) * 1000)

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=100,  # How many rows were affected
            execution_time_ms=elapsed_ms,
            stats={
                "key": "value",  # Any metrics you want to track
            }
        )
```

### 2. Return a HookResult

```python
from confiture.core.hooks import HookResult

result = HookResult(
    phase="AFTER_DDL",           # HookPhase.AFTER_DDL.name
    hook_name="BackfillHook",    # self.__class__.__name__
    rows_affected=5000,          # Rows modified by this hook
    execution_time_ms=234,       # Execution time in milliseconds
    stats={                       # Optional metrics dict
        "backfilled": True,
        "cache_invalidated": True,
    }
)
```

### 3. Use in Migration

```python
class MyMigration(Migration):
    version = "010"
    name = "complex_schema_change"
    after_ddl_hooks = [MyCustomHook()]

    def up(self):
        # DDL changes
        self.execute("ALTER TABLE ...")

    def down(self):
        self.execute("ALTER TABLE ...")
```

---

## Real-World Examples

### Example 1: CQRS Read Model Backfill

```python
class BackfillCustomerLTVReadModel(Hook):
    """Backfill read model after adding discount column."""

    phase = HookPhase.AFTER_DDL

    def execute(self, conn, context):
        start = time.time()

        with conn.cursor() as cursor:
            # Calculate lifetime value including new discount
            cursor.execute("""
                INSERT INTO r_customer_ltv (customer_id, ltv, updated_at)
                SELECT
                    c.id,
                    COALESCE(SUM(o.amount - COALESCE(o.discount, 0)), 0),
                    NOW()
                FROM customers c
                LEFT JOIN orders o ON c.id = o.customer_id
                GROUP BY c.id
                ON CONFLICT (customer_id) DO UPDATE SET
                    ltv = EXCLUDED.ltv,
                    updated_at = NOW()
            """)
            rows = cursor.rowcount

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=rows,
            execution_time_ms=int((time.time() - start) * 1000),
            stats={"model_backfilled": True}
        )
```

### Example 2: Data Validation

```python
class ValidateDataIntegrity(Hook):
    """Ensure no data was lost during migration."""

    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn, context):
        # Retrieve count from BEFORE_DDL hook
        initial = context.get_stat("initial_count")

        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users")
            final = cursor.fetchone()[0]

        if final < initial:
            raise ValueError(
                f"Data loss detected: {initial} → {final} rows"
            )

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            stats={"data_integrity_verified": True}
        )
```

### Example 3: Performance Monitoring

```python
class MeasureQueryPerformance(Hook):
    """Verify migration didn't degrade query performance."""

    phase = HookPhase.AFTER_VALIDATION

    def execute(self, conn, context):
        query = "SELECT * FROM orders WHERE status = 'pending'"

        with conn.cursor() as cursor:
            start = time.perf_counter()
            cursor.execute(query)
            cursor.fetchall()
            elapsed_ms = int((time.perf_counter() - start) * 1000)

        if elapsed_ms > 1000:  # Threshold: 1 second
            raise PerformanceWarning(
                f"Query took {elapsed_ms}ms (threshold: 1000ms)"
            )

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            execution_time_ms=elapsed_ms,
            stats={"query_time_ms": elapsed_ms}
        )
```

---

## Testing Hooks

Write tests for your hooks using pytest:

```python
import pytest
from confiture.core.hooks import HookContext, HookPhase
from my_hooks import BackfillReadModelHook

@pytest.fixture
def migration_context():
    return HookContext(
        migration_name="add_discount",
        migration_version="042",
        direction="forward"
    )

def test_backfill_hook_updates_read_model(test_db, migration_context):
    hook = BackfillReadModelHook()
    result = hook.execute(test_db.connection, migration_context)

    assert result.phase == "AFTER_DDL"
    assert result.rows_affected > 0
    assert result.stats["model_backfilled"] is True

def test_hook_raises_on_validation_failure(test_db, migration_context):
    hook = ValidateDataIntegrity()
    migration_context.set_stat("initial_count", 1000)

    # Simulate data loss
    test_db.truncate_table("users")

    with pytest.raises(ValueError, match="Data loss detected"):
        hook.execute(test_db.connection, migration_context)
```

---

## Common Patterns

### Pattern 1: Statistics Capture → Validation

```python
# Hook 1: Capture (BEFORE_DDL)
context.set_stat("users_before", 1000)

# ... DDL executes ...

# Hook 2: Validate (AFTER_VALIDATION)
before = context.get_stat("users_before")
cursor.execute("SELECT COUNT(*) FROM users")
after = cursor.fetchone()[0]
assert after >= before
```

### Pattern 2: Temporary Tables

```python
# Hook 1: Create (BEFORE_DDL)
cursor.execute("CREATE TEMP TABLE staging AS SELECT ...")

# ... DDL executes ...

# Hook 2: Cleanup (CLEANUP)
cursor.execute("DROP TABLE IF EXISTS staging")
```

### Pattern 3: Cascading Operations

```python
# Hook 1: Backfill (AFTER_DDL)
cursor.execute("INSERT INTO read_model ...")

# Hook 2: Validate (AFTER_VALIDATION)
cursor.execute("SELECT COUNT(*) FROM read_model")
# ... verify counts match ...

# Hook 3: Alert (ON_ERROR)
# If any previous hook fails, send notification
```

---

## Troubleshooting

### Hook Not Executing

**Check**:
1. Hook phase is correct
2. Hook is added to migration class
3. Hook class inherits from `Hook`
4. `phase` attribute is set
5. `execute()` method is implemented

```python
# ✅ Correct
class MyHook(Hook):
    phase = HookPhase.AFTER_DDL

    def execute(self, conn, context):
        return HookResult(...)

# ❌ Wrong - missing phase
class MyHook(Hook):
    def execute(self, conn, context):
        return HookResult(...)

# ❌ Wrong - not added to migration
class MyMigration(Migration):
    # Missing: after_ddl_hooks = [MyHook()]
    def up(self):
        pass
```

### Hook Causes Migration to Fail

**Solutions**:
1. Wrap risky operations in try/except if not critical
2. Check data assumptions before operations
3. Add validation hooks to catch issues early
4. Test hooks against production-like data

```python
# ❌ Will fail if table doesn't exist
class BadHook(Hook):
    def execute(self, conn, context):
        cursor = conn.cursor()
        cursor.execute("INSERT INTO read_model ...")  # Might not exist yet

# ✅ Safe version
class SafeHook(Hook):
    def execute(self, conn, context):
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'read_model'
            )
        """)
        exists = cursor.fetchone()[0]

        if not exists:
            return HookResult(
                phase=self.phase.name,
                hook_name=self.__class__.__name__,
                stats={"skipped": "table_not_found"}
            )

        cursor.execute("INSERT INTO read_model ...")
```

---

## Best Practices

1. **Keep Hooks Focused**: One responsibility per hook
2. **Use Appropriate Phases**: Don't do AFTER_DDL work in BEFORE_DDL
3. **Handle Errors Gracefully**: Don't crash on unexpected data
4. **Log Important Operations**: Use logging for debugging
5. **Test Hooks**: Write unit tests for hook logic
6. **Document Assumptions**: Comment on data expectations
7. **Measure Performance**: Track hook execution times
8. **Validate Results**: Don't assume operations succeeded

---

## See Also

- [Migration Models](./guides/medium-2-incremental-migrations.md) - How migrations work
- [CQRS Patterns](./guides/) - Read/write model coordination
- [Examples](../examples/hooks/) - Real-world hook examples

