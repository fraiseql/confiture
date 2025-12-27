# Dry-Run Mode Guide: Analyze Migrations Before Execution

**Feature 4: Migration Dry-Run Mode**

This guide explains how to use Confiture's dry-run mode to analyze migrations before executing them. Dry-run mode provides comprehensive analysis including impact assessment, concurrency risk evaluation, and cost estimation - all without modifying your database.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Analysis Modes](#analysis-modes)
4. [Understanding Results](#understanding-results)
5. [Advanced Configuration](#advanced-configuration)
6. [Real-World Examples](#real-world-examples)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Overview

Dry-run mode analyzes SQL migrations **without executing them** (in analysis-only mode) or **with guaranteed rollback** (in execute-and-analyze mode). This allows you to:

- **Assess Impact**: Understand which tables are affected, row counts, and data size changes
- **Evaluate Risk**: Detect potential lock conflicts and concurrency issues
- **Estimate Cost**: Predict execution time, disk usage, and CPU impact
- **Review Safety**: Identify unsafe operations before production deployment

### Key Capabilities

| Feature | Details |
|---------|---------|
| **Statement Classification** | Categorizes statements as SAFE, WARNING, or UNSAFE |
| **Impact Analysis** | Table impacts, row counts, constraint violations, size estimates |
| **Concurrency Analysis** | Lock prediction, blocking queries, risk level assessment |
| **Cost Estimation** | Time, disk, CPU predictions with threshold-based warnings |
| **Selective Components** | Run fast analysis (classification only) or comprehensive analysis |
| **Two Modes** | analyze() for metadata queries or execute_and_analyze() for SAVEPOINT testing |
| **Multiple Formats** | Text reports for humans, JSON for programmatic consumption |

---

## Quick Start

### Basic Analysis (Fastest)

```python
from confiture.core.migration.dry_run.dry_run_mode import DryRunMode
from psycopg import AsyncConnection

# Lightweight analysis (classification only)
dry_run = DryRunMode(
    analyze_impact=False,
    analyze_concurrency=False,
    estimate_costs=False
)

# Analyze statements without touching database
report = await dry_run.analyze(
    statements=[
        "ALTER TABLE users ADD COLUMN bio TEXT",
        "CREATE INDEX idx_bio ON users(bio)",
    ],
    connection=connection,
    migration_id="migration_001"
)

# View results
print(f"Unsafe statements: {report.unsafe_count}")
for warning in report.warnings:
    print(f"⚠️  {warning}")
```

### Comprehensive Analysis

```python
# Full analysis with all components
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

# Analyze statements
report = await dry_run.analyze(
    statements=[
        "ALTER TABLE users ADD COLUMN bio TEXT",
        "DELETE FROM logs WHERE created_at < NOW() - INTERVAL '1 year'",
    ],
    connection=connection,
    migration_id="migration_002"
)

# Inspect detailed results
for analysis in report.analyses:
    print(f"Statement: {analysis.statement}")
    print(f"  Classification: {analysis.classification}")
    print(f"  Impact: {analysis.impact}")
    print(f"  Concurrency: {analysis.concurrency}")
    print(f"  Cost: {analysis.cost}")
```

### Execute and Analyze (Most Realistic)

```python
# Full analysis with actual execution in SAVEPOINT
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

# Execute in SAVEPOINT (guaranteed rollback)
report = await dry_run.execute_and_analyze(
    statements=[
        "ALTER TABLE users ADD COLUMN bio TEXT",
    ],
    connection=connection,
    migration_id="migration_003"
)

# Results include actual execution time
for analysis in report.analyses:
    print(f"Actual execution time: {analysis.execution_time_ms}ms")
    print(f"Estimated time: {analysis.cost.estimated_duration_ms}ms")
    print(f"Estimate accuracy: {analysis.execution_time_ms / analysis.cost.estimated_duration_ms * 100:.0f}%")
```

---

## Analysis Modes

### Mode 1: analyze() - Metadata Only

**When to use**: Quick analysis, no production impact, fast results

```python
dry_run = DryRunMode()
report = await dry_run.analyze(
    statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    connection=connection
)
```

**Characteristics**:
- ✅ Fast: 50-100ms per statement
- ✅ Zero database modification
- ✅ Uses only metadata queries
- ⚠️ Estimates are heuristic-based
- ⚠️ Execution time is predicted, not actual

**Performance**:
```
Classification:    <1ms per statement
Impact analysis:   10-50ms per statement
Concurrency:       <5ms per statement
Cost estimation:   <5ms per statement
────────────────────────────────
Total:            20-60ms per statement
```

### Mode 2: execute_and_analyze() - With SAVEPOINT

**When to use**: Pre-production validation, realistic results, need actual measurements

```python
dry_run = DryRunMode()
report = await dry_run.execute_and_analyze(
    statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    connection=connection
)
```

**Characteristics**:
- ✅ Realistic: Executes actual SQL
- ✅ Accurate metrics: Real execution time, actual row counts
- ✅ Guaranteed rollback: No data left behind
- ⚠️ Slower: 100-1000ms per statement
- ⚠️ Requires transaction capability

**Performance**:
```
Execution in SAVEPOINT:  10-1000ms per statement
Post-execution analysis: 20-60ms per statement
────────────────────────────────
Total:                  30-1100ms per statement
```

**Safety Guarantee**:
```sql
-- All statements wrapped in SAVEPOINT
BEGIN;
  SAVEPOINT migration;
    -- Your migration statement here
  ROLLBACK TO SAVEPOINT migration;
COMMIT;
-- No data modified!
```

---

## Understanding Results

### Classification Levels

Each statement is classified into one of three categories:

#### SAFE ✓
- Read-only operations (SELECT)
- Simple inserts without constraints
- Non-blocking schema changes

**Examples**:
```sql
SELECT * FROM users
INSERT INTO logs VALUES (...)
-- Safe to execute
```

#### WARNING ⚠️
- ALTER TABLE operations
- Index creation/modification
- Schema changes that require locks
- May cause temporary service impact

**Examples**:
```sql
ALTER TABLE users ADD COLUMN bio TEXT
CREATE INDEX idx_email ON users(email)
-- Use with caution, best during low-traffic periods
```

#### UNSAFE ❌
- Destructive operations
- DELETE/UPDATE without WHERE clause
- DROP TABLE/INDEX
- Operations affecting production data

**Examples**:
```sql
DELETE FROM users  -- Missing WHERE clause!
DROP TABLE legacy_data
UPDATE accounts SET balance = 0  -- Oops!
-- Requires explicit confirmation before execution
```

### Impact Analysis

Impact analysis shows which tables are affected and how:

```python
analysis = report.analyses[0]
impact = analysis.impact

print(f"Affected tables: {impact.affected_tables}")
# ['users', 'orders']

for table_name, table_impact in impact.impact_by_table.items():
    print(f"\n{table_name}:")
    print(f"  Current rows: {table_impact.current_row_count}")
    print(f"  Size: {table_impact.size_mb}MB")
    print(f"  Estimated rows after: {table_impact.estimated_new_row_count}")
    print(f"  Size change: {table_impact.estimated_size_change_mb}MB")
    print(f"  Affected rows: {table_impact.affected_rows}")

# Check constraint violations
if impact.constraint_violations:
    print("\n⚠️  Constraint violations detected:")
    for violation in impact.constraint_violations:
        print(f"  {violation.constraint_type}: {violation.constraint_name}")
        print(f"    Affected rows: {violation.affected_rows}")
```

**What it means**:
- **current_row_count**: How many rows are in the table now
- **size_mb**: Current disk usage
- **estimated_new_row_count**: Projected rows after operation
- **estimated_size_change_mb**: Disk space change
- **constraint_violations**: Foreign key or check constraint issues

### Concurrency Analysis

Concurrency analysis predicts lock conflicts:

```python
concurrency = analysis.concurrency

print(f"Risk level: {concurrency.risk_level}")  # low, medium, high
print(f"Tables locked: {concurrency.tables_locked}")
print(f"Lock duration estimate: {concurrency.lock_duration_estimate_ms}ms")

# Check for blocking
if concurrency.blocking_statements:
    print("⚠️  This may block other queries:")
    for stmt in concurrency.blocking_statements:
        print(f"  - {stmt}")
```

**Risk Levels**:

| Level | Lock Type | Duration | Impact |
|-------|-----------|----------|--------|
| **LOW** | RowExclusiveLock | <50ms | Minimal impact on concurrent queries |
| **MEDIUM** | ShareUpdateExclusiveLock | 50-200ms | May delay some concurrent operations |
| **HIGH** | ExclusiveLock, AccessExclusiveLock | 200-500ms+ | Blocks other queries, use during maintenance |

**Best Practices**:
- Execute LOW risk operations anytime
- Execute MEDIUM risk during low-traffic periods
- Execute HIGH risk during scheduled maintenance windows

### Cost Analysis

Cost analysis estimates resource usage:

```python
cost = analysis.cost

print(f"Estimated time: {cost.estimated_duration_ms}ms")
print(f"Estimated disk: {cost.estimated_disk_usage_mb}MB")
print(f"Estimated CPU: {cost.estimated_cpu_percent}%")
print(f"Recommended batch size: {cost.recommended_batch_size}")
print(f"Cost score: {cost.total_cost_score}/100")
print(f"Is expensive: {cost.is_expensive}")

# Check warnings
if cost.warnings:
    print("\nCost warnings:")
    for warning in cost.warnings:
        print(f"  ⚠️  {warning}")
```

**Thresholds**:

| Metric | LOW | MEDIUM | HIGH (Expensive) |
|--------|-----|--------|------------------|
| **Time** | <5s | 5-10s | >10s |
| **Disk** | <50MB | 50-100MB | >100MB |
| **CPU** | <60% | 60-80% | >80% |

### Report Summary

Get a quick overview:

```python
print(f"Total statements: {report.statements_analyzed}")
print(f"Unsafe statements: {report.unsafe_count}")
print(f"Safe to execute: {not report.has_unsafe_statements}")
print(f"Total estimated time: {report.total_estimated_time_ms}ms")
print(f"Total estimated disk: {report.total_estimated_disk_mb}MB")

print("\nWarnings:")
for warning in report.warnings:
    print(f"  {warning}")
```

---

## Advanced Configuration

### Selective Component Analysis

Enable only the analysis you need:

```python
# Fast analysis - classification only (no impact/concurrency/cost)
dry_run_fast = DryRunMode(
    analyze_impact=False,
    analyze_concurrency=False,
    estimate_costs=False
)
# ~10-20ms per statement

# Medium analysis - skip cost estimation
dry_run_medium = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=False
)
# ~30-50ms per statement

# Full analysis - everything
dry_run_full = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)
# ~50-100ms per statement
```

### Formatted Output

Generate reports in different formats:

```python
from confiture.core.migration.dry_run.report import DryRunReportGenerator

generator = DryRunReportGenerator(use_colors=True, verbose=True)

# Plain text report (human-readable)
text_report = generator.generate_text_report(report)
print(text_report)

# JSON report (programmatic)
json_report = generator.generate_json_report(report)
import json
print(json.dumps(json_report, indent=2))

# One-line summary
summary = generator.generate_summary_line(report)
print(summary)
# Output: [✓ SAFE] 3 statements | Time: 1500ms | Disk: 5.2MB
```

### Batch Analysis

Analyze multiple statements efficiently:

```python
from confiture.core.migration.dry_run.estimator import CostEstimator

estimator = CostEstimator()

statements = [
    "ALTER TABLE users ADD COLUMN bio TEXT",
    "CREATE INDEX idx_email ON users(email)",
    "INSERT INTO logs SELECT * FROM archive_logs",
]

# Estimate costs for multiple statements
cost_estimates = await estimator.estimate_batch(statements)

# Get total cost
total_cost = estimator.get_total_cost(list(cost_estimates.values()))
print(f"Total time: {total_cost.estimated_duration_ms}ms")
print(f"Total disk: {total_cost.estimated_disk_usage_mb}MB")
print(f"Average CPU: {total_cost.estimated_cpu_percent}%")
```

---

## Real-World Examples

### Example 1: Large Table Migration

**Scenario**: Add column to users table with 1M rows

```python
# Setup
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

# Analyze
report = await dry_run.analyze(
    statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    connection=connection,
    migration_id="add_bio_column"
)

# Review results
analysis = report.analyses[0]
print(f"Classification: {analysis.classification}")
# WARNING - Schema change, will take time

print(f"Impact:")
print(f"  Affected table: users")
print(f"  Current rows: {analysis.impact.impact_by_table['users'].current_row_count}")
print(f"  Estimated time: {analysis.cost.estimated_duration_ms}ms")

print(f"Concurrency:")
print(f"  Risk: {analysis.concurrency.risk_level}")
# HIGH - Requires exclusive lock

print(f"Recommendation:")
print(f"  Execute during maintenance window (low-traffic period)")
```

### Example 2: Bulk Data Deletion

**Scenario**: Delete old records from logs table

```python
# Setup
dry_run = DryRunMode()

# Analyze
report = await dry_run.execute_and_analyze(
    statements=[
        "DELETE FROM logs WHERE created_at < NOW() - INTERVAL '1 year'"
    ],
    connection=connection
)

# Review
analysis = report.analyses[0]
print(f"Classification: {analysis.classification}")
# UNSAFE - No WHERE clause restriction? Actually has condition, so WARNING

impact = analysis.impact
print(f"Rows affected: {impact.rows_affected_estimate}")
print(f"Disk freed: {impact.estimated_size_change_mb}MB")

cost = analysis.cost
print(f"Recommended batch size: {cost.recommended_batch_size}")
# Large deletions should be batched

# Decision
if cost.is_expensive:
    print("⚠️  Large deletion - consider running in batches")
    print(f"Batch size: {cost.recommended_batch_size} rows")
```

### Example 3: Pre-Production Validation

**Scenario**: Full migration validation before deploying to production

```python
# Setup - Full analysis with execution
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

migration_statements = [
    "ALTER TABLE users ADD COLUMN last_login_ip INET",
    "CREATE INDEX idx_last_login ON users(last_login_ip)",
    "UPDATE user_settings SET theme = 'light' WHERE theme IS NULL",
]

# Analyze with actual execution
report = await dry_run.execute_and_analyze(
    statements=migration_statements,
    connection=connection,
    migration_id="pre_deploy_001"
)

# Comprehensive review
print("=" * 80)
print("MIGRATION VALIDATION REPORT")
print("=" * 80)
print(f"Total statements: {report.statements_analyzed}")
print(f"Safe to execute: {not report.has_unsafe_statements}")
print(f"Total time estimate: {report.total_estimated_time_ms}ms")
print()

for i, analysis in enumerate(report.analyses, 1):
    print(f"Statement {i}:")
    print(f"  SQL: {analysis.statement[:60]}...")
    print(f"  Classification: {analysis.classification}")
    print(f"  Actual execution time: {analysis.execution_time_ms}ms")
    if analysis.cost:
        accuracy = (analysis.execution_time_ms / analysis.cost.estimated_duration_ms * 100)
        print(f"  Estimate accuracy: {accuracy:.0f}%")
    if analysis.concurrency:
        print(f"  Concurrency risk: {analysis.concurrency.risk_level}")
    print()

# Final approval
if not report.has_unsafe_statements:
    print("✓ APPROVED FOR PRODUCTION DEPLOYMENT")
else:
    print("❌ UNSAFE STATEMENTS DETECTED - REVIEW REQUIRED")
```

---

## Troubleshooting

### Common Issues

#### "Analysis failed with: table does not exist"

**Cause**: Analyzing statements that reference non-existent tables

**Solution**:
```python
# Option 1: Create tables before analysis
# Option 2: Use analyze-only mode (faster, no table requirements)
dry_run = DryRunMode(analyze_impact=False)
report = await dry_run.analyze(statements, connection)
```

#### "Cost estimate seems inaccurate"

**Cause**: Heuristic estimates are based on statement patterns, not actual data

**Solution**:
```python
# Use execute_and_analyze for realistic metrics
report = await dry_run.execute_and_analyze(statements, connection)
# Actual execution time will be recorded
```

#### "Concurrency analysis says 'high risk' but it's blocking users"

**Cause**: HIGH risk operations require exclusive locks that block all other queries

**Solution**:
```
Execute during maintenance window:
- Scheduled off-hours
- During known low-traffic period
- With application disconnects

Example:
  Mon 2:00 AM - 3:00 AM (low traffic)
  Pause application for 5 minutes
  Run migration
  Resume application
```

---

## Best Practices

### 1. Always Analyze Before Production

```python
# Before deploying migrations to production:
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

report = await dry_run.execute_and_analyze(
    statements=migration.statements,
    connection=staging_connection
)

# Review report before approving
if report.has_unsafe_statements:
    return ApprovalResult.REJECTED
```

### 2. Choose the Right Mode

```python
# For quick checks during development
dry_run_fast = DryRunMode(
    analyze_impact=False,
    analyze_concurrency=False,
    estimate_costs=False
)

# For pre-production validation
dry_run_full = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)
```

### 3. Batch Large Operations

```python
# If batch size is recommended
cost = analysis.cost
if cost.recommended_batch_size < 100000:
    print(f"Consider batching in groups of {cost.recommended_batch_size}")
```

### 4. Schedule Based on Risk

```python
# Check concurrency risk and schedule accordingly
if analysis.concurrency.risk_level == "high":
    print("Schedule during maintenance window")
elif analysis.concurrency.risk_level == "medium":
    print("Execute during low-traffic period")
else:
    print("Safe to execute anytime")
```

### 5. Monitor Estimate vs. Actual

```python
# For execute_and_analyze, compare estimates vs. actual
actual_time = analysis.execution_time_ms
estimated_time = analysis.cost.estimated_duration_ms
accuracy = (actual_time / estimated_time * 100)

if accuracy < 50 or accuracy > 200:
    print(f"⚠️  Estimate was significantly off: {accuracy:.0f}%")
    # Review estimation logic
```

### 6. Document Migration Decisions

```python
# Save report for documentation
report_json = generator.generate_json_report(report)

import json
with open(f"migrations/reports/{migration_id}.json", "w") as f:
    json.dump(report_json, f, indent=2)

# Attach to deployment ticket with approval notes
```

---

## Integration with Wizard (Feature 3)

Dry-run mode integrates seamlessly with the interactive migration wizard:

```python
# Step 5: Execute & Verify
if user_chooses_dry_run:
    dry_run = DryRunMode(
        analyze_impact=True,
        analyze_concurrency=True,
        estimate_costs=True
    )

    # Execute with analysis
    report = await dry_run.execute_and_analyze(
        statements=migration.statements,
        connection=connection
    )

    # Show results to user
    console.print(report_generator.generate_text_report(report))

    # Ask for confirmation
    if questionary.confirm("Proceed with migration?").ask():
        # Execute for real
        await migrator.execute(migration.statements, connection)
    else:
        console.print("Migration cancelled")
```

---

## See Also

- [API Reference: DryRunMode](../reference/dry-run-api.md)
- [Cost Estimation Details](../reference/cost-estimation.md)
- [Statement Classification Rules](../reference/statement-classification.md)
- [Interactive Migration Wizard](./migration-wizard.md)

---

**Version**: 1.0
**Last Updated**: December 27, 2025
**Feature**: Feature 4 - Migration Dry-Run Mode
