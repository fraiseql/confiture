"""Core migration execution and schema building components."""

from confiture.core.dry_run import (
    DryRunError,
    DryRunExecutor,
    DryRunResult,
)
from confiture.core.hooks import (
    Hook,
    HookContext,
    HookError,
    HookExecutor,
    HookPhase,
    HookRegistry,
    HookResult,
    get_hook,
    register_hook,
)

__all__ = [
    # Dry-run mode
    "DryRunError",
    "DryRunExecutor",
    "DryRunResult",
    # Hook system
    "Hook",
    "HookContext",
    "HookError",
    "HookExecutor",
    "HookPhase",
    "HookRegistry",
    "HookResult",
    "get_hook",
    "register_hook",
]
