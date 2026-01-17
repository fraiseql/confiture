"""Observability and tracing infrastructure for hooks."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class HookExecutionStatus(Enum):
    """Status of hook execution."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class HookExecutionEvent:
    """Record of a single hook execution."""

    execution_id: UUID  # Trace correlation ID
    hook_id: str
    phase: str
    status: HookExecutionStatus
    duration_ms: int
    rows_affected: int = 0
    error: str | None = None
    reason: str | None = None
    stats: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HookExecutionResult:
    """Result of executing all hooks in a phase."""

    phase: str
    hooks_executed: int
    results: list[HookExecutionEvent] | None = None
    total_duration_ms: int = 0
    failed_count: int = 0
    timeout_count: int = 0


@dataclass
class ExecutionDAG:
    """Directed acyclic graph of hook dependencies."""

    execution_id: UUID
    hooks: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from, to) pairs


@dataclass
class PerformanceTrace:
    """Detailed performance trace of hook execution."""

    execution_id: UUID
    total_duration_ms: int
    hook_events: list[HookExecutionEvent] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)


class CircuitBreaker:
    """Prevent cascading failures from failing hooks."""

    def __init__(
        self,
        hook_id: str,
        failure_threshold: int = 5,
        recovery_timeout_ms: int = 60000,
    ):
        self.hook_id = hook_id
        self.failure_threshold = failure_threshold
        self.recovery_timeout_ms = recovery_timeout_ms
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED

    @property
    def is_open(self) -> bool:
        """Is circuit breaker open (blocking requests)?"""
        if self.state == CircuitBreakerState.OPEN:
            # Check if recovery timeout has elapsed
            if (
                self.last_failure_time
                and (datetime.now(UTC) - self.last_failure_time).total_seconds() * 1000
                > self.recovery_timeout_ms
            ):
                self.state = CircuitBreakerState.HALF_OPEN
                self.failure_count = 0
                return False
            return True
        return False

    def record_success(self) -> None:
        """Record successful hook execution."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record failed hook execution."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(UTC)

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            logger.warning(
                f"Circuit breaker opened for hook {self.hook_id} after "
                f"{self.failure_count} failures"
            )


class HookExecutionTracer:
    """Track and trace hook execution for debugging."""

    def __init__(self):
        self.execution_log: list[HookExecutionEvent] = []
        self.execution_graphs: dict[UUID, ExecutionDAG] = {}

    def record_execution(self, event: HookExecutionEvent) -> None:
        """Record hook execution event."""
        self.execution_log.append(event)
        logger.info(
            f"Hook {event.hook_id} in {event.phase}: {event.status.value} "
            f"({event.duration_ms}ms)"
        )

    def get_execution_log(
        self,
        execution_id: UUID | None = None,
        phase: str | None = None,
    ) -> list[HookExecutionEvent]:
        """Get execution log with optional filtering."""
        log = self.execution_log

        if execution_id:
            log = [e for e in log if e.execution_id == execution_id]

        if phase:
            log = [e for e in log if e.phase == phase]

        return log

    def get_execution_dag(self, execution_id: UUID) -> ExecutionDAG | None:
        """Get execution DAG showing hook dependencies."""
        return self.execution_graphs.get(execution_id)

    def get_performance_trace(self, execution_id: UUID) -> PerformanceTrace:
        """Get detailed performance trace."""
        events = self.get_execution_log(execution_id=execution_id)

        return PerformanceTrace(
            execution_id=execution_id,
            total_duration_ms=sum(e.duration_ms for e in events),
            hook_events=events,
            critical_path=self._compute_critical_path(events),
        )

    def _compute_critical_path(self, events: list[HookExecutionEvent]) -> list[str]:
        """Compute critical path - hooks that contributed most to total duration.

        Algorithm:
        1. Sort events by timestamp (execution order)
        2. Identify sequential execution blocks (no overlap)
        3. Return hooks in the longest duration chain

        Note: This assumes sequential execution. For parallel execution,
        a full DAG analysis with explicit dependencies would be needed.
        """
        if not events:
            return []

        if len(events) == 1:
            return [events[0].hook_id]

        # Sort events by timestamp and end time
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Find hooks that form a critical path (non-overlapping sequential chain)
        critical_path = []
        max_end_time = None

        for event in sorted_events:
            # Only include events that start after the previous one ended
            # (indicating sequential dependency)
            if max_end_time is None or event.timestamp >= max_end_time:
                critical_path.append(event.hook_id)
                # Update end time (approximated as timestamp + duration)
                end_timestamp = event.timestamp.timestamp() + (event.duration_ms / 1000)
                max_end_time = datetime.fromtimestamp(end_timestamp, tz=UTC)

        # If we got no sequential chain, return the longest single execution
        if not critical_path:
            longest = max(sorted_events, key=lambda e: e.duration_ms)
            return [longest.hook_id]

        return critical_path


class HookExecutionError(Exception):
    """Exception raised when hook execution fails."""

    pass
