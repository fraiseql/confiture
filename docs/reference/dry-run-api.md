# Dry-Run Mode API Reference

**Feature: Migration Dry-Run Execution**

Complete API reference for dry-run mode components.

---

## Table of Contents

1. [DryRunExecutor](#dryrunexecutor)
2. [DryRunResult](#dryrunresult)
3. [DryRunError](#dryrunerror)
4. [CLI Helpers](#cli-helpers)
5. [Examples](#examples)

---

## DryRunExecutor

Executes migrations in dry-run mode for testing.

**Module**: `confiture.core.dry_run`

### Class: DryRunExecutor

```python
class DryRunExecutor:
    """Executes migrations in dry-run mode for testing.

    Features:
    - Transaction-based execution with automatic rollback
    - Capture of execution metrics (time, rows affected, locks)
    - Estimation of production execution time
    - Detection of constraint violations
    - Confidence level for estimates
    - Structured logging for observability
    """
```

#### Constructor

```python
def __init__(self) -> None:
    """Initialize dry-run executor."""
```

#### Method: run

```python
def run(
    self,
    conn: psycopg.Connection,
    migration,
) -> DryRunResult:
    """Execute migration in dry-run mode.

    Executes the migration within a transaction that is automatically
    rolled back, allowing testing without permanent changes.

    Args:
        conn: Database connection
        migration: Migration instance with up() method

    Returns:
        DryRunResult with execution metrics

    Raises:
        DryRunError: If migration execution fails
    """
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conn` | psycopg.Connection | Yes | PostgreSQL connection |
| `migration` | Migration | Yes | Migration instance with up() method |

**Returns**: `DryRunResult` - Execution metrics and results

**Safety**: Guaranteed rollback - no data modified on disk

**Example**:
```python
from confiture.core.dry_run import DryRunExecutor, DryRunResult

executor = DryRunExecutor()

# Execute migration in dry-run mode
result = executor.run(conn, migration)

if result.success:
    print(f"Migration {result.migration_name} succeeded")
    print(f"Execution time: {result.execution_time_ms}ms")
    print(f"Rows affected: {result.rows_affected}")
else:
    print(f"Migration failed with warnings: {result.warnings}")
```

---

## DryRunResult

Result of a dry-run execution.

**Module**: `confiture.core.dry_run`

### Dataclass: DryRunResult

```python
@dataclass
class DryRunResult:
    """Result of a dry-run execution."""

    migration_name: str
    migration_version: str
    success: bool
    execution_time_ms: int = 0
    rows_affected: int = 0
    locked_tables: list[str] = field(default_factory=list)
    estimated_production_time_ms: int = 0
    confidence_percent: int = 0
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `migration_name` | str | Name of the migration |
| `migration_version` | str | Version of the migration |
| `success` | bool | Whether execution succeeded |
| `execution_time_ms` | int | Actual execution time in milliseconds |
| `rows_affected` | int | Number of rows affected |
| `locked_tables` | list[str] | Tables that were locked |
| `estimated_production_time_ms` | int | Estimated production time |
| `confidence_percent` | int | Confidence in the estimate (0-100) |
| `warnings` | list[str] | List of warnings encountered |
| `stats` | dict[str, Any] | Additional statistics |

---

## DryRunError

Error raised when dry-run execution fails.

**Module**: `confiture.core.dry_run`

### Class: DryRunError

```python
class DryRunError(MigrationError):
    """Error raised when dry-run execution fails."""

    def __init__(self, migration_name: str, error: Exception):
        """Initialize dry-run error.

        Args:
            migration_name: Name of migration that failed
            error: Original exception
        """
```

**Attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `migration_name` | str | Name of the failed migration |
| `original_error` | Exception | The underlying exception |

---

## CLI Helpers

Helper functions for dry-run CLI integration.

**Module**: `confiture.cli.dry_run`

### Function: save_text_report

```python
def save_text_report(report_text: str, filepath: Path) -> None:
    """Save text report to file.

    Args:
        report_text: Formatted text report
        filepath: Path to save report to

    Raises:
        IOError: If file write fails
    """
```

### Function: save_json_report

```python
def save_json_report(report_data: dict, filepath: Path) -> None:
    """Save JSON report to file.

    Args:
        report_data: Report dictionary to save
        filepath: Path to save report to

    Raises:
        IOError: If file write fails
    """
```

### Function: print_json_report

```python
def print_json_report(report_data: dict) -> None:
    """Print JSON report to console.

    Args:
        report_data: Report dictionary to print
    """
```

### Function: show_report_summary

```python
def show_report_summary(report: Any) -> None:
    """Show a brief summary of the report status.

    Args:
        report: Report object with has_unsafe_statements, unsafe_count,
                total_estimated_time_ms, and total_estimated_disk_mb attributes
    """
```

### Function: ask_dry_run_execute_confirmation

```python
def ask_dry_run_execute_confirmation() -> bool:
    """Ask user to confirm real execution after dry-run-execute test.

    Returns:
        True if user confirms, False otherwise
    """
```

### Function: display_dry_run_header

```python
def display_dry_run_header(mode: str) -> None:
    """Display header for dry-run analysis.

    Args:
        mode: Either "analysis" for --dry-run or "testing" for --dry-run-execute
    """
```

---

## Examples

### Basic Dry-Run Execution

```python
import psycopg
from confiture.core.dry_run import DryRunExecutor, DryRunResult, DryRunError

# Connect to database
conn = psycopg.connect("postgresql://localhost/mydb")

# Create executor
executor = DryRunExecutor()

# Execute migration in dry-run mode
try:
    result = executor.run(conn, migration)

    if result.success:
        print(f"✓ Migration {result.migration_name} passed")
        print(f"  Execution time: {result.execution_time_ms}ms")
        print(f"  Rows affected: {result.rows_affected}")
        print(f"  Locked tables: {', '.join(result.locked_tables)}")

        if result.warnings:
            print("  Warnings:")
            for warning in result.warnings:
                print(f"    - {warning}")
    else:
        print(f"✗ Migration {result.migration_name} failed")

except DryRunError as e:
    print(f"Dry-run failed: {e}")
    print(f"Original error: {e.original_error}")
```

### CLI Integration

```python
from pathlib import Path
from confiture.cli.dry_run import (
    save_text_report,
    save_json_report,
    display_dry_run_header,
    ask_dry_run_execute_confirmation,
)

# Display header
display_dry_run_header("testing")

# Run dry-run...
# result = executor.run(conn, migration)

# Save reports
save_text_report("Migration analysis results...", Path("reports/analysis.txt"))
save_json_report({"success": True, "time_ms": 250}, Path("reports/analysis.json"))

# Ask for confirmation before real execution
if ask_dry_run_execute_confirmation():
    print("Proceeding with real execution...")
else:
    print("Execution cancelled")
```

---

**Version**: 2.0
**Last Updated**: January 2026
**Note**: This API reference reflects the current simplified dry-run implementation.
