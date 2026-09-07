"""Enhanced Hook System.

Provides:
- Explicit hook execution semantics (sequential, parallel, DAG-based)
- Type-safe hook contexts with phase-specific data
- Three-category event system (Lifecycle, State, Alert)
- Full observability infrastructure (tracing, circuit breakers)
"""

from __future__ import annotations

from .base import Hook, HookError, HookExecutor, HookResult
from .context import (
    ExecutionContext,
    HookContext,
    MigrationPlanContext,
    MigrationStep,
    RiskAssessment,
    RollbackContext,
    Schema,
    SchemaAnalysisContext,
    SchemaDiffContext,
    SchemaDifference,
    ValidationContext,
)
from .execution_strategies import (
    HookContextMutationPolicy,
    HookErrorStrategy,
    HookExecutionStrategy,
    HookPhaseConfig,
    RetryConfig,
)
from .observability import (
    CircuitBreaker,
    CircuitBreakerState,
    ExecutionDAG,
    HookExecutionError,
    HookExecutionEvent,
    HookExecutionResult,
    HookExecutionStatus,
    HookExecutionTracer,
    PerformanceTrace,
)
from .phases import HookAlert, HookEvent, HookPhase
from .registry import HookRegistry

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerState",
    "ExecutionContext",
    "ExecutionDAG",
    # Base classes
    "Hook",
    "HookAlert",
    "HookContext",
    "HookContextMutationPolicy",
    "HookError",
    "HookErrorStrategy",
    "HookEvent",
    "HookExecutionError",
    "HookExecutionEvent",
    "HookExecutionResult",
    # Observability
    "HookExecutionStatus",
    # Execution strategies
    "HookExecutionStrategy",
    "HookExecutionTracer",
    "HookExecutor",
    # Phases/Events/Alerts
    "HookPhase",
    "HookPhaseConfig",
    # Registry
    "HookRegistry",
    "HookResult",
    "MigrationPlanContext",
    "MigrationStep",
    "PerformanceTrace",
    "RetryConfig",
    "RiskAssessment",
    "RollbackContext",
    "Schema",
    # Contexts
    "SchemaAnalysisContext",
    "SchemaDiffContext",
    "SchemaDifference",
    "ValidationContext",
]
