"""Deprecated alias of :mod:`confiture.core.anonymization.plugins.import_lint`.

The module was renamed because "sandbox" promised isolation it never had: the
import check is a lint, and the plugin runs in-process. This shim keeps the old
import path and names working for one release; it is removed in 1.0.0.
"""

from __future__ import annotations

import warnings

from confiture.core.anonymization.plugins.import_lint import (
    DEFAULT_TIMEOUT_S,
    BlockedImportError,
    StrategyTimeoutError,
    TimedResult,
    execute_timed,
    load_strategy,
)

warnings.warn(
    "confiture.core.anonymization.plugins.sandbox is deprecated; import from "
    "confiture.core.anonymization.plugins.import_lint (the plugin runs in-process; "
    "the check is an import lint, not a sandbox). This alias is removed in 1.0.0.",
    DeprecationWarning,
    stacklevel=2,
)

SandboxViolationError = BlockedImportError
SandboxResult = TimedResult
execute_sandboxed = execute_timed

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "SandboxResult",
    "SandboxViolationError",
    "StrategyTimeoutError",
    "execute_sandboxed",
    "load_strategy",
]
