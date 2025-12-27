# Dry-Run Mode API Reference

**Feature 4: Migration Dry-Run Analysis**

Complete API reference for dry-run mode components.

---

## Table of Contents

1. [DryRunMode](#dryrunmode)
2. [DryRunReportGenerator](#dryrunreportgenerator)
3. [CostEstimator](#costestimator)
4. [Impact Analysis](#impact-analysis)
5. [Concurrency Analysis](#concurrency-analysis)
6. [Data Models](#data-models)
7. [Examples](#examples)

---

## DryRunMode

Main orchestrator for dry-run analysis.

**Module**: `confiture.core.migration.dry_run.dry_run_mode`

### Class: DryRunMode

```python
class DryRunMode:
    """Orchestrate complete dry-run migration analysis."""
```

#### Constructor

```python
def __init__(
    self,
    analyze_impact: bool = True,
    analyze_concurrency: bool = True,
    estimate_costs: bool = True,
) -> None:
    """Initialize dry-run mode.

    Args:
        analyze_impact: Whether to analyze table impacts (default: True)
        analyze_concurrency: Whether to analyze concurrency/locks (default: True)
        estimate_costs: Whether to estimate execution costs (default: True)
    """
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `analyze_impact` | bool | True | Enable table impact analysis |
| `analyze_concurrency` | bool | True | Enable concurrency risk analysis |
| `estimate_costs` | bool | True | Enable cost estimation |

**Example**:
```python
# Full analysis
dry_run = DryRunMode()

# Fast analysis (classification only)
dry_run = DryRunMode(
    analyze_impact=False,
    analyze_concurrency=False,
    estimate_costs=False
)
```

#### Method: analyze

```python
async def analyze(
    self,
    statements: list[str],
    connection: AsyncConnection,
    migration_id: str | None = None,
) -> DryRunReport:
    """Perform complete dry-run analysis without executing.

    Analyzes statements using metadata queries only. No statements are
    executed on the database.

    Args:
        statements: List of SQL statements to analyze
        connection: AsyncConnection for metadata queries
        migration_id: Optional migration identifier for tracking

    Returns:
        DryRunReport with complete analysis results

    Raises:
        Exception: If analysis fails (caught and recorded in report)
    """
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `statements` | list[str] | Yes | SQL statements to analyze |
| `connection` | AsyncConnection | Yes | PostgreSQL async connection |
| `migration_id` | str \| None | No | Migration identifier for tracking |

**Returns**: `DryRunReport` - Complete analysis report

**Performance**: 50-100ms per statement (depending on components enabled)

**Example**:
```python
dry_run = DryRunMode()
report = await dry_run.analyze(
    statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    connection=connection,
    migration_id="001_add_bio"
)
```

#### Method: execute_and_analyze

```python
async def execute_and_analyze(
    self,
    statements: list[str],
    connection: AsyncConnection,
    migration_id: str | None = None,
) -> DryRunReport:
    """Execute statements in dry-run and collect analysis.

    Executes statements in rolled-back SAVEPOINT transaction while
    collecting comprehensive analysis data. Guaranteed rollback - no
    data is modified on disk.

    Args:
        statements: List of SQL statements to execute
        connection: AsyncConnection for execution
        migration_id: Optional migration identifier for tracking

    Returns:
        DryRunReport with execution results and analysis

    Raises:
        Exception: If execution fails (caught and recorded in report)
    """
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `statements` | list[str] | Yes | SQL statements to execute |
| `connection` | AsyncConnection | Yes | PostgreSQL async connection |
| `migration_id` | str \| None | No | Migration identifier for tracking |

**Returns**: `DryRunReport` - Report with actual execution metrics

**Performance**: 100-1000ms per statement

**Safety**: Guaranteed rollback via SAVEPOINT - no data modified

**Example**:
```python
dry_run = DryRunMode()
report = await dry_run.execute_and_analyze(
    statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    connection=connection,
    migration_id="001_add_bio"
)

# Access actual execution time
for analysis in report.analyses:
    print(f"Actual time: {analysis.execution_time_ms}ms")
```

---

## DryRunReportGenerator

Formats analysis results for human consumption.

**Module**: `confiture.core.migration.dry_run.report`

### Class: DryRunReportGenerator

```python
class DryRunReportGenerator:
    """Generate formatted reports from dry-run analysis."""
```

#### Constructor

```python
def __init__(
    self,
    use_colors: bool = True,
    verbose: bool = False,
) -> None:
    """Initialize report generator.

    Args:
        use_colors: Whether to use ANSI color codes (default: True)
        verbose: Whether to include detailed information (default: False)
    """
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_colors` | bool | True | Use ANSI colors in output |
| `verbose` | bool | False | Include detailed statement information |

#### Method: generate_text_report

```python
def generate_text_report(self, report: DryRunReport) -> str:
    """Generate plain text report.

    Generates human-readable report with sections:
    - SUMMARY: Analysis overview and metrics
    - WARNINGS: Aggregated warnings
    - STATEMENT DETAILS: Per-statement analysis (verbose only)
    - RECOMMENDATIONS: Suggested actions

    Args:
        report: DryRunReport to format

    Returns:
        Formatted text report as string
    """
```

**Returns**: `str` - Formatted text report

**Output Sections**:
1. SUMMARY - Overview with key metrics
2. WARNINGS - Aggregated warning list
3. STATEMENT DETAILS - Per-statement analysis (if verbose=True)
4. RECOMMENDATIONS - Actions based on findings

**Example**:
```python
generator = DryRunReportGenerator(use_colors=True, verbose=True)
text = generator.generate_text_report(report)
print(text)

# Output:
# ================================================================================
# DRY-RUN MIGRATION ANALYSIS REPORT
# ================================================================================
#
# SUMMARY
# ────────────────────────────────────────────────────────────────────────────
# Statements analyzed: 3
# Analysis duration: 256ms
#
# Safety Analysis:
#   Unsafe statements: 1 ⚠️  REQUIRES ATTENTION
#
# Cost Estimates:
#   Total time: 1500ms
#   Total disk: 5.2MB
#
# Concurrency Risk:
#   High risk: 1 statement(s) ⚠️
#
# WARNINGS
# ────────────────────────────────────────────────────────────────────────────
#   ⚠️  1 unsafe statement(s) detected
#   ⚠️  1 statement(s) with HIGH concurrency risk
#   ...
```

#### Method: generate_json_report

```python
def generate_json_report(self, report: DryRunReport) -> dict[str, Any]:
    """Generate JSON-serializable report.

    Generates structured report suitable for programmatic processing.

    Args:
        report: DryRunReport to convert

    Returns:
        Dictionary with report data
    """
```

**Returns**: `dict[str, Any]` - JSON-serializable report

**Structure**:
```json
{
  "migration_id": "001_add_bio",
  "started_at": "2025-12-27T10:30:00",
  "completed_at": "2025-12-27T10:30:01",
  "total_execution_time_ms": 1000,
  "statements_analyzed": 3,
  "summary": {
    "unsafe_count": 1,
    "total_estimated_time_ms": 1500,
    "total_estimated_disk_mb": 5.2,
    "has_unsafe_statements": true
  },
  "warnings": ["⚠️  1 unsafe statement(s) detected", ...],
  "analyses": [
    {
      "statement": "ALTER TABLE users ADD COLUMN bio TEXT",
      "classification": "warning",
      "execution_time_ms": 250.5,
      "success": true,
      "error_message": null,
      "impact": { ... },
      "concurrency": { ... },
      "cost": { ... }
    },
    ...
  ]
}
```

**Example**:
```python
import json
generator = DryRunReportGenerator()
json_data = generator.generate_json_report(report)
print(json.dumps(json_data, indent=2))
```

#### Method: generate_summary_line

```python
def generate_summary_line(self, report: DryRunReport) -> str:
    """Generate single-line summary for quick viewing.

    Args:
        report: DryRunReport to summarize

    Returns:
        Single line summary
    """
```

**Returns**: `str` - One-line summary

**Format**:
```
[STATUS] N statements | Time: Xms | Disk: Y.ZMB
```

**Example**:
```python
summary = generator.generate_summary_line(report)
print(summary)
# Output: [✓ SAFE] 3 statements | Time: 1500ms | Disk: 5.2MB
```

#### Method: _get_classification_icon

```python
@staticmethod
def _get_classification_icon(classification: StatementClassification) -> str:
    """Get icon for statement classification.

    Args:
        classification: StatementClassification

    Returns:
        Icon string
    """
```

**Returns**:
- `✓` for SAFE
- `⚠️` for WARNING
- `❌` for UNSAFE

---

## CostEstimator

Estimates execution cost (time, disk, CPU).

**Module**: `confiture.core.migration.dry_run.estimator`

### Class: CostEstimator

```python
class CostEstimator:
    """Estimate execution cost for SQL statements."""
```

#### Method: estimate

```python
async def estimate(
    self,
    statement: str,
    impact: ImpactAnalysis | None = None,
) -> CostEstimate:
    """Estimate execution cost of a statement.

    Estimates time, disk, and CPU usage. Uses ImpactAnalysis if provided
    for refinement, otherwise uses heuristic estimates from statement.

    Args:
        statement: SQL statement to estimate
        impact: Optional ImpactAnalysis for detailed estimates

    Returns:
        CostEstimate with time/disk/CPU predictions
    """
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `statement` | str | Yes | SQL statement to analyze |
| `impact` | ImpactAnalysis \| None | No | Impact analysis for refinement |

**Returns**: `CostEstimate` - Cost prediction

**Example**:
```python
estimator = CostEstimator()

# Estimate from statement alone
cost = await estimator.estimate("ALTER TABLE users ADD COLUMN bio TEXT")
print(f"Time: {cost.estimated_duration_ms}ms")
print(f"Disk: {cost.estimated_disk_usage_mb}MB")
print(f"CPU: {cost.estimated_cpu_percent}%")

# Estimate with impact analysis (more accurate)
impact = await impact_analyzer.analyze(statement, connection)
cost = await estimator.estimate(statement, impact)
```

#### Method: estimate_batch

```python
async def estimate_batch(
    self,
    statements: list[str],
    impacts: dict[str, ImpactAnalysis] | None = None,
) -> dict[str, CostEstimate]:
    """Estimate cost for multiple statements.

    Args:
        statements: List of SQL statements
        impacts: Optional dict of impact analyses by statement

    Returns:
        Dictionary mapping statement to CostEstimate
    """
```

**Returns**: `dict[str, CostEstimate]` - Cost by statement

**Example**:
```python
statements = [
    "ALTER TABLE users ADD COLUMN bio TEXT",
    "CREATE INDEX idx_bio ON users(bio)",
]

estimates = await estimator.estimate_batch(statements)
for stmt, cost in estimates.items():
    print(f"{stmt}: {cost.estimated_duration_ms}ms")
```

#### Method: get_total_cost

```python
def get_total_cost(self, estimates: list[CostEstimate]) -> CostEstimate:
    """Aggregate cost estimates for multiple statements.

    Args:
        estimates: List of CostEstimate objects

    Returns:
        Combined CostEstimate
    """
```

**Returns**: `CostEstimate` - Aggregated cost

**Example**:
```python
total = estimator.get_total_cost(list(estimates.values()))
print(f"Total time: {total.estimated_duration_ms}ms")
print(f"Total disk: {total.estimated_disk_usage_mb}MB")
```

---

## Impact Analysis

Analyzes table impacts and constraints.

**Module**: `confiture.core.migration.dry_run.impact`

### Class: ImpactAnalyzer

```python
class ImpactAnalyzer:
    """Analyze table impacts of SQL statements."""
```

#### Method: analyze

```python
async def analyze(
    self,
    statement: str,
    connection: AsyncConnection,
) -> ImpactAnalysis:
    """Analyze the impact of a single SQL statement.

    Identifies affected tables, row counts, size estimates, and
    constraint violations.

    Args:
        statement: SQL statement to analyze
        connection: AsyncConnection for metadata queries

    Returns:
        ImpactAnalysis with detailed impact information
    """
```

**Returns**: `ImpactAnalysis` - Impact details

**Performance**: 10-50ms per statement

---

## Concurrency Analysis

Analyzes lock conflicts and blocking.

**Module**: `confiture.core.migration.dry_run.concurrency`

### Class: ConcurrencyAnalyzer

```python
class ConcurrencyAnalyzer:
    """Analyze concurrency impacts of SQL statements."""
```

#### Method: analyze

```python
async def analyze(
    self,
    statement: str,
    connection: AsyncConnection,
) -> ConcurrencyAnalysis:
    """Analyze concurrency impacts of a statement.

    Detects explicit and implicit locks, predicts blocking behavior,
    and classifies risk level.

    Args:
        statement: SQL statement to analyze
        connection: AsyncConnection for lock queries

    Returns:
        ConcurrencyAnalysis with lock and risk information
    """
```

**Returns**: `ConcurrencyAnalysis` - Concurrency details

**Performance**: <5ms per statement

---

## Data Models

### DryRunReport

Complete analysis report.

```python
@dataclass
class DryRunReport:
    """Complete report from dry-run analysis."""

    migration_id: str | None        # Migration identifier
    started_at: datetime | None     # Analysis start time
    completed_at: datetime | None   # Analysis end time
    total_execution_time_ms: float  # Total analysis duration
    statements_analyzed: int        # Number of statements
    analyses: list[DryRunAnalysis]  # Individual analyses
    warnings: list[str]             # Aggregated warnings
```

**Properties**:

| Property | Type | Description |
|----------|------|-------------|
| `has_unsafe_statements` | bool | True if any statement is UNSAFE |
| `unsafe_count` | int | Number of UNSAFE statements |
| `total_estimated_time_ms` | int | Sum of time estimates |
| `total_estimated_disk_mb` | float | Sum of disk estimates |

**Methods**:

```python
def add_analysis(self, analysis: DryRunAnalysis) -> None:
    """Add an analysis to the report."""
```

### DryRunAnalysis

Individual statement analysis.

```python
@dataclass
class DryRunAnalysis:
    """Complete analysis of a dry-run migration."""

    statement: str                              # SQL statement
    classification: StatementClassification    # SAFE/WARNING/UNSAFE
    impact: ImpactAnalysis | None = None       # Table impacts
    concurrency: ConcurrencyAnalysis | None = None  # Locks/blocking
    cost: CostEstimate | None = None           # Cost prediction
    execution_time_ms: float = 0.0             # Actual execution time
    success: bool = False                      # Execution success
    error_message: str | None = None           # Error details
```

### CostEstimate

Cost prediction for a statement.

```python
@dataclass
class CostEstimate:
    """Estimate of execution cost."""

    statement: str                          # SQL statement
    estimated_duration_ms: int              # Predicted time (ms)
    estimated_disk_usage_mb: float          # Predicted disk (MB)
    estimated_cpu_percent: float            # Predicted CPU (%)
    recommended_batch_size: int             # Suggested batch size
    warnings: list[str] = field(...)        # Cost-based warnings
```

**Properties**:

| Property | Type | Description |
|----------|------|-------------|
| `is_expensive` | bool | True if exceeds thresholds (>5s, >100MB, >80%) |
| `total_cost_score` | float | Overall cost score (0-100) |

**Thresholds**:
- **Time**: >5000ms = MEDIUM, >10000ms = HIGH
- **Disk**: >50MB = MEDIUM, >100MB = HIGH
- **CPU**: >60% = MEDIUM, >80% = HIGH

### ImpactAnalysis

Table impact analysis.

```python
@dataclass
class ImpactAnalysis:
    """Analysis of statement impact on tables."""

    statement: str                                  # SQL statement
    affected_tables: list[str]                      # Tables affected
    impact_by_table: dict[str, TableImpact]        # Per-table impact
    constraint_violations: list[ConstraintViolation]  # Constraint issues
    estimated_size_change_mb: float                # Disk change estimate
    execution_time_estimate_ms: int                # Time estimate
    rows_affected_estimate: int                    # Rows affected estimate
```

### ConcurrencyAnalysis

Concurrency risk analysis.

```python
@dataclass
class ConcurrencyAnalysis:
    """Analysis of concurrency impacts."""

    statement: str                          # SQL statement
    explicit_locks: list[LockInfo]         # LOCK statements
    implicit_locks: list[LockInfo]         # Operation locks
    blocking_statements: list[str]         # Potentially blocking statements
    tables_locked: list[str]               # Tables that will be locked
    lock_duration_estimate_ms: int         # Lock duration estimate
    has_concurrent_risk: bool              # Risk detected
    risk_level: str                        # "low", "medium", "high"
```

**Risk Levels**:
- **LOW**: RowExclusiveLock - minimal impact
- **MEDIUM**: ShareUpdateExclusiveLock - delays some operations
- **HIGH**: ExclusiveLock, AccessExclusiveLock - blocks all queries

---

## Examples

### Complete Analysis Workflow

```python
from confiture.core.migration.dry_run.dry_run_mode import DryRunMode
from confiture.core.migration.dry_run.report import DryRunReportGenerator

# Setup
dry_run = DryRunMode(
    analyze_impact=True,
    analyze_concurrency=True,
    estimate_costs=True
)

generator = DryRunReportGenerator(use_colors=True, verbose=True)

# Analyze
statements = [
    "ALTER TABLE users ADD COLUMN bio TEXT",
    "CREATE INDEX idx_email ON users(email)",
]

report = await dry_run.execute_and_analyze(
    statements=statements,
    connection=connection,
    migration_id="001_update_users"
)

# Display results
print(generator.generate_text_report(report))

# Save JSON
import json
json_report = generator.generate_json_report(report)
with open("migration_001.json", "w") as f:
    json.dump(json_report, f, indent=2)
```

### Cost Estimation

```python
from confiture.core.migration.dry_run.estimator import CostEstimator

estimator = CostEstimator()

# Estimate time, disk, CPU
cost = await estimator.estimate("ALTER TABLE users ADD COLUMN bio TEXT")

print(f"Time: {cost.estimated_duration_ms}ms")
print(f"Disk: {cost.estimated_disk_usage_mb}MB")
print(f"CPU: {cost.estimated_cpu_percent}%")
print(f"Expensive: {cost.is_expensive}")
print(f"Batch size: {cost.recommended_batch_size}")

if cost.warnings:
    print("Warnings:")
    for warning in cost.warnings:
        print(f"  {warning}")
```

### Programmatic Approval

```python
# Automated approval logic
if report.has_unsafe_statements:
    print("❌ UNSAFE - Manual review required")
    return ApprovalStatus.REJECTED

if report.total_estimated_time_ms > 60000:  # >1 minute
    print("⚠️  SLOW - Schedule during maintenance")
    return ApprovalStatus.PENDING_APPROVAL

high_concurrency_risk = any(
    a.concurrency.risk_level == "high"
    for a in report.analyses
    if a.concurrency
)

if high_concurrency_risk:
    print("⚠️  HIGH CONCURRENCY RISK - Schedule during maintenance")
    return ApprovalStatus.PENDING_APPROVAL

print("✓ APPROVED - Safe to execute")
return ApprovalStatus.APPROVED
```

---

**Version**: 1.0
**Last Updated**: December 27, 2025
**Feature**: Feature 4 - Migration Dry-Run Mode
