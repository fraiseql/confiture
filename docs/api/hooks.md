# Hook API Reference

[← Back to API Reference](index.md)

**Stability**: Stable ✅

---

## Overview

The Hook API enables you to extend Confiture migrations with custom logic at key lifecycle points. Hooks allow you to validate data, log events, integrate with external systems, or implement custom business logic before and after migrations.

**Tagline**: *Extend migrations with custom logic at critical points*

---

## What is a Hook?

A Hook is a Python function registered to execute at a specific point in the migration lifecycle. Hooks have access to the migration context (tables, columns, status) and can:
- Validate data before or after migrations
- Log events to external systems
- Trigger notifications (Slack, email, webhooks)
- Implement custom compliance checks
- Coordinate with external systems

**Key Concept**: Hooks are synchronous, blocking operations. Keep them fast (<1 second) for best performance.

---

## Why Use Hooks?

### Common Use Cases

1. **Data Validation**
   - Check data integrity before/after migrations
   - Validate business rules are enforced
   - Detect anomalies early

2. **Monitoring & Logging**
   - Log migration events to central system
   - Track performance metrics
   - Send alerts on failures

3. **Notifications**
   - Notify teams via Slack
   - Send emails to stakeholders
   - Update status dashboards

4. **Compliance & Auditing**
   - Record all migrations for audit trails
   - Verify compliance requirements
   - Track who changed what

5. **Integration**
   - Coordinate with CI/CD pipelines
   - Trigger related processes
   - Sync with external databases

---

## When to Use Hooks

**✅ Good Use Cases**:
- Notifications (send messages when migrations complete)
- Quick validations (check row counts match)
- Logging (record events for audit)
- External integrations (webhook calls)
- Compliance checks (HIPAA audit logs)

**❌ Don't Use Hooks For**:
- Complex data transformations (use migrations instead)
- Long-running operations (> 5 seconds)
- Parallel processing (hooks are synchronous)
- Resource-intensive operations (use separate jobs)

**Pro Tip**: For complex logic, call external services from hooks rather than doing heavy computation in the hook itself.

---

## Hook Lifecycle & Trigger Points

### Available Hook Points

```
Migration Execution Timeline:
│
├─ pre_validate ──────────► Runs before schema validation
├─ post_validate ─────────► Runs after schema validation
├─ pre_execute ──────────► Runs before migration execution
├─ post_execute ─────────► Runs after migration execution
└─ on_error ─────────────► Runs if migration fails
```

### Hook Trigger Reference

| Hook Point | When Triggered | Use Case |
|-----------|----------------|----------|
| `pre_validate` | Before schema validation | Pre-flight checks |
| `post_validate` | After validation passes | Log validation success |
| `pre_execute` | Before migration starts | Notify teams starting |
| `post_execute` | After migration succeeds | Send completion alert |
| `on_error` | When migration fails | Error notification |

---

## Function Signature

### Basic Hook Definition

```python
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def my_migration_hook(context: HookContext) -> None:
    """
    Custom hook executed after migration completes.

    Args:
        context: HookContext with migration information

    Returns:
        None (blocking call)

    Raises:
        HookError: If hook execution fails (stops migration)
    """
    pass
```

### Parameters

**hook_point** (str): One of:
- `'pre_validate'` - Before schema validation
- `'post_validate'` - After successful validation
- `'pre_execute'` - Before migration execution
- `'post_execute'` - After successful migration
- `'on_error'` - On migration failure

---

## HookContext Object

The `HookContext` object provides information about the migration.

### Context Attributes

```python
@dataclass
class HookContext:
    # Migration Information
    migration_name: str          # e.g., "001_create_users_table"
    migration_version: str       # e.g., "001"
    environment: str             # e.g., "production"

    # Database Information
    database_url: str            # PostgreSQL connection string
    schema_name: str             # Target schema (default "public")
    tables: list[TableInfo]      # Tables involved in migration

    # Execution Details
    start_time: datetime          # When migration started
    end_time: datetime | None     # When it ended (None if running)
    duration: timedelta | None    # Total duration
    status: str                   # 'running', 'success', 'error'

    # Results
    rows_affected: int | None     # Rows changed (if applicable)
    error: Exception | None       # Exception if failed (on_error only)

    # Custom Data
    metadata: dict[str, Any]      # Custom metadata from migration
```

### TableInfo Details

```python
@dataclass
class TableInfo:
    name: str                     # Table name
    action: str                   # 'create', 'alter', 'drop'
    columns: list[ColumnInfo]     # Column details
    rows_before: int | None       # Row count before
    rows_after: int | None        # Row count after
```

### ColumnInfo Details

```python
@dataclass
class ColumnInfo:
    name: str                     # Column name
    data_type: str               # PostgreSQL type
    nullable: bool               # NOT NULL constraint
    default: str | None          # Default value
```

---

## Registering Hooks

### Simple Registration

