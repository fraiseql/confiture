"""Agent context tracking for workflow operations.

Provides AgentContext for tracking request IDs, workflow stages, and
operation types throughout the execution of agent workflows.
"""

from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Thread-local context var for storing current context
_context_var: ContextVar[Optional["AgentContext"]] = ContextVar("agent_context", default=None)


@dataclass
class AgentContext:
    """Context information for agent operations.

    Tracks request ID, workflow stage, operation type, and custom data
    throughout execution.

    Example:
        >>> ctx = AgentContext(
        ...     request_id="req-123",
        ...     workflow_stage="migration_up",
        ...     operation_type="apply_migration",
        ... )
        >>> with ctx:
        ...     # Code here has access to context
        ...     pass
    """

    request_id: str
    workflow_stage: str | None = None
    operation_type: str | None = None
    custom_data: dict[str, Any] = field(default_factory=dict)
    _previous_context: Optional["AgentContext"] = field(default=None, init=False, repr=False)

    def __enter__(self) -> "AgentContext":
        """Enter context manager."""
        # Store previous context to restore on exit
        self._previous_context = get_context()
        set_context(self)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        # Restore previous context
        set_context(self._previous_context)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dict.

        Returns:
            Dict representation of context
        """
        return asdict(self)

    def clone(self) -> "AgentContext":
        """Clone this context with independent data.

        Returns:
            New AgentContext with same values but independent custom_data
        """
        return AgentContext(
            request_id=self.request_id,
            workflow_stage=self.workflow_stage,
            operation_type=self.operation_type,
            custom_data=dict(self.custom_data),  # Make independent copy
        )


def set_context(ctx: AgentContext | None) -> None:
    """Set the current agent context.

    Args:
        ctx: Context to set, or None to clear
    """
    _context_var.set(ctx)


def get_context() -> AgentContext | None:
    """Get the current agent context.

    Returns:
        Current AgentContext or None if not set
    """
    return _context_var.get()


def with_context(
    request_id: str,
    workflow_stage: str | None = None,
    operation_type: str | None = None,
    custom_data: dict[str, Any] | None = None,
) -> AgentContext:
    """Create and set a new context.

    Convenience function for creating and setting context in one call.

    Args:
        request_id: Request identifier
        workflow_stage: Current workflow stage
        operation_type: Type of operation
        custom_data: Custom context data

    Returns:
        The created context
    """
    ctx = AgentContext(
        request_id=request_id,
        workflow_stage=workflow_stage,
        operation_type=operation_type,
        custom_data=custom_data or {},
    )
    set_context(ctx)
    return ctx
