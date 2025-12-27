# Advanced Patterns Guide

**For experienced Confiture users who want to master advanced techniques.**

---

## 📋 Overview

This guide covers advanced patterns for:
1. **Custom anonymization strategies** - Beyond built-in strategies
2. **Hook orchestration** - Coordinating multi-phase migrations
3. **Performance optimization** - Scaling to large datasets
4. **Complex migration scenarios** - Real-world edge cases
5. **CQRS backfilling** - Syncing read models after schema changes

---

## 1️⃣ Custom Anonymization Strategies

### When to Use Custom Strategies

Built-in strategies (hash, redact, email, name, phone) cover 90% of cases. Create custom strategies when you need:
- **Domain-specific anonymization** (credit cards, SSNs, medical records)
- **Deterministic transformations** (consistent fake data per ID)
- **Contextual anonymization** (different rules for different users)
- **Legacy system compatibility** (match existing anonymization)

### Creating a Custom Strategy

```python
from confiture.core.anonymization.strategy import AnonymizationStrategy
from dataclasses import dataclass
from typing import Any
import hashlib

@dataclass
class CreditCardConfig:
    seed: str = "confiture"

class CreditCardAnonymizer(AnonymizationStrategy):
    """Anonymize credit card numbers while preserving last 4 digits."""

    config_type = CreditCardConfig
    strategy_name = "credit_card"

    def __init__(self, config: CreditCardConfig):
        self.config = config

    def anonymize(self, value: Any) -> str:
        """Keep last 4 digits, hash the rest."""
        if not isinstance(value, str):
            return "INVALID"

        # Validate CC number
        if not self.validate(value):
            return "INVALID"

        # Keep last 4, hash the rest
        last_four = value[-4:]
        to_hash = value[:-4]

        # Deterministic hash (same CC always produces same output)
        hasher = hashlib.sha256(f"{to_hash}{self.config.seed}".encode())
        hashed = hasher.hexdigest()[:12]

        return f"xxxx-xxxx-xxxx-{last_four}"

    def validate(self, value: Any) -> bool:
        """Check if value is valid credit card."""
        if not isinstance(value, str):
            return False

        # Remove spaces/dashes
        digits = value.replace(" ", "").replace("-", "")

        # Must be 13-19 digits
        if not digits.isdigit() or len(digits) < 13 or len(digits) > 19:
            return False

        # Luhn check (basic validation)
        return self._luhn_check(digits)

    def _luhn_check(self, card_number: str) -> bool:
        """Luhn algorithm for credit card validation."""
        digits = [int(d) for d in card_number]
        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:  # Every second digit
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0
```

### Using Your Custom Strategy

```python
from confiture.core.syncer import Syncer, SyncConfig, TableSelection
from confiture.core.anonymization.rules import AnonymizationRule

# Register custom strategy
custom_strategy = CreditCardAnonymizer(CreditCardConfig(seed="your-seed"))

# Use in sync config
config = SyncConfig(
    source_url="postgresql://prod:5432/production",
    target_url="postgresql://localhost/development",
    tables=TableSelection(include=["users", "payments"]),
    anonymization={
        "payments": [
            AnonymizationRule(
                column="card_number",
                strategy=custom_strategy  # Use custom anonymizer
            )
        ]
    }
)

syncer = Syncer(config)
result = await syncer.sync()
```

### Advanced: Context-Aware Anonymization

```python
from typing import Dict, Any

class ContextAwareAnonymizer(AnonymizationStrategy):
    """Apply different anonymization based on user role."""

    config_type = ContextAwareConfig
    strategy_name = "context_aware"

    def anonymize(self, value: Any, context: Dict[str, Any] | None = None) -> str:
        """Anonymize differently based on context."""
        if context is None:
            context = {}

        user_role = context.get("user_role", "user")

        # Admins see real data, regular users see anonymized
        if user_role == "admin":
            return str(value)  # No anonymization

        # Regular users get hashed version
        return self._hash_value(value)

    def _hash_value(self, value: Any) -> str:
        hasher = hashlib.sha256(str(value).encode())
        return f"hash_{hasher.hexdigest()[:8]}"
```

---

## 2️⃣ Hook Orchestration

### Understanding Hook Phases

Confiture provides 6 hook phases for complete control over migrations:

```
1. BEFORE_VALIDATION  →  Pre-flight checks
                         ↓
2. BEFORE_DDL        →  Prepare for schema changes
                         ↓
3. (Execute DDL)     →  Schema changes happen
                         ↓
4. AFTER_DDL         →  Post-schema changes (data migration, CQRS)
                         ↓
5. AFTER_VALIDATION  →  Verify everything worked
                         ↓
6. CLEANUP           →  Clean up temporary state
                         ↓
   ON_ERROR          →  Handle failures (can run at any point)
```

### Example: Complex Migration with All Hooks

```python
from confiture.core.hooks import MigrationHook, HookPhase, HookContext

class ComplexMigrationHook(MigrationHook):
    """Orchestrate complex migration with multiple steps."""

    async def execute(self, context: HookContext) -> None:
        phase = context.phase

        # Phase 1: Pre-flight checks
        if phase == HookPhase.BEFORE_VALIDATION:
            await self._check_prerequisites(context)

        # Phase 2: Prepare
        elif phase == HookPhase.BEFORE_DDL:
            await self._backup_critical_data(context)
            await self._notify_users(context, "maintenance starting")

        # Phase 3: Post-DDL data operations
        elif phase == HookPhase.AFTER_DDL:
            await self._backfill_new_column(context)
            await self._rebuild_indexes(context)
            await self._sync_read_models(context)

        # Phase 4: Validation
        elif phase == HookPhase.AFTER_VALIDATION:
            await self._verify_data_integrity(context)
            await self._check_performance_metrics(context)

        # Phase 5: Cleanup
        elif phase == HookPhase.CLEANUP:
            await self._remove_temporary_tables(context)
            await self._notify_users(context, "maintenance complete")

        # Phase 6: Error handling
        elif phase == HookPhase.ON_ERROR:
            await self._handle_failure(context)

    async def _check_prerequisites(self, context: HookContext) -> None:
        """BEFORE_VALIDATION: Check if migration can proceed."""
        conn = context.connection

        # Check for long-running queries
        result = await conn.execute("""
            SELECT count(*) FROM pg_stat_activity
            WHERE query_start < now() - interval '5 minutes'
        """)
        long_running = result.scalar()

        if long_running > 0:
            raise RuntimeError(
                f"{long_running} long-running queries detected. "
                "Cancel them before proceeding."
            )

    async def _backup_critical_data(self, context: HookContext) -> None:
        """BEFORE_DDL: Backup critical tables."""
        conn = context.connection

        # Create backup of users table
        await conn.execute("""
            CREATE TABLE users_backup_20250101 AS
            SELECT * FROM users
        """)

        print("✅ Created users_backup_20250101")

    async def _backfill_new_column(self, context: HookContext) -> None:
        """AFTER_DDL: Backfill data into new column."""
        conn = context.connection

        # New column 'account_status' was added, backfill based on created_at
        await conn.execute("""
            UPDATE users
            SET account_status = 'active'
            WHERE created_at > now() - interval '30 days'
        """)

        print("✅ Backfilled account_status column")

    async def _sync_read_models(self, context: HookContext) -> None:
        """AFTER_DDL: Rebuild read models (CQRS pattern)."""
        conn = context.connection

        # Refresh materialized view for reporting
        await conn.execute("REFRESH MATERIALIZED VIEW user_stats")

        # Update read model in external system
        # (could be Redis, Elasticsearch, etc.)
        await self._update_elasticsearch()

        print("✅ Synced read models")

    async def _verify_data_integrity(self, context: HookContext) -> None:
        """AFTER_VALIDATION: Check data quality."""
        conn = context.connection

        # Verify all users have valid email
        result = await conn.execute("""
            SELECT count(*) FROM users
            WHERE email IS NULL OR email = ''
        """)
        invalid_count = result.scalar()

        if invalid_count > 0:
            raise RuntimeError(
                f"{invalid_count} users have invalid email. "
                "Data integrity check failed."
            )

    async def _update_elasticsearch(self) -> None:
        """Update external read models."""
        # Example: Update Elasticsearch index
        import httpx

        async with httpx.AsyncClient() as client:
            await client.post(
                "http://elasticsearch:9200/_reindex",
                json={"source": {"index": "users"}, "dest": {"index": "users_v2"}}
            )

    async def _remove_temporary_tables(self, context: HookContext) -> None:
        """CLEANUP: Remove temporary artifacts."""
        conn = context.connection

        # Drop backup (migration succeeded, no need)
        await conn.execute("DROP TABLE IF EXISTS users_backup_20250101")

    async def _handle_failure(self, context: HookContext) -> None:
        """ON_ERROR: Handle migration failure."""
        error = context.error

        # Log error
        print(f"❌ Migration failed: {error}")

        # Restore from backup if it exists
        try:
            conn = context.connection
            await conn.execute("""
                DROP TABLE users;
                ALTER TABLE users_backup_20250101 RENAME TO users;
            """)
            print("✅ Restored from backup")
        except Exception as restore_error:
            print(f"❌ Restore also failed: {restore_error}")
```