```python
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def log_migration_success(context: HookContext) -> None:
    """Log successful migration to monitoring system."""
    print(f"Migration {context.migration_name} completed successfully!")
    print(f"Duration: {context.duration}")
    print(f"Rows affected: {context.rows_affected}")
```

### Multiple Hooks for Same Point

You can register multiple hooks for the same trigger point:

```python
@register_hook('post_execute')
def notify_slack(context: HookContext) -> None:
    """Send Slack notification."""
    # Implementation
    pass

@register_hook('post_execute')
def log_metrics(context: HookContext) -> None:
    """Log metrics to monitoring system."""
    # Implementation
    pass

# Both hooks will execute in registration order
```

### Conditional Hook Execution

```python
@register_hook('post_execute')
def notify_on_production(context: HookContext) -> None:
    """Only notify for production migrations."""
    if context.environment == 'production':
        # Send notification
        pass
```

---

## Hook Examples

### Example 1: Log to File

```python
import logging
from confiture.hooks import register_hook, HookContext

logger = logging.getLogger('confiture.migrations')

@register_hook('post_execute')
def log_migration(context: HookContext) -> None:
    """Log migration completion."""
    logger.info(
        f"Migration {context.migration_name} completed",
        extra={
            'environment': context.environment,
            'duration': context.duration.total_seconds(),
            'rows_affected': context.rows_affected,
        }
    )
```

**Output**:
```
2026-01-15 14:23:45 INFO: Migration 001_create_users_table completed
  environment=production
  duration=2.34
  rows_affected=1000
```

---

### Example 2: Slack Notification

```python
import requests
from confiture.hooks import register_hook, HookContext

SLACK_WEBHOOK = "https://hooks.slack.com/services/YOUR/WEBHOOK"

@register_hook('post_execute')
def notify_slack(context: HookContext) -> None:
    """Send Slack notification after migration."""
    message = {
        "text": f"✅ Migration {context.migration_name} completed",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Migration Completed*\n"
                            f"*Name*: {context.migration_name}\n"
                            f"*Environment*: {context.environment}\n"
                            f"*Duration*: {context.duration}\n"
                            f"*Rows*: {context.rows_affected}"
                }
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK, json=message)
    response.raise_for_status()
```

**Slack Output**:
```
✅ Migration Completed
Name: 001_create_users_table
Environment: production
Duration: 0:00:02.34
Rows: 1000
```

---

### Example 3: Data Validation

```python
import psycopg
from confiture.hooks import register_hook, HookContext, HookError

@register_hook('post_execute')
def validate_data(context: HookContext) -> None:
    """Validate data integrity after migration."""
    try:
        with psycopg.connect(context.database_url) as conn:
            for table_info in context.tables:
                # Check for NULL values in NOT NULL columns
                for col in table_info.columns:
                    if not col.nullable:
                        cursor = conn.execute(
                            f"SELECT COUNT(*) FROM {table_info.name} "
                            f"WHERE {col.name} IS NULL"
                        )
                        null_count = cursor.scalar()

                        if null_count > 0:
                            raise HookError(
                                f"Found {null_count} NULL values in "
                                f"{table_info.name}.{col.name}"
                            )

    except Exception as e:
        raise HookError(f"Validation failed: {str(e)}") from e
```

---

### Example 4: Conditional Error Notification

```python
import requests
from confiture.hooks import register_hook, HookContext

@register_hook('on_error')
def notify_error(context: HookContext) -> None:
    """Send error notification for production failures."""
    if context.environment == 'production':
        # Send alert to on-call engineer
        message = {
            "text": f"🚨 Migration Failed: {context.migration_name}",
            "error": str(context.error),
            "environment": context.environment,
        }

        requests.post(
            "https://alerts.example.com/incident",
            json=message
        )
```

---

### Example 5: Metric Collection

```python
from confiture.hooks import register_hook, HookContext

# Mock metrics collector (would be Prometheus, Datadog, etc.)
class MetricsCollector:
    @staticmethod
    def record(metric_name: str, value: float, tags: dict) -> None:
        print(f"{metric_name}={value} {tags}")

@register_hook('post_execute')
def collect_metrics(context: HookContext) -> None:
    """Collect migration performance metrics."""
    collector = MetricsCollector()

    # Record duration
    duration_seconds = context.duration.total_seconds()
    collector.record(
        'migration.duration_seconds',
        duration_seconds,
        {'migration': context.migration_name, 'env': context.environment}
    )

    # Record rows affected
    if context.rows_affected:
        collector.record(
            'migration.rows_affected',
            context.rows_affected,
            {'migration': context.migration_name}
        )

    # Record success
    collector.record(
        'migration.success',
        1.0,
        {'migration': context.migration_name}
    )
```

---

## Exception Handling

### HookError

If your hook raises a `HookError`, it stops the migration:

```python
from confiture.hooks import register_hook, HookContext, HookError

@register_hook('post_execute')
def strict_validation(context: HookContext) -> None:
    """Fail migration if validation fails."""
    if context.rows_affected is None:
        raise HookError("Rows affected could not be determined")
```

