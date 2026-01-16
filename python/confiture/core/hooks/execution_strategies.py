"""Hook execution strategies and configuration for Phase 6."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class HookExecutionStrategy(Enum):
    """Defines how hooks execute within a phase."""

    SEQUENTIAL = "sequential"  # One by one, in priority order
    PARALLEL = "parallel"  # All simultaneously via asyncio.gather()
    PARALLEL_WITH_DEPS = "parallel_with_deps"  # DAG execution respecting dependencies


class HookErrorStrategy(Enum):
    """What happens when a hook fails."""

    FAIL_FAST = "fail_fast"  # Stop execution, fail migration
    FAIL_SAFE = "fail_safe"  # Log error, continue migration
    RETRY = "retry"  # Retry with exponential backoff
    ALERT_ONLY = "alert_only"  # Alert but continue


class HookContextMutationPolicy(Enum):
    """Whether downstream hooks can see upstream modifications."""

    IMMUTABLE = "immutable"  # Context is read-only
    MUTABLE = "mutable"  # Hooks can modify for downstream
    COPY_ON_WRITE = "copy_on_write"  # Each hook gets modified copy


@dataclass
class RetryConfig:
    """Retry strategy for RETRY error handling."""

    max_attempts: int = 3
    initial_delay_ms: int = 100
    max_delay_ms: int = 30000
    backoff_multiplier: float = 2.0


@dataclass
class HookPhaseConfig:
    """Configuration for hook execution in a specific phase."""

    phase: Any  # HookPhase | HookEvent | HookAlert
    execution_strategy: HookExecutionStrategy = HookExecutionStrategy.SEQUENTIAL
    error_strategy: HookErrorStrategy = HookErrorStrategy.FAIL_FAST
    context_mutation_policy: HookContextMutationPolicy = HookContextMutationPolicy.IMMUTABLE
    timeout_per_hook_ms: int = 30000  # 30 seconds per hook
    timeout_per_phase_ms: int = 300000  # 5 minutes per phase
    max_parallel_hooks: int = 4  # Limit concurrent execution
    retry_config: RetryConfig | None = None  # For RETRY strategy
    circuit_breaker_enabled: bool = True  # Prevent cascading failures
