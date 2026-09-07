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
    "CircuitBreaker",
    "CircuitBreakerState",
    # Preconditions - Column checks
    "ColumnExists",
    "ColumnNotExists",
    "ColumnType",
    # Preconditions - Constraint checks
    "ConstraintExists",
    "ConstraintNotExists",
    # Preconditions - Custom SQL
    "CustomSQL",
    # Dry-run mode
    "DryRunError",
    "DryRunExecutor",
    "DryRunResult",
    "ExecutionDAG",
    "ForeignKeyExists",
    # Hook system - Base
    "Hook",
    "HookContext",
    "HookErrorStrategy",
    "HookExecutionEvent",
    "HookExecutionResult",
    # Hook system - Observability
    "HookExecutionStatus",
    # Hook system - Execution strategies
    "HookExecutionStrategy",
    "HookExecutionTracer",
    "HookPhase",
    "HookRegistry",
    "HookResult",
    # Preconditions - Index checks
    "IndexExists",
    "IndexNotExists",
    "PerformanceTrace",
    # Preconditions - Base
    "Precondition",
    "PreconditionError",
    "PreconditionValidationError",
    "PreconditionValidator",
    "RetryConfig",
    # Preconditions - Row count checks
    "RowCountEquals",
    "RowCountGreaterThan",
    # Preconditions - Schema checks
    "SchemaExists",
    "SchemaNotExists",
    # Preconditions - Table checks
    "TableExists",
    "TableIsEmpty",
    "TableNotExists",
]