**Result**: Migration marked as failed, error reported to user

### Non-blocking Errors

To handle errors without stopping migration:

```python
@register_hook('post_execute')
def resilient_notification(context: HookContext) -> None:
    """Fail gracefully if notification fails."""
    try:
        send_slack_notification(context)
    except Exception as e:
        print(f"Warning: Notification failed: {e}")
        # Migration continues despite error
```

---

## Best Practices

### ✅ Do's

1. **Keep hooks fast**
   ```python
   # Good: Direct operation
   @register_hook('post_execute')
   def quick_notification(context: HookContext) -> None:
       send_webhook(context.migration_name)  # < 1 second
   ```

2. **Use context information**
   ```python
   # Good: Use provided context
   if context.environment == 'production':
       send_important_notification(context)
   ```

3. **Handle errors gracefully**
   ```python
   # Good: Log and continue
   try:
       send_notification(context)
   except Exception as e:
       logger.error(f"Notification failed: {e}")
   ```

4. **Document your hooks**
   ```python
   @register_hook('post_execute')
   def my_hook(context: HookContext) -> None:
       """
       Sends Slack notification after successful migration.

       Expects SLACK_WEBHOOK environment variable.
       """
       pass
   ```

### ❌ Don'ts

1. **Don't do heavy processing**
   ```python
   # Bad: Slow operation blocks migration
   @register_hook('post_execute')
   def slow_operation(context: HookContext) -> None:
       result = expensive_computation()  # Minutes to complete
   ```

2. **Don't modify database directly**
   ```python
   # Bad: Hook modifies data
   @register_hook('post_execute')
   def bad_modification(context: HookContext) -> None:
       conn = psycopg.connect(context.database_url)
       conn.execute("UPDATE users SET status = 'migrated'")  # Don't do this!
   ```

3. **Don't ignore errors silently**
   ```python
   # Bad: Error disappears
   try:
       send_notification(context)
   except:
       pass  # Problem now hidden
   ```

---

## Testing Hooks

### Unit Test Example

```python
import pytest
from confiture.hooks import HookContext
from my_hooks import validate_data, HookError

def test_validation_passes_with_valid_data():
    """Test validation hook with valid data."""
    context = HookContext(
        migration_name='001_create_users',
        environment='test',
        database_url='postgresql://localhost/test_db',
        status='success',
        rows_affected=100,
        duration=timedelta(seconds=2),
        start_time=datetime.now(),
        end_time=datetime.now(),
    )

    # Should not raise
    validate_data(context)

def test_validation_fails_with_null_values():
    """Test validation hook detects NULL values."""
    context = HookContext(...)  # Setup context

    with pytest.raises(HookError):
        validate_data(context)
```

---

## Hook Performance

### Performance Characteristics

| Operation | Typical Time | Max Recommended |
|-----------|-------------|-----------------|
| Simple notification | 10-50ms | 100ms |
| Database query | 50-200ms | 500ms |
| API call | 100-500ms | 1000ms |
| Complex validation | 500-2000ms | 5000ms |

**Recommendation**: Keep total hook time < 1 second for responsive migrations

---

## Troubleshooting

### Problem: Hook Not Called

**Cause**: Hook not registered or wrong trigger point

**Solution**:
```python
# Check hook is registered
from confiture.hooks import list_hooks
print(list_hooks('post_execute'))  # Should include your hook

# Verify trigger point name
@register_hook('post_execute')  # Not 'postExecute' or 'post-execute'
def my_hook(context: HookContext) -> None:
    pass
```

### Problem: Hook Modifies Migration

**Cause**: Returning value from hook (shouldn't happen)

**Solution**: Hooks always return `None`
```python
@register_hook('post_execute')
def my_hook(context: HookContext) -> None:  # Type hint enforces None return
    # No return statement needed
    pass
```

### Problem: Hook Slows Down Migrations

**Cause**: Hook does heavy processing

**Solution**: Move heavy work outside hook
```python
# Bad
@register_hook('post_execute')
def slow_hook(context: HookContext) -> None:
    for i in range(1000000):
        expensive_operation()

# Good: Trigger background job
@register_hook('post_execute')
def trigger_job(context: HookContext) -> None:
    queue_job('heavy_processing', context.migration_name)
```

---

## API Stability

**Status**: ✅ **Stable**

The Hook API is stable and won't change in breaking ways:
- ✅ New trigger points may be added
- ✅ HookContext may gain new optional fields
- ✅ HookError remains the exception mechanism
- ⚠️ No promises about hook execution order across files

---

## See Also

- [Migration Hooks Guide](../guides/hooks.md) - User guide with patterns
- [Integrations Guide](../guides/integrations.md) - CI/CD, Slack, monitoring
- [Troubleshooting](../troubleshooting.md) - Common issues

---

**Last Updated**: January 17, 2026

