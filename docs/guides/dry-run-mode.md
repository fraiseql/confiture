# Dry-Run Mode Guide: Test Migrations Before Execution

**Feature: Migration Dry-Run Mode**

This guide explains how to use Confiture's dry-run mode to test migrations before executing them. Dry-run mode executes migrations within a transaction that is automatically rolled back, allowing you to verify migrations without modifying your database.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Understanding Results](#understanding-results)
4. [CLI Integration](#cli-integration)
5. [Real-World Examples](#real-world-examples)
6. [Troubleshooting](#troubleshooting)
7. [Best Practices](#best-practices)

---

## Overview

Dry-run mode executes migrations in a transaction with **guaranteed rollback**. This allows you to:

- **Test Execution**: Verify migrations run without errors
- **Measure Performance**: Capture actual execution time
- **Detect Issues**: Find constraint violations before production
- **Review Impact**: See rows affected and tables locked

### Key Capabilities

| Feature | Details |
|---------|---------|
| **Transaction Rollback** | All changes are automatically rolled back |
| **Execution Metrics** | Time, rows affected, locked tables captured |
| **Production Estimates** | Confidence-based time predictions |
| **Warning Detection** | Identifies potential issues during execution |

---

## Quick Start

### Basic Dry-Run Execution

```python
import psycopg
from confiture.core.dry_run import DryRunExecutor, DryRunResult

# Connect to database
conn = psycopg.connect("postgresql://localhost/mydb")

# Create executor
executor = DryRunExecutor()

# Execute migration in dry-run mode
result = executor.run(conn, migration)

# Check results
if result.success:
    print(f"Migration {result.migration_name} succeeded")
    print(f"Execution time: {result.execution_time_ms}ms")
    print(f"Rows affected: {result.rows_affected}")
else:
    print(f"Migration failed")
    for warning in result.warnings:
        print(f"  Warning: {warning}")
```

### With Error Handling

```python
from confiture.core.dry_run import DryRunExecutor, DryRunError

executor = DryRunExecutor()

try:
    result = executor.run(conn, migration)

    if result.success:
        print(f"Ready to execute: {result.migration_name}")
        print(f"Estimated production time: {result.estimated_production_time_ms}ms")
        print(f"Confidence: {result.confidence_percent}%")
    else:
        print("Dry-run completed with issues")

except DryRunError as e:
    print(f"Dry-run failed for {e.migration_name}")
    print(f"Error: {e.original_error}")
```

---

## Understanding Results

### DryRunResult Fields

The `DryRunResult` dataclass contains all execution metrics:

```python
@dataclass
class DryRunResult:
    migration_name: str           # Migration identifier
    migration_version: str        # Version string
    success: bool                 # Whether execution succeeded
    execution_time_ms: int        # Actual execution time
    rows_affected: int            # Number of rows modified
    locked_tables: list[str]      # Tables that were locked
    estimated_production_time_ms: int  # Predicted production time
    confidence_percent: int       # Estimate confidence (0-100)
    warnings: list[str]           # List of warnings
    stats: dict[str, Any]         # Additional statistics
```

### Interpreting Results

#### Execution Time

```python
result = executor.run(conn, migration)

print(f"Actual time: {result.execution_time_ms}ms")
print(f"Estimated production time: {result.estimated_production_time_ms}ms")
print(f"Confidence: {result.confidence_percent}%")

# High confidence (>80%) means estimate is reliable
# Low confidence (<50%) means results may vary in production
```

#### Locked Tables

```python
if result.locked_tables:
    print("Tables locked during migration:")
    for table in result.locked_tables:
        print(f"  - {table}")

    # If many tables locked, consider running during maintenance
    if len(result.locked_tables) > 3:
        print("Warning: Multiple tables locked - schedule during low traffic")
```

#### Warnings

```python
if result.warnings:
    print("Warnings detected:")
    for warning in result.warnings:
        print(f"  - {warning}")

    # Decide whether to proceed based on warnings
    if any("constraint" in w.lower() for w in result.warnings):
        print("Constraint issue detected - review before proceeding")
```

---

## CLI Integration

### Helper Functions

Confiture provides CLI helper functions for dry-run integration:

```python
from pathlib import Path
from confiture.cli.dry_run import (
    save_text_report,
    save_json_report,
    print_json_report,
    display_dry_run_header,
    ask_dry_run_execute_confirmation,
)

# Display header
display_dry_run_header("testing")
# Output: 🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...

# Save reports
save_text_report("Migration completed successfully", Path("reports/dry-run.txt"))
save_json_report({"success": True, "time_ms": 250}, Path("reports/dry-run.json"))

# Print JSON to console
print_json_report({"success": True, "time_ms": 250})

# Ask for confirmation
if ask_dry_run_execute_confirmation():
    print("Proceeding with real execution...")
else:
    print("Execution cancelled")
```

### Display Modes

```python
# For analysis-only mode
display_dry_run_header("analysis")
# Output: 🔍 Analyzing migrations without execution...

# For execute-and-rollback mode
display_dry_run_header("testing")
# Output: 🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...
```

---

## Real-World Examples

### Example 1: Pre-Production Validation

**Scenario**: Validate migration before deploying to production

```python
from confiture.core.dry_run import DryRunExecutor, DryRunError

def validate_migration(conn, migration):
    """Validate migration in dry-run mode before production."""
    executor = DryRunExecutor()

    try:
        result = executor.run(conn, migration)

        if not result.success:
            print(f"Migration {result.migration_name} failed validation")
            return False

        # Check execution time
        if result.execution_time_ms > 5000:  # >5 seconds
            print(f"Warning: Slow migration ({result.execution_time_ms}ms)")
            print("Consider running during maintenance window")

        # Check locked tables
        if len(result.locked_tables) > 5:
            print(f"Warning: {len(result.locked_tables)} tables locked")
            print("Consider batching or off-peak execution")

        # Check warnings
        if result.warnings:
            print("Warnings detected:")
            for w in result.warnings:
                print(f"  - {w}")

        print(f"Migration validated successfully")
        print(f"  Time: {result.execution_time_ms}ms")
        print(f"  Rows: {result.rows_affected}")
        return True

    except DryRunError as e:
        print(f"Validation failed: {e}")
        return False


# Usage
if validate_migration(staging_conn, migration):
    print("Approved for production")
else:
    print("Review required before production")
```

### Example 2: Batch Migration Testing

**Scenario**: Test multiple migrations in sequence

```python
def test_migration_batch(conn, migrations):
    """Test a batch of migrations in dry-run mode."""
    executor = DryRunExecutor()
    results = []

    for migration in migrations:
        try:
            result = executor.run(conn, migration)
            results.append({
                "name": result.migration_name,
                "success": result.success,
                "time_ms": result.execution_time_ms,
                "warnings": result.warnings
            })
        except DryRunError as e:
            results.append({
                "name": e.migration_name,
                "success": False,
                "error": str(e.original_error)
            })

    # Summary
    successful = sum(1 for r in results if r["success"])
    print(f"Tested {len(migrations)} migrations: {successful} passed")

    total_time = sum(r.get("time_ms", 0) for r in results)
    print(f"Total estimated time: {total_time}ms")

    failed = [r for r in results if not r["success"]]
    if failed:
        print("Failed migrations:")
        for r in failed:
            print(f"  - {r['name']}: {r.get('error', 'unknown')}")

    return results
```

### Example 3: CI/CD Integration

**Scenario**: Automate dry-run in CI pipeline

```python
import sys
import json
from pathlib import Path

def ci_dry_run_check(conn, migration, report_path: Path):
    """CI-friendly dry-run check with JSON report."""
    from confiture.core.dry_run import DryRunExecutor, DryRunError
    from confiture.cli.dry_run import save_json_report

    executor = DryRunExecutor()

    report = {
        "migration": None,
        "success": False,
        "execution_time_ms": 0,
        "warnings": [],
        "error": None
    }

    try:
        result = executor.run(conn, migration)

        report["migration"] = result.migration_name
        report["success"] = result.success
        report["execution_time_ms"] = result.execution_time_ms
        report["warnings"] = result.warnings
        report["rows_affected"] = result.rows_affected

        # Save report
        save_json_report(report, report_path)

        # Exit with appropriate code
        if result.success and not result.warnings:
            print("CI Check: PASSED")
            return 0
        elif result.success:
            print("CI Check: PASSED with warnings")
            return 0
        else:
            print("CI Check: FAILED")
            return 1

    except DryRunError as e:
        report["migration"] = e.migration_name
        report["error"] = str(e.original_error)
        save_json_report(report, report_path)
        print(f"CI Check: FAILED - {e}")
        return 1


# Usage in CI
# exit_code = ci_dry_run_check(conn, migration, Path("dry-run-report.json"))
# sys.exit(exit_code)
```

---

## Troubleshooting

### Common Issues

#### "DryRunError: Migration failed"

**Cause**: The migration SQL has errors or constraint violations

**Solution**:
```python
try:
    result = executor.run(conn, migration)
except DryRunError as e:
    print(f"Migration: {e.migration_name}")
    print(f"Original error: {e.original_error}")
    # Fix the SQL and retry
```

#### "Execution time is 0ms"

**Cause**: Migration has no actual SQL to execute

**Solution**:
```python
# Check if migration has content
if result.execution_time_ms == 0:
    print("Migration may be empty or only contains comments")
```

#### "Locked tables list is empty"

**Cause**: Read-only operations don't acquire locks

**Solution**:
```python
# This is expected for SELECT statements
if not result.locked_tables:
    print("No locks acquired (read-only operation)")
```

---

## Best Practices

### 1. Always Dry-Run Before Production

```python
# Before any production migration:
result = executor.run(staging_conn, migration)

if result.success:
    # Proceed to production
    pass
else:
    # Fix issues first
    pass
```

### 2. Check Execution Time Thresholds

```python
SLOW_THRESHOLD_MS = 5000  # 5 seconds
VERY_SLOW_THRESHOLD_MS = 30000  # 30 seconds

if result.execution_time_ms > VERY_SLOW_THRESHOLD_MS:
    print("CRITICAL: Very slow migration - requires maintenance window")
elif result.execution_time_ms > SLOW_THRESHOLD_MS:
    print("WARNING: Slow migration - consider low-traffic period")
```

### 3. Review Warnings Thoroughly

```python
CRITICAL_WARNINGS = ["constraint", "foreign key", "unique", "not null"]

for warning in result.warnings:
    if any(crit in warning.lower() for crit in CRITICAL_WARNINGS):
        print(f"CRITICAL: {warning}")
        # Require manual approval
```

### 4. Save Reports for Audit

```python
from confiture.cli.dry_run import save_json_report
from datetime import datetime

report_data = {
    "timestamp": datetime.now().isoformat(),
    "migration": result.migration_name,
    "version": result.migration_version,
    "success": result.success,
    "execution_time_ms": result.execution_time_ms,
    "rows_affected": result.rows_affected,
    "warnings": result.warnings,
}

save_json_report(report_data, Path(f"audits/{result.migration_name}.json"))
```

### 5. Use Confidence Levels

```python
if result.confidence_percent >= 80:
    print("High confidence - estimate is reliable")
elif result.confidence_percent >= 50:
    print("Medium confidence - add buffer time")
else:
    print("Low confidence - run additional tests")
```

---

## See Also

- [API Reference: Dry-Run Mode](../reference/dry-run-api.md)
- [Migration Guide](./migration-strategies.md)

---

**Version**: 2.0
**Last Updated**: January 2026
**Note**: This guide reflects the current simplified dry-run implementation.