### Using the Hook

```python
from confiture.core.migrator import Migrator, MigrationConfig

config = MigrationConfig(
    environment="production",
    hooks=[ComplexMigrationHook()],
    dry_run=False,
    dry_run_execute=False
)

migrator = Migrator(config)
result = await migrator.migrate_up()
```

---

## 3️⃣ Performance Optimization

### Batch Size Tuning

```python
from confiture.core.syncer import Syncer, SyncConfig

# For tables with many columns (wide tables)
config_wide = SyncConfig(
    source_url="postgresql://prod:5432/production",
    target_url="postgresql://localhost/development",
    tables=TableSelection(include=["wide_table"]),
    batch_size=2000  # Reduce for wide tables
)

# For simple tables (narrow tables)
config_narrow = SyncConfig(
    source_url="postgresql://prod:5432/production",
    target_url="postgresql://localhost/development",
    tables=TableSelection(include=["narrow_table"]),
    batch_size=10000  # Increase for narrow tables
)
```

### Parallel Table Sync

```python
# Sync multiple tables in parallel
config = SyncConfig(
    source_url="postgresql://prod:5432/production",
    target_url="postgresql://localhost/development",
    tables=TableSelection(
        include=["users", "orders", "products", "payments"]
    ),
    parallelism=4  # Sync 4 tables at once
)

syncer = Syncer(config)
result = await syncer.sync()
```

### Progress Monitoring

```python
from confiture.core.syncer import Syncer, SyncConfig

config = SyncConfig(
    source_url="postgresql://prod:5432/production",
    target_url="postgresql://localhost/development",
    tables=TableSelection(include=["huge_table"]),
    show_progress=True,  # Show progress bar
    checkpoint_file=Path("/tmp/sync_checkpoint.json"),  # Enable resume
    verbose=True  # Show detailed logging
)

syncer = Syncer(config)
try:
    result = await syncer.sync()
except KeyboardInterrupt:
    print("Sync interrupted. Resume with:")
    print(f"  confiture sync --checkpoint /tmp/sync_checkpoint.json")
```

---

## 4️⃣ Complex Migration Scenarios

### Scenario: Rename Column with Backfill

```python
from confiture.core.hooks import MigrationHook, HookPhase, HookContext

class RenameColumnHook(MigrationHook):
    """Rename column with gradual backfill."""

    async def execute(self, context: HookContext) -> None:
        if context.phase == HookPhase.AFTER_DDL:
            conn = context.connection

            # Step 1: Add new column with default
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN user_status VARCHAR DEFAULT 'active'
            """)

            # Step 2: Backfill from old column
            await conn.execute("""
                UPDATE users
                SET user_status = status
                WHERE user_status = 'active'
            """)

            # Step 3: Add constraint
            await conn.execute("""
                ALTER TABLE users
                ALTER COLUMN user_status SET NOT NULL
            """)

            print("✅ Column renamed and backfilled")
```

### Scenario: Add Column to Large Table

```python
class AddColumnToLargeTableHook(MigrationHook):
    """Add column to table with 100M+ rows without locking."""

    async def execute(self, context: HookContext) -> None:
        if context.phase == HookPhase.AFTER_DDL:
            conn = context.connection

            # PostgreSQL 11+: Column can be added with default without table rebuild
            # Add column without locking table
            await conn.execute("""
                ALTER TABLE orders
                ADD COLUMN shipping_status VARCHAR DEFAULT 'pending'
            """)

            # Backfill in batches to avoid locking
            batch_size = 100000
            offset = 0

            while True:
                result = await conn.execute(f"""
                    UPDATE orders
                    SET shipping_status = 'shipped'
                    WHERE id IN (
                        SELECT id FROM orders
                        WHERE shipping_status = 'pending'
                        LIMIT {batch_size}
                    )
                """)

                if result.rowcount == 0:
                    break

                offset += batch_size
                print(f"✅ Backfilled {offset} rows")
```

---

