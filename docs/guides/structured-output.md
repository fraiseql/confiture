# Structured Output Guide

Export Confiture command results in **JSON** or **CSV** format for automation, integration, and reporting.

## Overview

Many Confiture commands support structured output via `--format`, plus a flag to
save it to a file. The save flag differs by command: the **migrate** family uses
`--output`/`-o`, while `build`, `migrate diff`, and `seed apply` use `--report`.

```bash
# Output to console as JSON
confiture build --format json

# Save JSON to a file (build / seed apply / migrate diff use --report)
confiture build --format json --report build-result.json

# Save migrate output to a file (the migrate family uses --output / -o)
confiture migrate status --format json --output status.json

# Export as CSV (CSV is supported by build, migrate diff, and seed apply)
confiture seed apply --format csv --report seeds.csv
```

## Quick Start

### Text Output (Default)
```bash
confiture build
```
Shows formatted console output with colors and emoji indicators.

### JSON Output
```bash
confiture build --format json --report result.json
```
Returns structured data suitable for parsing and automation:
```json
{
  "success": true,
  "files_processed": 15,
  "schema_size_bytes": 24576,
  "output_path": "/path/to/schema.sql",
  "execution_time_ms": 245,
  "seed_files_applied": 3
}
```

### CSV Output

CSV is supported by `build`, `migrate diff`, and `seed apply` (not the
`migrate up/down/status` family, which emit text/JSON only):

```bash
confiture migrate diff old.sql new.sql --format csv --report changes.csv
```
Generates tabular data for spreadsheets or data analysis:
```csv
type,details
add_column,users.email VARCHAR(255)
drop_index,old_users_idx
```

## Supported Commands

| Command | JSON | CSV | Save flag | Notes |
|---------|------|-----|-----------|-------|
| `build` | ✅ | ✅ | `--report` | Schema compilation metrics |
| `migrate up` | ✅ | — | `--output` | `--format text\|json` |
| `migrate down` | ✅ | — | `--output` | `--format text\|json` |
| `migrate status` | ✅ | — | `--output` | `--format table\|json` |
| `migrate diff` | ✅ | ✅ | `--report` | Schema change detection |
| `migrate validate` | ✅ | — | `--output` | `--format text\|json` |
| `seed apply` | ✅ | ✅ | `--report` | Seed operation summary |

## Command Reference

### confiture build

**Purpose:** Build database schema from DDL files

**Output Fields (JSON):**
```json
{
  "success": boolean,
  "files_processed": number,
  "schema_size_bytes": number,
  "output_path": string,
  "hash": string | null,
  "execution_time_ms": number,
  "seed_files_applied": number,
  "warnings": string[],
  "error": string | null
}
```

**CSV Columns:** `metric, value`

**Examples:**
```bash
# Show build metrics as JSON
confiture build --format json

# Save build report
confiture build --format json --report build.json

# Export metrics as CSV
confiture build --format csv --report metrics.csv
```

### confiture migrate up

**Purpose:** Apply pending migrations

**Output Fields (JSON)** — the keys of `MigrateUpResult.to_dict()`:

<!-- doctest:migrate-up-json -->
```json
{
  "success": true,
  "applied": [
    {
      "version": "20260403120000",
      "name": "create_users",
      "execution_time_ms": 12,
      "rows_affected": 0
    }
  ],
  "skipped": [],
  "skipped_superuser": [],
  "pending": [],
  "errors": [],
  "total_duration_ms": 12,
  "checksums_verified": true,
  "dry_run": false,
  "dry_run_execute": false,
  "warnings": []
}
```

**Examples:**
```bash
# Dry-run migrations and get JSON output
confiture migrate up --dry-run --format json

# Apply migrations and save the JSON result to a file
confiture migrate up --format json --output up.json
```

### confiture migrate down

**Purpose:** Rollback previously applied migrations

