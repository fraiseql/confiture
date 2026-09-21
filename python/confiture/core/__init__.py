"""Core migration execution and schema building components.

The names below resolve on first use. ``confiture.core`` is the parent of every
core module, so anything it imports eagerly is paid by *each* of them: the
dry-run executor, the hook system and the preconditions pulled psycopg into a
process that only wanted to hold a schema model (``core/schema_model.py``).
"""

from __future__ import annotations

import importlib
from typing import Any

#: Public name -> the module that defines it.
_LAZY_IMPORTS: dict[str, str] = {
    "CircuitBreaker": "confiture.core.hooks",
    "CircuitBreakerState": "confiture.core.hooks",
    "ColumnExists": "confiture.core.preconditions",
    "ColumnNotExists": "confiture.core.preconditions",
    "ColumnType": "confiture.core.preconditions",
    "ConstraintExists": "confiture.core.preconditions",
    "ConstraintNotExists": "confiture.core.preconditions",
    "CustomSQL": "confiture.core.preconditions",
    "DryRunError": "confiture.core.dry_run",
    "DryRunExecutor": "confiture.core.dry_run",
    "DryRunResult": "confiture.core.dry_run",
    "ExecutionDAG": "confiture.core.hooks",
    "ForeignKeyExists": "confiture.core.preconditions",
    "Hook": "confiture.core.hooks",
    "HookContext": "confiture.core.hooks",
    "HookErrorStrategy": "confiture.core.hooks",
    "HookExecutionEvent": "confiture.core.hooks",
    "HookExecutionResult": "confiture.core.hooks",
    "HookExecutionStatus": "confiture.core.hooks",
    "HookExecutionStrategy": "confiture.core.hooks",
    "HookExecutionTracer": "confiture.core.hooks",
    "HookPhase": "confiture.core.hooks",
    "HookRegistry": "confiture.core.hooks",
    "HookResult": "confiture.core.hooks",
    "IndexExists": "confiture.core.preconditions",
    "IndexNotExists": "confiture.core.preconditions",
    "PerformanceTrace": "confiture.core.hooks",
    "Precondition": "confiture.core.preconditions",
    "PreconditionError": "confiture.core.preconditions",
    "PreconditionValidationError": "confiture.core.preconditions",
    "PreconditionValidator": "confiture.core.preconditions",
    "RetryConfig": "confiture.core.hooks",
    "RowCountEquals": "confiture.core.preconditions",
    "RowCountGreaterThan": "confiture.core.preconditions",
    "SchemaExists": "confiture.core.preconditions",
    "SchemaNotExists": "confiture.core.preconditions",
    "TableExists": "confiture.core.preconditions",
    "TableIsEmpty": "confiture.core.preconditions",
    "TableNotExists": "confiture.core.preconditions",
}

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


def __getattr__(name: str) -> Any:
    """Resolve a public name from the module that defines it, on first use."""
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
