# Dry-Run Mode CLI Guide

**Table of Contents**:
1. [Overview](#overview)
2. [Analyze Without Execution](#analyze-without-execution)
3. [Test in SAVEPOINT](#test-in-savepoint)
4. [Rollback Analysis](#rollback-analysis)
5. [Output Formats](#output-formats)
6. [Troubleshooting](#troubleshooting)

---

## Overview

Dry-run mode allows you to analyze migrations before executing them. This is essential for:
- **Understanding impact**: See what migrations will do before applying them
- **Risk assessment**: Identify potentially unsafe operations
- **Resource planning**: Estimate CPU, memory, and disk usage
- **Testing**: Validate migrations in a SAVEPOINT (guaranteed rollback)
- **CI/CD integration**: Automate migration safety checks

### Three Modes

| Mode | Command | Effect |
|------|---------|--------|
| **Analyze** | `--dry-run` | Shows what will happen (no execution) |
| **Test** | `--dry-run-execute` | Executes in SAVEPOINT (guaranteed rollback) |
| **Down** | `--dry-run` with `migrate down` | Analyzes rollback impact |

---

## Analyze Without Execution

The simplest dry-run mode: see what migrations will do before applying them.

### Basic Usage

```bash
confiture migrate up --dry-run
```

**Example Output**:
```
🔍 Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================
```

### Understanding the Output

- **Estimated time**: How long the migration should take (conservative estimate)
- **Disk**: Estimated storage used
- **CPU**: Estimated CPU impact (as percentage)

> **Note**: These are estimates. Actual metrics depend on your database size, complexity, and load.

### With Verbose Mode

Get more detailed information:

```bash
confiture migrate up --dry-run --verbose
```

This shows additional details about each migration (ready for future enhancements).

### Filtering to Target Version

Only analyze up to a specific migration:

```bash
confiture migrate up --dry-run --target 005_add_indexes
```

---

## Test in SAVEPOINT

Execute migrations in a transaction SAVEPOINT with guaranteed rollback. This is the closest you can get to real execution without permanently applying changes.

### Basic Usage

```bash
confiture migrate up --dry-run-execute
```

**Workflow**:
1. Show migration analysis
2. Execute each migration in a SAVEPOINT
3. Display actual execution metrics
4. Rollback all changes automatically
5. Ask for confirmation before real execution

**Example Output**:
```
🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================

🔄 Proceed with real execution? [y/N]: y

✅ Successfully applied 2 migration(s)!
```

### How SAVEPOINT Works

```sql
-- Confiture executes migrations like this:
BEGIN;
  SAVEPOINT pre_migration;
    -- Execute migration (creates tables, indexes, etc.)
  ROLLBACK TO pre_migration;  -- Undo all changes
COMMIT;
```

**Advantages**:
- ✅ Real execution (syntax errors caught)
- ✅ No permanent changes
- ✅ Realistic performance metrics
- ✅ All changes rolled back automatically

**Limitations**:
- Some operations can't run in transactions (e.g., CREATE INDEX CONCURRENTLY)
- If a migration uses `AUTOCOMMIT`, it will commit and fail

### Key Features

1. **Guaranteed Rollback**: All changes are rolled back, even if you accept confirmation
2. **User Confirmation**: You review metrics before real execution
3. **Safe Testing**: Run in your production database (changes aren't saved)

---

## Rollback Analysis

Analyze what will happen if you rollback migrations.

### Basic Usage

```bash
confiture migrate down --dry-run
```

Analyzes rollback of the last 1 applied migration (default).

### Specify Number of Migrations

```bash
confiture migrate down --dry-run --steps 3
```

Analyzes rollback of the last 3 migrations.

**Example Output**:
```
🔍 Analyzing migrations without execution...

Rollback Analysis Summary
================================================================================
Migrations to rollback: 2

  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

⚠️  Rollback will undo these migrations
================================================================================
```

---

## Output Formats

### Text Format (Default)

Human-readable, colorized output for terminal display:

```bash
confiture migrate up --dry-run
confiture migrate up --dry-run --format text  # Same as above
```

**Best for**: Quick review, interactive use

### JSON Format

Structured output for programmatic processing:

```bash
confiture migrate up --dry-run --format json
```

**Example JSON Output**:
```json
{
  "migration_id": "dry_run_local",
  "mode": "analysis",
  "statements_analyzed": 2,
  "migrations": [
    {
      "version": "001",
      "name": "create_initial_schema",
      "classification": "warning",
      "estimated_duration_ms": 500,
      "estimated_disk_usage_mb": 1.0,
      "estimated_cpu_percent": 30.0
    },
    {
      "version": "002",
      "name": "add_user_table",
      "classification": "warning",
      "estimated_duration_ms": 500,
      "estimated_disk_usage_mb": 1.0,
      "estimated_cpu_percent": 30.0
    }
  ],
  "summary": {
    "unsafe_count": 0,
    "total_estimated_time_ms": 1000,
    "total_estimated_disk_mb": 2.0,
    "has_unsafe_statements": false
  },
  "warnings": [],
  "analyses": []
}
```

**Best for**: CI/CD integration, automation, scripting

### Saving to File

Save the report for later review:

```bash
# Text format to file
confiture migrate up --dry-run --output migration_report.txt

# JSON format to file
confiture migrate up --dry-run --format json --output report.json
```

**Example Usage**:
```bash
# Generate report before important migration
confiture migrate up --dry-run --format json --output pre_migration_analysis.json

# Review JSON in Python
import json
with open('pre_migration_analysis.json') as f:
    report = json.load(f)
    print(f"Unsafe statements: {report['summary']['unsafe_count']}")
```

---

## Real-World Examples

### Example 1: Quick Safety Check

Before applying migrations to production:

```bash
$ confiture migrate up --dry-run
🔍 Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 1

  042: add_index_on_users_email
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================
```

✅ Looks safe, proceed with real execution.

### Example 2: Detailed Review

When migrations are complex:

```bash
confiture migrate up --dry-run --verbose --output review.json
```

Send `review.json` to DBA for review before execution.

### Example 3: CI/CD Integration

Validate all migrations before merging:

```bash
#!/bin/bash
# .github/workflows/migration-check.yml

# Analyze migrations
confiture migrate up --dry-run --format json --output /tmp/analysis.json

# Parse JSON and check safety
unsafe_count=$(jq '.summary.unsafe_count' /tmp/analysis.json)
if [ "$unsafe_count" -gt 0 ]; then
  echo "❌ Unsafe statements detected"
  exit 1
fi

echo "✅ Migrations appear safe"
exit 0
```

### Example 4: Testing SAVEPOINT Execution

In staging environment before production:

```bash
# Test migrations in SAVEPOINT (automatic rollback)
confiture migrate up --dry-run-execute

# Output shows actual metrics vs estimates
# Review and approve if metrics look good

# Now run for real
confiture migrate up
```

### Example 5: Safe Rollback Analysis

Before rolling back in emergency:

```bash
# Analyze what will be rolled back
confiture migrate down --dry-run --steps 2

# Output shows which 2 migrations will be undone
# Verify nothing critical, then execute
confiture migrate down --steps 2
```

---

## Troubleshooting

### Problem: "Cannot use both --dry-run and --dry-run-execute"

```bash
❌ confiture migrate up --dry-run --dry-run-execute
❌ Error: Cannot use both --dry-run and --dry-run-execute
```

**Solution**: Choose one mode:
- `--dry-run` for analysis only
- `--dry-run-execute` for SAVEPOINT testing

### Problem: "Cannot use --dry-run with --force"

```bash
❌ confiture migrate up --dry-run --force
❌ Error: Cannot use --dry-run with --force
```

**Reason**: Dry-run is for safety checks, `--force` skips checks. They contradict.

**Solution**: Use dry-run without force.

### Problem: "Invalid format 'csv'"

```bash
❌ confiture migrate up --dry-run --format csv
❌ Error: Invalid format 'csv'. Use 'text' or 'json'
```

**Solution**: Use `text` or `json`:
```bash
✅ confiture migrate up --dry-run --format json
```

### Problem: JSON Output Contains Non-JSON Text

```bash
$ confiture migrate up --dry-run --format json
🔍 Analyzing migrations without execution...

{
  "migration_id": "dry_run_local",
  ...
}
```

**Note**: The emoji/text before JSON is printed to console. When using in scripts:
```bash
# Extract JSON only
confiture migrate up --dry-run --format json | tail -n +2 | jq .
```

Or save to file:
```bash
# File output is clean JSON
confiture migrate up --dry-run --format json --output report.json
cat report.json | jq '.summary'
```

### Problem: Estimates Seem Wrong

**Note**: Estimates are *conservative approximations* based on migration complexity, not actual analysis of SQL statements. Actual execution time depends on:
- Database size
- Current load
- Available CPU/RAM
- Index efficiency
- Data distribution

For more accurate estimates in SAVEPOINT testing:
```bash
confiture migrate up --dry-run-execute
```

This executes migrations in a SAVEPOINT and shows real metrics.

---

## Best Practices

### ✅ Do

- **Use `--dry-run` before applying migrations** in any environment
- **Use `--dry-run-execute`** in staging/test before production
- **Save reports** for audit trail and reviews
- **Check output carefully** for warnings and unsafe statements
- **Test rollback** before emergency rollbacks
- **Automate in CI/CD** to catch issues early

### ❌ Don't

- Don't skip dry-run for "simple" migrations
- Don't use `--force` to skip dry-run checks
- Don't assume estimates are exact
- Don't rollback without analyzing first
- Don't apply migrations directly to production without review

---

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Migration Validation

on: [pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v3

      - name: Analyze migrations
        run: |
          confiture migrate up --dry-run --format json --output analysis.json

      - name: Check safety
        run: |
          UNSAFE=$(jq '.summary.unsafe_count' analysis.json)
          if [ "$UNSAFE" -gt 0 ]; then
            echo "❌ Unsafe migrations detected!"
            exit 1
          fi
          echo "✅ All migrations safe"

      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: migration-analysis
          path: analysis.json
```

---

## FAQ

**Q: Is dry-run mode safe to run on production?**
A: Yes, `--dry-run` only reads metadata and doesn't execute. `--dry-run-execute` uses SAVEPOINT and rolls back automatically.

**Q: How accurate are the estimates?**
A: They're conservative approximations. Use `--dry-run-execute` for real metrics.

**Q: Can I schedule dry-runs?**
A: Yes! Combine with cron or CI/CD for regular validation checks.

**Q: What if a migration fails in SAVEPOINT testing?**
A: The SAVEPOINT is rolled back. You can review the error and fix the migration file before running for real.

**Q: How do I automate migration safety checks?**
A: Use JSON format with CI/CD pipelines (see example above).

---

**For more help**:
- Run `confiture migrate up --help`
- Run `confiture migrate down --help`
- Check the main [README.md](../../README.md)

