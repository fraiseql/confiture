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
]
