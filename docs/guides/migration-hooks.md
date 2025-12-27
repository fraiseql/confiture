# Migration Hooks

**Extend migration behavior with before/after hooks for validation, logging, and custom workflows**

---

## What are Migration Hooks?

Migration hooks allow you to execute custom code at specific points in the migration lifecycle. They're powerful for automating tasks like:

- **Validation** - Check preconditions before running migrations
- **Logging** - Track migration metadata and audit trails
- **Data verification** - Validate data integrity before/after
- **Custom workflows** - Trigger external systems (webhooks, notifications)
- **Rollback handlers** - Clean up side effects on rollback

### Key Concept

> **"Hooks are the bridge between your migrations and your application logic"**

Hooks run Python functions at predictable points, giving you full control over the migration process.

---

## When to Use Migration Hooks

### ✅ Perfect For

- **Validation checks** - Verify preconditions before applying migration
- **Audit logging** - Record who applied which migrations and when
- **Data integrity** - Run consistency checks after migrations
- **Notifications** - Alert teams via Slack/email of migration status
- **Side effects** - Update caches, rebuild indices, reset sequences
- **Rollback handling** - Clean up resources created by migrations
- **Integration testing** - Validate data after migrations in CI/CD

### ❌ Not For

- **Schema modifications** - Use `db/schema/` DDL files instead
- **Data transformations** - Use SQL migrations or Medium 3 (Sync)
- **Performance optimization** - Add indices in schema files, not hooks
- **Complex business logic** - Better as separate application code

---

## How Hooks Work

### The Hook Lifecycle

```
confiture migrate up
         │
         ├─→ [pre_validate] Hook
         │   └─ Check preconditions
         │
         ├─→ Load migrations
         │
         ├─→ [pre_execute] Hook (per migration)
         │   └─ Log migration start
         │
         ├─→ Execute SQL
         │
         └─→ [post_execute] Hook (per migration)
             └─ Verify data integrity
```

### Available Hooks

| Hook | Timing | Use Case |
|------|--------|----------|
| `pre_validate` | Before any migration | Check preconditions |
| `pre_execute` | Before each migration | Log start, notify team |
| `post_execute` | After each migration | Verify results, rebuild indices |
| `post_complete` | After all migrations | Notify completion, cleanup |
| `pre_rollback` | Before rollback | Save state for rollback |
| `post_rollback` | After rollback | Clean up side effects |

---

## Defining Hooks

### Hook Function Signature

All hooks follow this pattern:

```python
from confiture.hooks import HookContext, HookRegistry

def my_hook(context: HookContext) -> None:
    """Hook function must accept HookContext and return None."""
    migration_version = context.migration.version
    migration_name = context.migration.name
    # Your custom code here
```

### HookContext Object

The `HookContext` provides access to migration metadata:

```python
class HookContext:
    migration: Migration         # Current migration (or None for pre_validate)
    environment: str            # Environment name
    status: str                 # 'pending', 'applied', 'error'
    duration_ms: float          # Execution time in milliseconds
    error: Exception | None     # Error if migration failed
    metadata: dict              # Custom metadata
```

### Registering Hooks

#### Option 1: Using Decorator (Recommended)

```python
# confiture_hooks.py (in project root or db/)

from confiture.hooks import register_hook, HookContext

@register_hook('pre_execute')
def log_migration_start(context: HookContext) -> None:
    """Log when migration starts."""
    print(f"🚀 Starting: {context.migration.name}")

@register_hook('post_execute')
def verify_schema(context: HookContext) -> None:
    """Verify schema integrity after migration."""
    print(f"✅ Completed: {context.migration.name}")
```

#### Option 2: Configuration File

```yaml
# db/confiture.yaml

hooks:
  pre_execute:
    - module: "scripts.hooks"
      function: "log_migration"
  post_execute:
    - module: "scripts.hooks"
      function: "verify_schema"
```

#### Option 3: Programmatic Registration

```python
from confiture.hooks import HookRegistry

registry = HookRegistry()

def my_hook(context: HookContext) -> None:
    pass

registry.register('pre_execute', my_hook)
```

---

## Example: Validation Hook

**Situation**: Ensure database is accessible before running migrations.

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
import psycopg

@register_hook('pre_validate')
def check_database_accessible(context: HookContext) -> None:
    """Verify database connection before migration."""
    try:
        # Try to connect to database
        with psycopg.connect(
            f"postgresql://localhost/{context.environment}"
        ) as conn:
            conn.execute("SELECT 1")
        print("✅ Database is accessible")
    except Exception as e:
        raise RuntimeError(f"Cannot connect to database: {e}")
```

**Output**:
```
✅ Database is accessible
🚀 Applying migrations...
```

**Explanation**: This hook runs before any migrations execute, verifying the database is ready. If connection fails, the migration stops immediately.

---

## Example: Audit Logging Hook

**Situation**: Track all migrations in an audit table for compliance.

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
from datetime import datetime
import psycopg
import os

@register_hook('post_execute')
def audit_log_migration(context: HookContext) -> None:
    """Log migration to audit table."""

    # Skip if not in production
    if context.environment != "production":
        return

    # Connect to database
    with psycopg.connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_migrations
            (version, name, applied_at, duration_ms, applied_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                context.migration.version,
                context.migration.name,
                datetime.now(),
                context.duration_ms,
                os.getenv('USER', 'unknown')
            )
        )
        conn.commit()

    print(f"📝 Audit logged: {context.migration.name}")
```