**Output Fields (JSON)** — the keys of `MigrateDownResult.to_dict()`:
```json
{
  "success": true,
  "rolled_back": [
    {
      "version": "20260403120000",
      "name": "create_users",
      "execution_time_ms": 8,
      "rows_affected": 0
    }
  ],
  "total_duration_ms": 8,
  "checksums_verified": true,
  "warnings": [],
  "error": null
}
```

**Examples:**
```bash
# Preview rollback before executing
confiture migrate down --dry-run --format json

# Execute rollback and save the JSON report
confiture migrate down --steps 2 --format json --output rollback.json
```

### confiture migrate status

**Purpose:** View migration history and pending migrations

**Output Fields (JSON):**
```json
{
  "applied": string[],
  "pending": string[],
  "current": string | null,
  "total": number,
  "migrations": [
    {
      "version": string,
      "name": string,
      "status": "applied" | "pending" | "unknown"
    }
  ],
  "orphaned_migrations": string[] | undefined,
  "duplicate_versions": object | undefined
}
```

**Examples:**
```bash
# Show migration status as JSON
confiture migrate status --format json

# Save migration inventory to a file
confiture migrate status --format json --output inventory.json
```

### confiture migrate diff

**Purpose:** Compare two schema files and identify differences

**Output Fields (JSON):**
```json
{
  "success": boolean,
  "has_changes": boolean,
  "changes": [
    {
      "type": string,
      "details": string
    }
  ],
  "change_count": number,
  "migration_generated": boolean,
  "migration_file": string | null,
  "error": string | null
}
```

**CSV Columns:** `type, details`

**Examples:**
```bash
# Compare schemas and get JSON output
confiture migrate diff old.sql new.sql --format json

# Generate migration and save diff report
confiture migrate diff old.sql new.sql --generate --name add_features \
  --format json --report diff.json
```

### confiture migrate validate

**Purpose:** Validate migration files and conventions

**Output Fields (JSON):**
```json
{
  "success": boolean,
  "orphaned_files": string[],
  "orphaned_files_count": number,
  "duplicate_versions": object,
  "duplicate_versions_count": number,
  "fixed_files": string[],
  "fixed_files_count": number,
  "warnings": string[],
  "error": string | null
}
```

**Examples:**
```bash
# Validate migrations and get JSON output
confiture migrate validate --format json

# Save validation report to a file
confiture migrate validate --format json --output validation.json

# Preview naming fixes
confiture migrate validate --fix-naming --dry-run --format json
```

### confiture seed apply

**Purpose:** Load seed data into database

**Output Fields (JSON):**
```json
{
  "total": number,
  "succeeded": number,
  "failed": number,
  "failed_files": string[],
  "success": boolean
}
```

**CSV Columns:** `metric, value`

**Examples:**
```bash
# Apply seeds and get JSON results
confiture seed apply --format json

# Save seed operation report
confiture seed apply --format json --report seeds.json
```

## Integration Examples

### CI/CD Pipeline

```bash
#!/bin/bash

# Build schema and fail if unsuccessful
confiture build --format json --report build.json
BUILD_RESULT=$(cat build.json | jq '.success')
if [ "$BUILD_RESULT" != "true" ]; then
  echo "❌ Build failed"
  exit 1
fi

# Migrate database
confiture migrate up --format json --output migrations.json
MIGRATE_SUCCESS=$(cat migrations.json | jq '.success')
if [ "$MIGRATE_SUCCESS" != "true" ]; then
  echo "❌ Migration failed"
  exit 1
fi

# Apply seeds
confiture seed apply --format json --report seeds.json
SEED_SUCCESS=$(cat seeds.json | jq '.success')
if [ "$SEED_SUCCESS" != "true" ]; then
  echo "❌ Seed failed"
  exit 1
fi

echo "✅ All operations successful"
```

### Performance Tracking

```bash
#!/bin/bash

# Track build performance over time
confiture build --format json --report "build_$(date +%s).json"

# Extract metrics
EXEC_TIME=$(cat build_*.json | jq '.execution_time_ms' | awk '{sum+=$1} END {print sum/NR}')
SCHEMA_SIZE=$(cat build_*.json | jq '.schema_size_bytes' | awk '{sum+=$1} END {print sum/NR}')

echo "Average execution time: ${EXEC_TIME}ms"
echo "Average schema size: ${SCHEMA_SIZE} bytes"
```