## 5️⃣ CQRS Backfilling

### Syncing Read Models After Schema Changes

```python
class CQRSBackfillHook(MigrationHook):
    """Backfill CQRS read models after schema change."""

    async def execute(self, context: HookContext) -> None:
        if context.phase == HookPhase.AFTER_DDL:
            await self._rebuild_user_read_model(context)
            await self._sync_elasticsearch(context)
            await self._refresh_materialized_views(context)

    async def _rebuild_user_read_model(self, context: HookContext) -> None:
        """Rebuild read model in database."""
        conn = context.connection

        # Drop and recreate read model
        await conn.execute("DROP MATERIALIZED VIEW IF EXISTS user_stats")
        await conn.execute("""
            CREATE MATERIALIZED VIEW user_stats AS
            SELECT
                user_id,
                count(*) as total_orders,
                sum(amount) as total_spent,
                max(created_at) as last_order
            FROM orders
            GROUP BY user_id
        """)

    async def _sync_elasticsearch(self, context: HookContext) -> None:
        """Sync to Elasticsearch for search."""
        conn = context.connection

        # Fetch updated users
        result = await conn.fetch("SELECT * FROM users WHERE updated_at > now() - interval '1 hour'")

        # Update Elasticsearch
        import httpx
        async with httpx.AsyncClient() as client:
            for row in result:
                await client.put(
                    f"http://elasticsearch:9200/users/_doc/{row['id']}",
                    json=dict(row)
                )

    async def _refresh_materialized_views(self, context: HookContext) -> None:
        """Refresh all materialized views."""
        conn = context.connection

        views = await conn.fetch("""
            SELECT matviewname FROM pg_matviews
        """)

        for view in views:
            await conn.execute(f"REFRESH MATERIALIZED VIEW {view['matviewname']}")
```

---

## 📚 Best Practices

### 1. Always Test Complex Hooks

```bash
# Test hook with dry-run-execute (transactions rollback)
confiture migrate up --dry-run-execute

# Verify the transaction rolled back
confiture migrate status  # Should show same state
```

### 2. Use Idempotent Hooks

```python
# ✅ Good: Idempotent (can run multiple times safely)
async def idempotent_hook(context):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS temp_data (id INT)
    """)

# ❌ Bad: Not idempotent (fails on retry)
async def non_idempotent_hook(context):
    await conn.execute("""
        CREATE TABLE temp_data (id INT)  -- Fails if run twice
    """)
```

### 3. Log Extensively

```python
import logging

logger = logging.getLogger(__name__)

async def logged_hook(context):
    logger.info("🚀 Starting complex operation")

    try:
        result = await complex_operation(context)
        logger.info(f"✅ Operation succeeded: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Operation failed: {e}", exc_info=True)
        raise
```

### 4. Use Checkpoints for Long Operations

```python
# Save progress to resume if interrupted
checkpoint_file = Path("/tmp/migration_checkpoint.json")

async def checkpointed_hook(context):
    # Load checkpoint
    if checkpoint_file.exists():
        checkpoint = json.loads(checkpoint_file.read_text())
        last_id = checkpoint.get("last_processed_id", 0)
    else:
        last_id = 0

    # Process in batches
    batch_size = 10000
    while True:
        result = await conn.execute(f"""
            SELECT id FROM large_table
            WHERE id > {last_id}
            LIMIT {batch_size}
        """)

        if not result:
            break

        # Process batch
        for row in result:
            await process_row(row)
            last_id = row['id']

        # Save checkpoint
        checkpoint_file.write_text(json.dumps({"last_processed_id": last_id}))
        print(f"✅ Processed {last_id} rows, checkpoint saved")
```

---

## 🔗 Related Guides

- **[Migration Hooks](../hooks.md)** - Full hook API reference
- **[Production Data Sync](./medium-3-production-sync.md)** - Sync strategies
- **[Anonymization Strategy Framework](./anonymization-strategy-framework.md)** - Built-in strategies
- **[Zero-Downtime Migrations](./medium-4-schema-to-schema.md)** - FDW strategy

---

## 💡 Next Steps

1. **Try custom anonymization** - Create a strategy for your domain
2. **Implement hooks** - Automate complex migrations
3. **Optimize performance** - Tune batch sizes for your tables
4. **Monitor production** - Use checkpoints and logging

---

*Last updated: December 27, 2025*
*Questions? See [Troubleshooting](troubleshooting.md) or [Getting Started](../getting-started.md)*
