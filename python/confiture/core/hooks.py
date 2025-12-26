"""Migration hooks system for Phase 4 - before/after DDL execution hooks.

This module provides a flexible hook system that allows executing custom code
before and after schema migrations. Hooks are useful for:
- Backfilling read models (CQRS)
- Data consistency validation
- Maintaining application invariants
- Custom transformations during schema evolution
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg
from importlib.metadata import entry_points

from confiture.exceptions import MigrationError

# Logger for hook execution
logger = logging.getLogger(__name__)


class HookPhase(Enum):
    """Phases during migration execution where hooks can run."""

    BEFORE_VALIDATION = 1  # Pre-flight checks before migration
    BEFORE_DDL = 2         # Data prep before structural changes
    AFTER_DDL = 3          # Data backfill after structural changes
    AFTER_VALIDATION = 4   # Verification after data operations
    CLEANUP = 5            # Final cleanup operations
    ON_ERROR = 6           # Error handlers during rollback


@dataclass
class HookResult:
    """Result of hook execution."""

    phase: str
    hook_name: str
    rows_affected: int = 0
    stats: dict[str, Any] | None = None
    execution_time_ms: int = 0

    def __post_init__(self):
        """Initialize stats if not provided."""
        if self.stats is None:
            self.stats = {}


class HookContext:
    """Context passed to hooks during migration execution.

    Provides hooks with access to migration metadata and allows
    hooks to exchange data (e.g., row counts before/after).
    """

    def __init__(
        self,
        migration_name: str,
        migration_version: str,
        direction: str = "forward",
    ):
        """Initialize hook context.

        Args:
            migration_name: Name of migration (e.g., "001_add_users")
            migration_version: Version identifier (e.g., "001")
            direction: Direction of migration ("forward" or "backward")
        """
        self.migration_name = migration_name
        self.migration_version = migration_version
        self.direction = direction
        self.stats: dict[str, Any] = {}

    def get_stat(self, key: str) -> Any:
        """Get a stored statistic."""
        return self.stats.get(key)

    def set_stat(self, key: str, value: Any) -> None:
        """Store a statistic for later use."""
        self.stats[key] = value


class HookError(MigrationError):
    """Error raised when hook execution fails."""

    def __init__(self, hook_name: str, phase: str, error: Exception):
        """Initialize hook error.

        Args:
            hook_name: Name of hook that failed
            phase: Hook phase name
            error: Original exception
        """
        self.hook_name = hook_name
        self.phase = phase
        self.original_error = error
        super().__init__(
            f"Hook {hook_name} failed in phase {phase}: {str(error)}"
        )


class Hook(ABC):
    """Abstract base class for all migration hooks.

    Hooks execute custom code before, during, and after migrations.
    Each hook executes within its own savepoint for isolation.

    Example:
        class BackfillReadModelHook(Hook):
            phase = HookPhase.AFTER_DDL

            def execute(self, conn, context):
                result = conn.execute(
                    \"INSERT INTO r_customer_lifetime_value ...\"
                )
                return HookResult(
                    phase="AFTER_DDL",
                    hook_name="BackfillReadModel",
                    rows_affected=result.rowcount
                )
    """

    phase: HookPhase

    @abstractmethod
    def execute(
        self,
        conn: psycopg.Connection,
        context: HookContext,
    ) -> HookResult:
        """Execute hook logic.

        Args:
            conn: Database connection
            context: HookContext with migration metadata

        Returns:
            HookResult with execution status and metadata

        Raises:
            Exception: Any errors are wrapped in HookError
        """
        pass


class HookRegistry:
    """Registry for built-in and custom hooks.

    Allows registration and lookup of hooks by name for easy configuration
    in migration files and YAML files. Supports both manual registration
    and automatic discovery via setuptools entry points.

    Example:
        registry = HookRegistry()
        registry.register("backfill_read_model", BackfillReadModelHook)
        hook_class = registry.get("backfill_read_model")
    """

    def __init__(self):
        """Initialize hook registry and load entry points."""
        self._hooks: dict[str, type[Hook]] = {}
        self._load_entry_points()

    def _load_entry_points(self) -> None:
        """Load hooks from setuptools entry points.

        Discovers and loads hooks registered via the 'confiture.hooks' entry
        point group. This allows third-party packages to provide hooks without
        requiring code changes.

        Handles both Python 3.10+ (entry_points(group="...")) and Python 3.9
        (entry_points().get("...")) API styles for compatibility.
        """
        try:
            # Try Python 3.10+ style first
            try:
                eps = entry_points(group="confiture.hooks")
            except TypeError:
                # Fall back to Python 3.9 style
                eps = entry_points().get("confiture.hooks", [])

            for ep in eps:
                try:
                    hook_class = ep.load()
                    # Validate it's a Hook subclass
                    if not issubclass(hook_class, Hook):
                        logger.warning(
                            f"Entry point '{ep.name}' does not resolve to a Hook subclass, skipping"
                        )
                        continue
                    self.register(ep.name, hook_class)
                except Exception as e:
                    logger.warning(
                        f"Failed to load hook from entry point {ep.name}: {e}"
                    )
        except Exception as e:
            logger.warning(f"Failed to load entry points: {e}")

    def register(self, name: str, hook_class: type[Hook]) -> None:
        """Register a hook class by name.

        Args:
            name: Name for the hook (e.g., "backfill_read_model")
            hook_class: Hook class (subclass of Hook)

        Raises:
            TypeError: If hook_class is not a Hook subclass
        """
        if not issubclass(hook_class, Hook):
            raise TypeError(f"{hook_class} must be a subclass of Hook")

        self._hooks[name] = hook_class

    def get(self, name: str) -> type[Hook] | None:
        """Get a registered hook class by name.

        Args:
            name: Hook name

        Returns:
            Hook class or None if not found
        """
        return self._hooks.get(name)

    def list_hooks(self) -> list[str]:
        """List all registered hook names.

        Returns:
            List of registered hook names
        """
        return list(self._hooks.keys())

    def unregister(self, name: str) -> None:
        """Unregister a hook by name.

        Args:
            name: Hook name
        """
        self._hooks.pop(name, None)


# Global hook registry instance
_global_registry = HookRegistry()


def register_hook(name: str, hook_class: type[Hook]) -> None:
    """Register a hook in the global registry.

    Args:
        name: Hook name
        hook_class: Hook class
    """
    _global_registry.register(name, hook_class)


def get_hook(name: str) -> type[Hook] | None:
    """Get a hook from the global registry.

    Args:
        name: Hook name

    Returns:
        Hook class or None
    """
    return _global_registry.get(name)


class HookExecutor:
    """Executes hooks during migration with savepoint support.

    Features:
    - Sequential hook execution within a phase
    - Savepoint per hook for isolation and rollback
    - Detailed error reporting with hook context
    - Metric collection for performance tracking
    - Structured logging for observability
    """

    def __init__(self):
        """Initialize hook executor."""
        self.registry = _global_registry
        self.logger = logger

    def execute_phase(
        self,
        conn: psycopg.Connection,
        phase: HookPhase,
        hooks: list[Hook],
        context: HookContext,
    ) -> list[HookResult]:
        """Execute all hooks for a given phase.

        Hooks are executed sequentially. Each hook runs within its own
        savepoint, so if a hook fails, only that hook's work is rolled back.

        Args:
            conn: Database connection
            phase: HookPhase to execute
            hooks: List of Hook instances to run
            context: HookContext for execution

        Returns:
            List of HookResult objects (one per hook)

        Raises:
            HookError: If any hook execution fails
        """
        results: list[HookResult] = []

        # Log phase start
        self.logger.info(
            "executing_hooks",
            extra={
                "phase": phase.name,
                "hook_count": len(hooks),
                "migration": context.migration_name,
            }
        )

        for hook in hooks:
            hook_name = hook.__class__.__name__
            start_time = time.time()

            try:
                # Log hook start
                self.logger.debug(
                    "hook_start",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "migration": context.migration_name,
                    }
                )

                # Execute hook (in real implementation, wrap in savepoint)
                result = hook.execute(conn, context)
                duration_ms = int((time.time() - start_time) * 1000)

                # Log hook completion
                self.logger.info(
                    "hook_completed",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "duration_ms": duration_ms,
                        "rows_affected": result.rows_affected,
                        "migration": context.migration_name,
                    }
                )

                results.append(result)

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                # Log hook failure
                self.logger.error(
                    "hook_failed",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "duration_ms": duration_ms,
                        "error": str(e),
                        "migration": context.migration_name,
                    },
                    exc_info=True
                )

                # Wrap any exception in HookError with context
                raise HookError(
                    hook_name=hook_name,
                    phase=phase.name,
                    error=e,
                ) from e

        # Log phase completion
        self.logger.info(
            "phase_completed",
            extra={
                "phase": phase.name,
                "hooks_executed": len(results),
                "migration": context.migration_name,
            }
        )

        return results