### Migration Audit Log

```bash
#!/bin/bash

# Create audit trail of all migrations
confiture migrate status --format json --output "status_$(date +%Y-%m-%d).json"

# Archive results
mkdir -p migration-audits
cp status_*.json migration-audits/
```

## Parsing Output

### Using jq (JSON)

```bash
# Extract success status
confiture build --format json | jq '.success'

# Get execution time
confiture migrate up --format json | jq '.total_duration_ms'

# List all applied migrations
confiture migrate status --format json | jq '.applied[]'

# Count changes
confiture migrate diff old.sql new.sql --format json | jq '.change_count'
```

### Using grep/awk (CSV)

CSV is emitted by `build`, `migrate diff`, and `seed apply`:

```bash
# Extract the metric column from a build report
confiture build --format csv | cut -d',' -f1

# Count failed seed files
confiture seed apply --format csv | grep -c "failed"
```

For the `migrate up/down/status` family (JSON only), parse with `jq` instead —
e.g. `confiture migrate status --format json | jq -r '.migrations[].version'`.

## Error Handling

When a command fails, JSON output is the unified error envelope — `ok: false`
plus a structured `error` object:

```json
{
  "ok": false,
  "error": {
    "code": "CONFIG_006",
    "message": "Database connection failed",
    "severity": "error",
    "actionable": "Check database_url and that PostgreSQL is reachable"
  }
}
```

The process exit code is derived from `error.code` (see the
[CLI reference](../reference/cli.md)).

Distinguish this from a command that *runs* but reports per-item failures in its
result body — e.g. `migrate up` returns `"success": false` with a populated
`errors` array (exit code 0 for the run, non-zero only on a hard failure).
Detect failures by checking `ok` (envelope) or `success` (result body).

## Best Practices

### 1. Use Meaningful Report Names
```bash
# Good: Timestamp and operation type
confiture migrate up --format json --output "migrate_up_$(date +%Y%m%d_%H%M%S).json"

# Less clear
confiture migrate up --format json --output result.json
```

### 2. Validate Output Before Processing
```bash
# Extract and validate
confiture build --format json --report build.json
if ! jq empty build.json 2>/dev/null; then
  echo "❌ Invalid JSON"
  exit 1
fi
```

### 3. Combine with Timestamps
```bash
# Create audit trail with timestamps
confiture migrate status --format json --output "status_$(date -u +%Y-%m-%dT%H:%M:%SZ).json"
```

### 4. Use Appropriate Format for Purpose
- **JSON**: Automation, CI/CD pipelines, programmatic parsing
- **CSV**: Spreadsheets, data analysis, human review
- **Text**: Interactive use, immediate feedback

## Backward Compatibility

- Default format is always **text** (unchanged)
- Existing scripts using text output continue to work
- Structured output is opt-in via `--format` flag
- No breaking changes to existing behavior

## Troubleshooting

### Invalid Format Error
```
❌ Invalid format: excel. Use text, json, or csv
```
Ensure format is one of: `text`, `json`, `csv`

### File Not Found
```
[red]✗ Output file directory does not exist[/red]
```
Create parent directories before writing:
```bash
mkdir -p results/
confiture build --format json --report results/build.json
```

### CSV Parsing Issues
If CSV contains special characters (commas, quotes), they are properly escaped:
```
"column_name,with,commas","column_name_with_"_quotes"
```

## Examples Repository

See `examples/` directory for complete working examples:
- `examples/structured-output/` - Full CI/CD integration examples
- `examples/performance-tracking/` - Performance monitoring scripts
- `examples/audit-trail/` - Audit logging setup

## See Also

- **[CLI Reference](../reference/cli.md)** - All CLI options
- **[Configuration Guide](../reference/configuration.md)** - Environment setup
- **[API Documentation](../api/)** - Programmatic access
