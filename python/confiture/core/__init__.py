"""Core migration execution and schema building components."""

from confiture.core.dry_run import (
    DryRunError,
    DryRunExecutor,
    DryRunResult,
)
from confiture.core.hooks import (
    CircuitBreaker,
    CircuitBreakerState,
    ExecutionDAG,
    Hook,
    HookContext,
    HookErrorStrategy,
    HookExecutionEvent,
    HookExecutionResult,
    HookExecutionStatus,
    HookExecutionStrategy,
    HookExecutionTracer,
    HookPhase,
    HookRegistry,
    HookResult,
    PerformanceTrace,
    RetryConfig,
)
from confiture.core.preconditions import (
    ColumnExists,
    ColumnNotExists,
    ColumnType,
    ConstraintExists,
    ConstraintNotExists,
    CustomSQL,
    ForeignKeyExists,
    IndexExists,
    IndexNotExists,
    Precondition,
    PreconditionError,
    PreconditionValidationError,
    PreconditionValidator,
    RowCountEquals,
    RowCountGreaterThan,
    SchemaExists,
    SchemaNotExists,
    TableExists,
    TableIsEmpty,
    TableNotExists,
)

__all__ = [
    # Dry-run mode
    "DryRunError",
    "DryRunExecutor",
    "DryRunResult",
    # Hook system - Base
    "Hook",
    "HookContext",
    "HookResult",
    "HookPhase",
    "HookRegistry",
    # Hook system - Execution strategies
    "HookExecutionStrategy",
    "HookErrorStrategy",
    "RetryConfig",
    # Hook system - Observability
    "HookExecutionStatus",
    "HookExecutionEvent",
    "HookExecutionResult",
    "CircuitBreaker",
    "CircuitBreakerState",
    "HookExecutionTracer",
    "ExecutionDAG",
    "PerformanceTrace",
    # Preconditions - Base
    "Precondition",
    "PreconditionValidator",
    "PreconditionError",
    "PreconditionValidationError",
    # Preconditions - Table checks
    "TableExists",
    "TableNotExists",
    "TableIsEmpty",
    # Preconditions - Column checks
    "ColumnExists",
    "ColumnNotExists",
    "ColumnType",
    # Preconditions - Constraint checks
    "ConstraintExists",
    "ConstraintNotExists",
    "ForeignKeyExists",
    # Preconditions - Index checks
    "IndexExists",
    "IndexNotExists",
    # Preconditions - Schema checks
    "SchemaExists",
    "SchemaNotExists",
    # Preconditions - Row count checks
    "RowCountEquals",
    "RowCountGreaterThan",
    # Preconditions - Custom SQL
    "CustomSQL",
]
