"""Phase 6 Enhanced Hook System.

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
    # Base classes
    "Hook",
    "HookResult",
    "HookError",
    "HookExecutor",
    "HookContext",
    # Phases/Events/Alerts
    "HookPhase",
    "HookEvent",
    "HookAlert",
    # Contexts
    "SchemaAnalysisContext",
    "SchemaDiffContext",
    "MigrationPlanContext",
    "ExecutionContext",
    "RollbackContext",
    "ValidationContext",
    "Schema",
    "SchemaDifference",
    "RiskAssessment",
    "MigrationStep",
    # Execution strategies
    "HookExecutionStrategy",
    "HookErrorStrategy",
    "HookContextMutationPolicy",
    "HookPhaseConfig",
    "RetryConfig",
    # Observability
    "HookExecutionStatus",
    "HookExecutionEvent",
    "HookExecutionResult",
    "CircuitBreaker",
    "CircuitBreakerState",
    "HookExecutionTracer",
    "HookExecutionError",
    "ExecutionDAG",
    "PerformanceTrace",
    # Registry
    "HookRegistry",
]
