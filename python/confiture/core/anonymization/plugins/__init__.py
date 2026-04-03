"""Security sandbox for custom anonymization strategies.

This module provides safe loading and execution of user-provided
anonymization strategies, with import blocking and execution monitoring.
"""

from confiture.core.anonymization.plugins.import_checker import (
    BLOCKED_MODULES,
    ImportViolation,
    check_file,
    check_source,
)
from confiture.core.anonymization.plugins.sandbox import (
    SandboxResult,
    SandboxViolationError,
    StrategyTimeoutError,
    execute_sandboxed,
    load_strategy,
)

__all__ = [
    "load_strategy",
    "execute_sandboxed",
    "SandboxResult",
    "SandboxViolationError",
    "StrategyTimeoutError",
    "check_file",
    "check_source",
    "ImportViolation",
    "BLOCKED_MODULES",
]
