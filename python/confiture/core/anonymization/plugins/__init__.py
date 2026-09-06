"""Custom anonymization strategies: import lint, then in-process loading.

:func:`load_strategy` rejects files that import blocked modules and then
executes the file in this process — with confiture's privileges — warning as it
does so. There is no isolation boundary here; see
:mod:`confiture.core.anonymization.plugins.import_lint`.

The pre-0.47 names (``SandboxViolationError``, ``SandboxResult``,
``execute_sandboxed``) remain importable from the deprecated
``plugins.sandbox`` module until 1.0.0.
"""

from confiture.core.anonymization.plugins.import_checker import (
    BLOCKED_MODULES,
    ImportViolation,
    check_file,
    check_source,
)
from confiture.core.anonymization.plugins.import_lint import (
    BlockedImportError,
    InProcessPluginWarning,
    StrategyTimeoutError,
    TimedResult,
    execute_timed,
    load_strategy,
)

__all__ = [
    "BLOCKED_MODULES",
    "BlockedImportError",
    "ImportViolation",
    "InProcessPluginWarning",
    "StrategyTimeoutError",
    "TimedResult",
    "check_file",
    "check_source",
    "execute_timed",
    "load_strategy",
]
