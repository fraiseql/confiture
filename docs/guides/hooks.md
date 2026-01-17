# Migration Hooks

[← Back to Guides](../index.md) · [Schema-to-Schema](04-schema-to-schema.md) · [Anonymization →](anonymization.md)

Execute custom code before and after migrations for validation, logging, and workflows.

---

## Quick Start

```python
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def verify_schema(context: HookContext) -> None:
    print(f"Completed: {context.migration.name}")
```

---

## Hook Lifecycle

```
confiture migrate up
    │
    ├─→ [pre_validate]     Check preconditions
    ├─→ Load migrations
    ├─→ [pre_execute]      Before each migration
    ├─→ Execute SQL
    ├─→ [post_execute]     After each migration
    └─→ [post_complete]    After all migrations
```

---

## Available Hooks

| Hook | Timing | Use Case |
|------|--------|----------|
| `pre_validate` | Before any migration | Check preconditions |
| `pre_execute` | Before each migration | Log start, notify team |
| `post_execute` | After each migration | Verify results, backfill |
| `post_complete` | After all migrations | Notify completion |
| `pre_rollback` | Before rollback | Save state |
| `post_rollback` | After rollback | Clean up |

---

## Hook Phases (Advanced)

For fine-grained control, use phase-based hooks:

| Phase | When | Use Case |
|-------|------|----------|
| `BEFORE_VALIDATION` | Before any work | Health checks, locks |
| `BEFORE_DDL` | Before schema changes | Capture stats |
| `AFTER_DDL` | After schema changes | Backfill, sync read models |
| `AFTER_VALIDATION` | After verification | Check integrity |
| `CLEANUP` | Before commit | Drop temp tables |
| `ON_ERROR` | On failure | Send alerts |

---

## Examples

### Validation Hook

```python
@register_hook('pre_validate')
def check_database(context: HookContext) -> None:
    with psycopg.connect() as conn:
        conn.execute("SELECT 1")
    print("Database accessible")
```

### Audit Logging

```python
@register_hook('post_execute')
def audit_log(context: HookContext) -> None:
    if context.environment != "production":
        return

    with psycopg.connect() as conn:
        conn.execute(
            "INSERT INTO audit_migrations (version, name, applied_at) VALUES (%s, %s, NOW())",
            (context.migration.version, context.migration.name)
        )
```

### Data Integrity Check

```python
@register_hook('post_execute')
def verify_emails(context: HookContext) -> None:
    with psycopg.connect() as conn:
        result = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL")
        if result.scalar() > 0:
            raise ValueError("Found NULL emails after migration!")
```

### CQRS Read Model Backfill

```python
from confiture.core.hooks import Hook, HookPhase, HookResult

class BackfillReadModel(Hook):
    phase = HookPhase.AFTER_DDL

    def execute(self, conn, context) -> HookResult:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO r_user_summary (user_id, order_count)
                SELECT u.id, COUNT(o.id)
                FROM users u LEFT JOIN orders o ON u.id = o.user_id
                GROUP BY u.id
                ON CONFLICT (user_id) DO UPDATE SET order_count = EXCLUDED.order_count
            """)
            rows = cursor.rowcount

        return HookResult(
            phase=self.phase.name,
            hook_name=self.__class__.__name__,
            rows_affected=rows
        )
```

---

## Sharing Data Between Hooks

Use `HookContext` to pass data:

```python
# BEFORE_DDL: Capture initial count
context.set_stat("initial_count", 1000)

# AFTER_VALIDATION: Verify count
initial = context.get_stat("initial_count")
if final_count < initial:
    raise ValueError("Data was lost!")
```

---

## Configuration

### Decorator (Recommended)

```python
from confiture.hooks import register_hook

@register_hook('post_execute')
def my_hook(context: HookContext) -> None:
    pass
```

### YAML Configuration

```yaml
# confiture.yaml
hooks:
  pre_execute:
    - module: "scripts.hooks"
      function: "log_migration"
```

---

## Best Practices

1. **Keep hooks fast** - Avoid expensive operations
2. **Handle errors gracefully** - Use try/except for non-critical checks
3. **Check environment** - Skip production-only checks in dev
4. **Test hooks** - Write unit tests for hook logic

```python
# Good: Handle errors
@register_hook('post_execute')
def safe_hook(context: HookContext) -> None:
    try:
        risky_operation()
    except Exception as e:
        print(f"Hook failed (non-critical): {e}")
```

---

## Hooks vs Pre-commit

| Aspect | Confiture Hooks | Git Pre-commit |
|--------|-----------------|----------------|
| **Trigger** | Migration lifecycle | Git commit |
| **Access** | Database, migration context | Files only |
| **Use case** | Data validation | Code formatting |

**Use Confiture Hooks when**:
- You need database access
- You need migration context
- Logic runs during migration

**Use Pre-commit when**:
- Linting SQL files
- Code formatting
- Preventing bad commits

---

## Troubleshooting

### Hook not executing

- Verify hook is registered with correct trigger name
- Check hook function signature matches expected

### Hook crashes migration

- Wrap non-critical operations in try/except
- Return gracefully instead of raising

---

## See Also

- [Hooks API Reference](../api/hooks.md)
- [Advanced Patterns](./advanced-patterns.md)
