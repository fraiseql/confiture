# Structured Output Guide

Export Confiture command results in **JSON** or **CSV** format for automation, integration, and reporting.

## Overview

All major Confiture commands support structured output via `--format` and `--report` options:

```bash
# Output to console as JSON
confiture build --format json

# Save as JSON to file
confiture build --format json --report build-result.json

# Export as CSV for spreadsheet/analysis
confiture migrate status --format csv --report migrations.csv
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
```bash
confiture migrate status --format csv --report status.csv
```
Generates tabular data for spreadsheets or data analysis:
```csv
version,name,status
001,initial_schema,applied
002,add_users,applied
003,add_indexes,pending
```

## Supported Commands

| Command | JSON | CSV | Notes |
|---------|------|-----|-------|
| `build` | ✅ | ✅ | Schema compilation metrics |
| `migrate up` | ✅ | ✅ | Migration execution details |
| `migrate down` | ✅ | ✅ | Rollback tracking |
| `migrate status` | ✅ | ✅ | Migration inventory |
| `migrate diff` | ✅ | ✅ | Schema change detection |
| `migrate validate` | ✅ | ✅ | Validation results |
| `seed apply` | ✅ | ✅ | Seed operation summary |

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

**Output Fields (JSON):**
```json
{
  "success": boolean,
  "migrations_applied": [
    {
      "version": string,
      "name": string,
      "execution_time_ms": number,
      "rows_affected": number
    }
  ],
  "count": number,
  "total_execution_time_ms": number,
  "checksums_verified": boolean,
  "dry_run": boolean,
  "warnings": string[],
  "error": string | null
}
```

**CSV Columns:** `version, name, execution_time_ms, rows_affected`

**Examples:**
```bash
# Dry-run migrations and get JSON output
confiture migrate up --dry-run --format json

# Apply migrations and save results
confiture migrate up --format json --report up.json

# Export migration details as CSV
confiture migrate up --format csv --report migrations.csv
```

### confiture migrate down

**Purpose:** Rollback previously applied migrations

**Output Fields (JSON):**
```json
{
  "success": boolean,
  "migrations_rolled_back": [
    {
      "version": string,
      "name": string,
      "execution_time_ms": number,
      "rows_affected": number
    }
  ],
  "count": number,
  "total_execution_time_ms": number,
  "checksums_verified": boolean,
  "warnings": string[],
  "error": string | null
}
```

**CSV Columns:** `version, name, execution_time_ms, rows_affected`

**Examples:**
```bash
# Preview rollback before executing
confiture migrate down --dry-run --format json

# Execute rollback and save report
confiture migrate down --steps 2 --format json --report rollback.json
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

**CSV Columns:** `version, name, status`

**Examples:**
```bash
# Show migration status as JSON
confiture migrate status --format json

# Save migration inventory as CSV
confiture migrate status --format csv --report inventory.csv
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

**CSV Columns:** `check, count`

**Examples:**
```bash
# Validate migrations and get JSON output
confiture migrate validate --format json

# Save validation report as CSV
confiture migrate validate --format csv --report validation.csv

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
confiture migrate up --format json --report migrations.json
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
confiture migrate status --format json --report "status_$(date +%Y-%m-%d).json"

# Create CSV for spreadsheet
confiture migrate status --format csv --report "migrations_$(date +%Y-%m-%d).csv"

# Archive results
mkdir -p migration-audits
cp status_*.json migration-audits/
cp migrations_*.csv migration-audits/
```

## Parsing Output

### Using jq (JSON)

```bash
# Extract success status
confiture build --format json | jq '.success'

# Get execution time
confiture migrate up --format json | jq '.total_execution_time_ms'

# List all applied migrations
confiture migrate status --format json | jq '.applied[]'

# Count changes
confiture migrate diff old.sql new.sql --format json | jq '.change_count'
```

### Using grep/awk (CSV)

```bash
# Count applied migrations
confiture migrate status --format csv | grep "applied" | wc -l

# Find pending migrations
confiture migrate status --format csv | grep "pending"

# Extract version column
confiture migrate status --format csv | cut -d',' -f1
```

## Error Handling

When a command fails, the output format is respected:

**JSON Error Response:**
```json
{
  "success": false,
  "error": "Database connection failed",
  ...
}
```

**CSV Error Response:**
```csv
error
"Database connection failed"
```

Check the `success` field (JSON) or look for error rows (CSV) to determine if an operation succeeded.

## Best Practices

### 1. Use Meaningful Report Names
```bash
# Good: Timestamp and operation type
confiture migrate up --format json --report "migrate_up_$(date +%Y%m%d_%H%M%S).json"

# Less clear
confiture migrate up --format json --report result.json
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
confiture migrate status --format csv --report "status_$(date -u +%Y-%m-%dT%H:%M:%SZ).csv"
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