**Prerequisites**:
```sql
-- db/schema/10_tables/audit.sql
CREATE TABLE IF NOT EXISTS audit_migrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    duration_ms FLOAT NOT NULL,
    applied_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Example: Data Integrity Check Hook

**Situation**: Verify data is valid after a complex migration.

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
import psycopg

@register_hook('post_execute')
def verify_data_integrity(context: HookContext) -> None:
    """Check data integrity after migration."""

    # Skip if not a users migration
    if 'users' not in context.migration.name:
        return

    with psycopg.connect() as conn:
        # Check for missing emails
        result = conn.execute(
            "SELECT COUNT(*) FROM users WHERE email IS NULL"
        )
        null_count = result.scalar()

        if null_count > 0:
            raise ValueError(f"Found {null_count} users with NULL emails")

        # Check for duplicate emails
        result = conn.execute(
            "SELECT COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1"
        )
        dup_count = len(result.fetchall())

        if dup_count > 0:
            raise ValueError(f"Found {dup_count} duplicate email addresses")

    print("✅ Data integrity verified")
```

---

## Example: Slack Notification Hook

**Situation**: Notify team on migration completion.

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
import os
import requests
from datetime import datetime

@register_hook('post_complete')
def notify_slack(context: HookContext) -> None:
    """Send Slack notification on migration completion."""

    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return

    message = {
        "text": f"✅ {context.environment.upper()} migrations completed",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Migration Complete*\n"
                        f"Environment: `{context.environment}`\n"
                        f"Time: {datetime.now().isoformat()}"
                    )
                }
            }
        ]
    }

    response = requests.post(webhook_url, json=message)
    response.raise_for_status()
    print("📢 Slack notification sent")
```

---

## Example: Rollback Cleanup Hook

**Situation**: Clean up temporary tables created by migration on rollback.

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
import psycopg

@register_hook('post_rollback')
def cleanup_temporary_resources(context: HookContext) -> None:
    """Remove temporary tables created by migration."""

    temp_table_name = f"temp_{context.migration.version}"

    with psycopg.connect() as conn:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
            conn.commit()
            print(f"🧹 Cleaned up temporary table: {temp_table_name}")
        except Exception as e:
            print(f"⚠️  Could not cleanup {temp_table_name}: {e}")
```

---

## Best Practices

### 1. Keep Hooks Fast

**Good**:
```python
@register_hook('post_execute')
def quick_check(context: HookContext) -> None:
    """Fast hook that completes in <100ms."""
    # Just check a few rows
    pass
```

**Bad**:
```python
@register_hook('post_execute')
def slow_scan(context: HookContext) -> None:
    """Slow hook that scans millions of rows."""
    # Scans entire database
    pass
```

### 2. Handle Errors Gracefully

**Good**:
```python
@register_hook('post_execute')
def safe_hook(context: HookContext) -> None:
    """Handles errors without crashing migration."""
    try:
        # Try to do something
        risky_operation()
    except Exception as e:
        print(f"⚠️  Hook failed (non-critical): {e}")
        # Continue - don't raise
```

**Bad**:
```python
@register_hook('post_execute')
def unsafe_hook(context: HookContext) -> None:
    """Crashes entire migration on any error."""
    risky_operation()  # If fails, migration fails
```

### 3. Log Meaningfully

**Good**:
```python
@register_hook('pre_execute')
def meaningful_log(context: HookContext) -> None:
    """Provides useful information."""
    print(f"Applying migration {context.migration.version}: {context.migration.name}")
```

**Bad**:
```python
@register_hook('pre_execute')
def meaningless_log(context: HookContext) -> None:
    """Not helpful."""
    print("Hook running...")
```

### 4. Check Environment Conditionally

**Good**:
```python
@register_hook('post_execute')
def prod_only_check(context: HookContext) -> None:
    """Only runs in production."""
    if context.environment != 'production':
        return
    # Production-specific logic
```

**Bad**:
```python
@register_hook('post_execute')
def runs_everywhere(context: HookContext) -> None:
    """Runs in all environments."""
    # Does expensive prod checks even in dev
```

---

## Troubleshooting

### ❌ Error: Hook not called

**Cause**: Hook not registered or wrong trigger name.

**Solution**: Verify hook is registered and trigger name is correct:

```python
# Check registered hooks
from confiture.hooks import get_registered_hooks
print(get_registered_hooks())  # See all hooks
```

**Explanation**: Hook names are case-sensitive and must match exactly.

---

### ❌ Error: Hook crashes migration

**Cause**: Unhandled exception in hook.

**Solution**: Wrap in try-except:

```python
@register_hook('post_execute')
def safe_hook(context: HookContext) -> None:
    """Won't crash migration if it fails."""
    try:
        risky_code()
    except Exception as e:
        print(f"⚠️  Hook error (non-critical): {e}")
        # Don't raise - migration continues
```

**Explanation**: By default, hook errors stop migrations. Use try-except for optional checks.

---

## See Also

- [Advanced Patterns](./advanced-patterns.md) - Custom workflows and integrations
- [Migration Hooks API](../api/hooks.md) - Complete API reference
- [Troubleshooting](./troubleshooting.md) - Common issues
- [Comparison: Hooks vs Pre-commit](./hooks-vs-pre-commit.md) - When to use each

---

## 🎯 Next Steps

**Ready to extend your migrations?**
- ✅ You now understand: Hook lifecycle, common patterns, best practices

**What to do next:**

1. **[Advanced Patterns](./advanced-patterns.md)** - Custom validation and workflows
2. **[API Reference](../api/hooks.md)** - Detailed hook API documentation
3. **[Examples](../../examples/)** - Production-ready hook examples

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](./troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
