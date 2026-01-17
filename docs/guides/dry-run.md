# Dry-Run Mode

[← Back to Guides](../index.md) · [Integrations](integrations.md)

Test migrations before execution using analysis or SAVEPOINT-based testing.

---

## Quick Start

```bash
# Analyze without executing
confiture migrate up --dry-run

# Execute in SAVEPOINT (guaranteed rollback)
confiture migrate up --dry-run-execute
```

---

## Two Modes

| Mode | Flag | Effect |
|------|------|--------|
| **Analyze** | `--dry-run` | Shows impact without execution |
| **Test** | `--dry-run-execute` | Executes in SAVEPOINT, rolls back |

---

## Analysis Mode

See what migrations will do before applying:

```bash
confiture migrate up --dry-run
```

**Output**:
```
Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

All migrations appear safe to execute
================================================================================
```

### Target Specific Version

```bash
confiture migrate up --dry-run --target 005_add_indexes
```

### Rollback Analysis

```bash
confiture migrate down --dry-run --steps 3
```

---

## SAVEPOINT Testing

Execute migrations with guaranteed rollback:

```bash
confiture migrate up --dry-run-execute
```

**How it works**:
```sql
BEGIN;
  SAVEPOINT pre_migration;
    -- Execute migration
  ROLLBACK TO pre_migration;
COMMIT;
```

**Advantages**:
- Catches syntax errors
- Shows real execution metrics
- No permanent changes
- Safe to run on production

**Limitations**:
- `CREATE INDEX CONCURRENTLY` can't run in transactions
- `AUTOCOMMIT` operations will fail

---

## Output Formats

### JSON for CI/CD

```bash
confiture migrate up --dry-run --format json --output report.json
```

```json
{
  "migration_id": "dry_run_local",
  "mode": "analysis",
  "migrations": [
    {
      "version": "001",
      "name": "create_initial_schema",
      "estimated_duration_ms": 500
    }
  ],
  "summary": {
    "unsafe_count": 0,
    "has_unsafe_statements": false
  }
}
```

### CI/CD Integration

```bash
#!/bin/bash
confiture migrate up --dry-run --format json --output analysis.json

unsafe=$(jq '.summary.unsafe_count' analysis.json)
if [ "$unsafe" -gt 0 ]; then
  echo "Unsafe migrations detected"
  exit 1
fi
```

---

## Python API

```python
from confiture.core.dry_run import DryRunExecutor

executor = DryRunExecutor()
result = executor.run(conn, migration)

if result.success:
    print(f"Time: {result.execution_time_ms}ms")
    print(f"Rows: {result.rows_affected}")
    print(f"Locked tables: {result.locked_tables}")
else:
    for warning in result.warnings:
        print(f"Warning: {warning}")
```

---

## Best Practices

1. **Always dry-run before production**
2. **Use `--dry-run-execute`** in staging for realistic metrics
3. **Save reports** for audit trails
4. **Automate in CI/CD** to catch issues early
5. **Analyze rollbacks** before emergency rollbacks

---

## Troubleshooting

### "Cannot use both --dry-run and --dry-run-execute"

Choose one mode - they're mutually exclusive.

### "Cannot use --dry-run with --force"

Dry-run is for safety checks; `--force` skips checks. They contradict.

### Estimates seem wrong

Estimates are conservative approximations. Use `--dry-run-execute` for real metrics.

---

## See Also

- [CLI Reference](../reference/cli.md)
- [Incremental Migrations](./02-incremental-migrations.md)
