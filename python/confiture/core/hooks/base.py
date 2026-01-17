"""Base classes for hooks with priority and dependencies."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from .context import HookContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


class HookError(Exception):
    """Exception raised during hook execution.

    Provides detailed error information including the hook that failed,
    the context in which it failed, and any nested exceptions.

    Attributes:
        hook_id: ID of the hook that failed
        hook_name: Name of the hook that failed
        phase: Migration phase when error occurred (e.g., "pre_migration", "post_migration")
        message: Error message
        cause: Original exception that caused this error
    """

    def __init__(
        self,
        message: str,
        hook_id: str | None = None,
        hook_name: str | None = None,
        phase: str | None = None,
        cause: Exception | None = None,
    ):
        """Initialize hook error.

        Args:
            message: Error message
            hook_id: ID of hook that failed
            hook_name: Name of hook that failed
            phase: Migration phase when error occurred
            cause: Original exception (for chaining)
        """
        self.hook_id = hook_id
        self.hook_name = hook_name
        self.phase = phase
        self.cause = cause

        # Build detailed error message
        parts = [message]
        if hook_name:
            parts.append(f"(hook: {hook_name})")
        if phase:
            parts.append(f"(phase: {phase})")

        full_message = " ".join(parts)
        super().__init__(full_message)


@dataclass
class HookResult:
    """Result of hook execution."""

    success: bool
    rows_affected: int = 0
    stats: dict[str, Any] | None = None
    error: str | None = None


class Hook(Generic[T], ABC):
    """Base class for all hooks."""

    def __init__(
        self,
        hook_id: str,
        name: str,
        priority: int = 5,  # 1-10, lower = higher priority
        depends_on: list[str] | None = None,
    ):
        self.id = hook_id
        self.name = name
        self.priority = priority
        self.depends_on = depends_on or []

    @abstractmethod
    async def execute(self, context: HookContext[T]) -> HookResult:
        """Execute hook - must be implemented by subclasses."""
        pass


class HookExecutor:
    """Executes hooks in configured order with proper error handling.

    Manages hook execution with support for:
    - Sequential execution with proper ordering
    - Dependency resolution
    - Error handling and recovery
    - Execution context management
    - Performance tracking

    Example:
        >>> executor = HookExecutor(registry=registry)
        >>> await executor.execute_phase("pre_migration", context)
    """

    def __init__(self, registry: Any | None = None):
        """Initialize hook executor.

        Args:
            registry: Hook registry with registered hooks (optional)
        """
        self.registry = registry
        self._executed_hooks: set[str] = set()
        self._hook_results: dict[str, HookResult] = {}

    async def execute_phase(self, phase: str, context: Any) -> dict[str, HookResult]:
        """Execute all hooks for a given phase.

        Args:
            phase: Phase name (e.g., "pre_migration", "post_migration")
            context: Hook execution context with migration state

        Returns:
            Dictionary mapping hook IDs to their execution results

        Raises:
            HookError: If any hook fails during execution
        """
        if not self.registry:
            logger.debug(f"No hook registry configured, skipping phase: {phase}")
            return {}

        try:
            # Get hooks for this phase
            hooks = self.registry.get_hooks(phase) if hasattr(self.registry, "get_hooks") else []

            if not hooks:
                logger.debug(f"No hooks registered for phase: {phase}")
                return {}

            # Sort hooks by priority (lower number = higher priority)
            sorted_hooks = sorted(hooks, key=lambda h: getattr(h, "priority", 5))

            # Execute hooks
            for hook in sorted_hooks:
                await self._execute_single_hook(hook, phase, context)

            return self._hook_results

        except HookError:
            raise
        except Exception as e:
            raise HookError(
                message=f"Unexpected error executing phase '{phase}'",
                phase=phase,
                cause=e,
            ) from e

    async def _execute_single_hook(self, hook: Any, phase: str, context: Any) -> None:
        """Execute a single hook with error handling.

        Args:
            hook: Hook instance to execute
            phase: Phase name
            context: Hook execution context

        Raises:
            HookError: If hook execution fails
        """
        hook_id = getattr(hook, "id", "unknown")
        hook_name = getattr(hook, "name", "unknown")

        # Check dependencies
        depends_on = getattr(hook, "depends_on", [])
        if depends_on:
            for dep_id in depends_on:
                if dep_id not in self._executed_hooks:
                    raise HookError(
                        message=f"Dependency '{dep_id}' not executed",
                        hook_id=hook_id,
                        hook_name=hook_name,
                        phase=phase,
                    )

        try:
            logger.debug(f"Executing hook '{hook_name}' ({hook_id}) in phase '{phase}'")

            # Execute the hook
            if hasattr(hook, "execute"):
                result = (
                    await hook.execute(context)
                    if hasattr(hook.execute, "__await__")
                    else hook.execute(context)
                )
            else:
                raise HookError(
                    message="Hook does not have execute method",
                    hook_id=hook_id,
                    hook_name=hook_name,
                    phase=phase,
                )

            # Store result
            self._hook_results[hook_id] = result
            self._executed_hooks.add(hook_id)

            if not result.success:
                error_msg = result.error or "Unknown error"
                raise HookError(
                    message=f"Hook execution failed: {error_msg}",
                    hook_id=hook_id,
                    hook_name=hook_name,
                    phase=phase,
                )

            logger.debug(f"Hook '{hook_name}' completed successfully")

        except HookError:
            raise
        except Exception as e:
            raise HookError(
                message=f"Exception during hook execution: {str(e)}",
                hook_id=hook_id,
                hook_name=hook_name,
                phase=phase,
                cause=e,
            ) from e
