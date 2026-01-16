"""Hook registry and execution engine for Phase 6."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Generic, TypeVar

from .base import Hook, HookResult
from .context import HookContext
from .execution_strategies import (
    HookErrorStrategy,
    HookExecutionStrategy,
    HookPhaseConfig,
)
from .observability import (
    CircuitBreaker,
    HookExecutionError,
    HookExecutionEvent,
    HookExecutionResult,
    HookExecutionStatus,
    HookExecutionTracer,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _extract_phase_value(phase: Any) -> str:
    """Extract string value from phase enum or convert to string.

    Args:
        phase: A phase/event/alert that may be an enum or string.

    Returns:
        String representation of the phase value.
    """
    return phase.value if hasattr(phase, "value") else str(phase)


class HookRegistry(Generic[T]):
    """Manage hook registration and execution."""

    def __init__(
        self, execution_config: dict[Any, HookPhaseConfig] | None = None
    ):
        self.hooks: dict[str, list[Hook]] = {}  # phase/event/alert -> hooks
        self.execution_config = execution_config or {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.execution_log: list[HookExecutionEvent] = []
        self.tracer = HookExecutionTracer()

    def register(self, phase_key: str | Any, hook: Hook) -> None:
        """Register a hook for a phase/event/alert."""
        phase_value = _extract_phase_value(phase_key)

        if phase_value not in self.hooks:
            self.hooks[phase_value] = []

        self.hooks[phase_value].append(hook)

        # Create circuit breaker for this hook
        if hook.id not in self.circuit_breakers:
            self.circuit_breakers[hook.id] = CircuitBreaker(hook.id)

        logger.info(f"Registered hook {hook.name} ({hook.id}) for phase {phase_value}")

    async def trigger(
        self,
        phase: Any,  # HookPhase | HookEvent | HookAlert
        context: HookContext[T],
    ) -> HookExecutionResult:
        """Trigger hooks for a phase/event/alert."""
        phase_value = _extract_phase_value(phase)
        config = self.execution_config.get(
            phase, HookPhaseConfig(phase=phase)
        )
        hooks = self.hooks.get(phase_value, [])

        if not hooks:
            return HookExecutionResult(phase=phase_value, hooks_executed=0)

        # Execute according to strategy
        if config.execution_strategy == HookExecutionStrategy.SEQUENTIAL:
            return await self._execute_sequential(context, hooks, config)
        elif config.execution_strategy == HookExecutionStrategy.PARALLEL:
            return await self._execute_parallel(context, hooks, config)
        elif config.execution_strategy == HookExecutionStrategy.PARALLEL_WITH_DEPS:
            return await self._execute_dag(context, hooks, config)

        return HookExecutionResult(phase=phase_value, hooks_executed=0)

    async def _execute_sequential(
        self,
        context: HookContext[T],
        hooks: list[Hook],
        config: HookPhaseConfig,
    ) -> HookExecutionResult:
        """Execute hooks one-by-one."""
        results = []

        for hook in sorted(hooks, key=lambda h: h.priority):
            try:
                result = await self._execute_hook_with_timeout(
                    hook, context, config
                )
                results.append(result)

                # Check if we should fail fast
                if (
                    result.status == HookExecutionStatus.FAILED
                    and config.error_strategy == HookErrorStrategy.FAIL_FAST
                ):
                    raise HookExecutionError(
                        f"Hook {hook.name} failed: {result.error}"
                    )

            except Exception as e:
                if config.error_strategy == HookErrorStrategy.FAIL_SAFE:
                    logger.error(f"Hook {hook.name} failed: {e}")
                    results.append(
                        HookExecutionEvent(
                            execution_id=context.execution_id,
                            hook_id=hook.id,
                            phase=_extract_phase_value(config.phase),
                            status=HookExecutionStatus.FAILED,
                            error=str(e),
                            duration_ms=0,
                        )
                    )
                elif config.error_strategy == HookErrorStrategy.RETRY:
                    result = await self._retry_hook(hook, context, config)
                    results.append(result)
                else:
                    raise

        return HookExecutionResult(
            phase=_extract_phase_value(config.phase),
            hooks_executed=len(results),
            results=results,
            total_duration_ms=sum(r.duration_ms for r in results),
            failed_count=sum(1 for r in results if r.status == HookExecutionStatus.FAILED),
            timeout_count=sum(1 for r in results if r.status == HookExecutionStatus.TIMEOUT),
        )

    async def _execute_parallel(
        self,
        context: HookContext[T],
        hooks: list[Hook],
        config: HookPhaseConfig,
    ) -> HookExecutionResult:
        """Execute hooks in parallel."""
        # Limit parallelism
        semaphore = asyncio.Semaphore(config.max_parallel_hooks)

        async def execute_with_semaphore(hook: Hook) -> HookExecutionEvent:
            async with semaphore:
                return await self._execute_hook_with_timeout(hook, context, config)

        tasks = [execute_with_semaphore(hook) for hook in hooks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        failed = [
            r
            for r in results
            if isinstance(r, Exception) or r.status == HookExecutionStatus.FAILED
        ]
        if failed and config.error_strategy == HookErrorStrategy.FAIL_FAST:
            raise HookExecutionError(
                f"{len(failed)} hooks failed in parallel execution"
            )

        return HookExecutionResult(
            phase=_extract_phase_value(config.phase),
            hooks_executed=len(results),
            results=[r for r in results if not isinstance(r, Exception)],
            total_duration_ms=sum(
                r.duration_ms for r in results if not isinstance(r, Exception)
            ),
            failed_count=sum(
                1
                for r in results
                if not isinstance(r, Exception)
                and r.status == HookExecutionStatus.FAILED
            ),
            timeout_count=sum(
                1
                for r in results
                if not isinstance(r, Exception)
                and r.status == HookExecutionStatus.TIMEOUT
            ),
        )

    async def _execute_dag(
        self,
        context: HookContext[T],
        hooks: list[Hook],
        config: HookPhaseConfig,
    ) -> HookExecutionResult:
        """Execute hooks with dependency resolution."""
        # For now, fall back to sequential execution
        # Full DAG implementation would go here
        return await self._execute_sequential(context, hooks, config)

    async def _execute_hook_with_timeout(
        self,
        hook: Hook,
        context: HookContext[T],
        config: HookPhaseConfig,
    ) -> HookExecutionEvent:
        """Execute single hook with timeout enforcement."""
        start = datetime.utcnow()
        circuit_breaker = self.circuit_breakers.get(hook.id)

        if circuit_breaker and circuit_breaker.is_open:
            return HookExecutionEvent(
                execution_id=context.execution_id,
                hook_id=hook.id,
                phase=_extract_phase_value(config.phase),
                status=HookExecutionStatus.SKIPPED,
                reason="Circuit breaker open",
                duration_ms=0,
            )

        try:
            result: HookResult = await asyncio.wait_for(
                hook.execute(context),
                timeout=config.timeout_per_hook_ms / 1000,
            )
            duration = (datetime.utcnow() - start).total_seconds() * 1000

            event = HookExecutionEvent(
                execution_id=context.execution_id,
                hook_id=hook.id,
                phase=_extract_phase_value(config.phase),
                status=HookExecutionStatus.COMPLETED,
                duration_ms=int(duration),
                rows_affected=result.rows_affected,
                stats=result.stats,
            )

            if circuit_breaker:
                circuit_breaker.record_success()

            self.tracer.record_execution(event)
            return event

        except TimeoutError:
            if circuit_breaker:
                circuit_breaker.record_failure()
            return HookExecutionEvent(
                execution_id=context.execution_id,
                hook_id=hook.id,
                phase=_extract_phase_value(config.phase),
                status=HookExecutionStatus.TIMEOUT,
                reason=f"Exceeded {config.timeout_per_hook_ms}ms timeout",
                duration_ms=config.timeout_per_hook_ms,
            )
        except Exception as e:
            if circuit_breaker:
                circuit_breaker.record_failure()
            return HookExecutionEvent(
                execution_id=context.execution_id,
                hook_id=hook.id,
                phase=_extract_phase_value(config.phase),
                status=HookExecutionStatus.FAILED,
                error=str(e),
                duration_ms=int((datetime.utcnow() - start).total_seconds() * 1000),
            )

    async def _retry_hook(
        self,
        hook: Hook,
        context: HookContext[T],
        config: HookPhaseConfig,
    ) -> HookExecutionEvent:
        """Retry hook with exponential backoff."""
        if not config.retry_config:
            return await self._execute_hook_with_timeout(hook, context, config)

        retry_config = config.retry_config
        last_error = None

        for attempt in range(retry_config.max_attempts):
            try:
                return await self._execute_hook_with_timeout(hook, context, config)
            except Exception as e:
                last_error = e
                if attempt < retry_config.max_attempts - 1:
                    delay_ms = min(
                        retry_config.initial_delay_ms
                        * (retry_config.backoff_multiplier ** attempt),
                        retry_config.max_delay_ms,
                    )
                    logger.warning(
                        f"Hook {hook.name} failed, retrying in {delay_ms}ms "
                        f"(attempt {attempt + 1}/{retry_config.max_attempts})"
                    )
                    await asyncio.sleep(delay_ms / 1000)

        # All retries failed
        return HookExecutionEvent(
            execution_id=context.execution_id,
            hook_id=hook.id,
            phase=_extract_phase_value(config.phase),
            status=HookExecutionStatus.FAILED,
            error=f"Failed after {retry_config.max_attempts} attempts: {last_error}",
            duration_ms=0,
        )
