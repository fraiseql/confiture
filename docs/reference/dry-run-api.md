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
    """Executes migration SQL in dry-run mode for testing.

    Features:
    - SAVEPOINT-based execution with automatic rollback (nothing persisted)
    - Per-statement metrics (execution time, rows affected)
    - A confidence percentage for the run
    """
```

#### Constructor

```python
def __init__(self, conn: psycopg.Connection | None = None) -> None:
    """Initialize the executor, optionally binding a connection."""
```

#### Method: run

```python
def run(
    self,
    *,
    migration_name: str | None = None,
    statements: list[str] | None = None,
) -> DryRunResult:
    """Execute SQL statements in dry-run mode.

    Each statement runs inside a SAVEPOINT that is rolled back, so nothing is
    persisted. Returns per-statement results plus an overall verdict.

    Args:
        migration_name: Label for the migration under test.
        statements: SQL statements to execute (and roll back).

    Returns:
        DryRunResult with per-statement metrics.

    Raises:
        DryRunError: If execution fails irrecoverably.
    """
```

**Returns**: `DryRunResult` — per-statement metrics and an overall verdict.

**Safety**: every statement runs in a SAVEPOINT and is rolled back — nothing is persisted to disk.

**Example**:
```python
import psycopg
from confiture.core.dry_run import DryRunExecutor

with psycopg.connect("postgresql://localhost/mydb") as conn:
    executor = DryRunExecutor(conn)
    result = executor.run(
        migration_name="20260403120000_add_users",
        statements=["ALTER TABLE users ADD COLUMN email VARCHAR(255)"],
    )

    if result.success:
        print(
            f"{result.migration_name} ok in {result.total_time_ms} ms "
            f"(confidence {result.confidence_pct}%)"
        )
        for stmt in result.statements:
            print(f"  {stmt.rows_affected} rows in {stmt.execution_time_ms} ms")
    else:
        print(f"failed: {result.error}")
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
    success: bool
    total_time_ms: int = 0
    confidence_pct: int = 0
    statements: list[StatementResult] = field(default_factory=list)
    error: str | None = None
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `migration_name` | str | Name of the migration under test |
| `success` | bool | Whether every statement succeeded |
| `total_time_ms` | int | Total execution time across statements (ms) |
| `confidence_pct` | int | Confidence in the estimate (SAVEPOINT replay ≈ 80–90) |
| `statements` | list[StatementResult] | Per-statement results (see below) |
| `error` | str \| None | Error message if the run failed |

### Dataclass: StatementResult

```python
@dataclass
class StatementResult:
    """Result of a single statement within a dry run."""

    sql: str
    success: bool
    execution_time_ms: int = 0
    rows_affected: int = 0
    error: str | None = None
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `sql` | str | The statement that was executed |
| `success` | bool | Whether the statement succeeded |
| `execution_time_ms` | int | Statement execution time (ms) |
| `rows_affected` | int | Rows affected by the statement |
| `error` | str \| None | Error message if the statement failed |

---

## DryRunError

Error raised when dry-run execution fails.

**Module**: `confiture.core.dry_run`

### Class: DryRunError

```python
class DryRunError(ConfiturError):
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
from confiture.core.dry_run import DryRunExecutor, DryRunError

with psycopg.connect("postgresql://localhost/mydb") as conn:
    executor = DryRunExecutor(conn)

    try:
        result = executor.run(
            migration_name="20260403120000_add_users",
            statements=["ALTER TABLE users ADD COLUMN email VARCHAR(255)"],
        )

        if result.success:
            print(f"✓ {result.migration_name} passed in {result.total_time_ms} ms")
            for stmt in result.statements:
                print(f"  {stmt.rows_affected} rows in {stmt.execution_time_ms} ms")
        else:
            print(f"✗ {result.migration_name} failed: {result.error}")

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

**Note**: This reference reflects the SAVEPOINT-based dry-run implementation in
`confiture.core.dry_run`.
