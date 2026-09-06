"""Import lint and in-process loading for custom anonymization strategies.

A custom strategy is a Python file the operator points confiture at. Before it
is loaded, :func:`load_strategy` rejects files that import modules on the
block list (``os``, ``subprocess``, ...). That check is a **lint**: it catches
the obvious, it does not contain the rest. The module is then executed with
:mod:`importlib` in the confiture process, with confiture's privileges, on the
operator's host. Loading a plugin is therefore an act of trust in its author,
and every load says so with :class:`InProcessPluginWarning` and a WARNING log
line.

Process isolation would be a separate feature; nothing here claims it.
"""

from __future__ import annotations

import importlib.util
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from confiture.core.anonymization.plugins.import_checker import (
    ImportViolation,
    check_file,
)
from confiture.core.anonymization.strategy import AnonymizationStrategy
from confiture.exceptions import ConfiturError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 5.0


class InProcessPluginWarning(UserWarning):
    """Emitted whenever a custom strategy file is executed in-process."""


class BlockedImportError(ConfiturError):
    """Raised when a custom strategy module imports a blocked module."""

    def __init__(self, path: Path, violations: list[ImportViolation]) -> None:
        details = "; ".join(f"{v.module} (line {v.line})" for v in violations)
        super().__init__(f"Blocked imports in {path.name}: {details}")
        self.violations = violations


class StrategyTimeoutError(ConfiturError):
    """Raised when a custom strategy exceeds execution timeout."""


@dataclass(frozen=True)
class TimedResult:
    """Result of a timed strategy execution."""

    value: Any
    duration_ms: float
    strategy_name: str


def load_strategy(path: Path) -> type[AnonymizationStrategy]:
    """Lint *path* for blocked imports, then import it and return its strategy class.

    The file must contain exactly one :class:`AnonymizationStrategy` subclass.
    The module runs in this process: the lint is a filter on the obvious, not a
    boundary, and the call warns to that effect.

    Args:
        path: The strategy file.

    Returns:
        The one strategy class the file defines.

    Raises:
        BlockedImportError: The file imports a blocked module.
        ConfiturError: The file cannot be loaded, or defines zero or several
            strategy classes.

    Warns:
        InProcessPluginWarning: Always, once per load.
    """
    violations = check_file(path)
    if violations:
        raise BlockedImportError(path, violations)

    message = (
        f"Loading custom strategy {path.name} from {path}: it executes in-process with "
        "confiture's privileges. The import check is a lint, not a sandbox — load only "
        "code you trust."
    )
    logger.warning(message)
    warnings.warn(message, InProcessPluginWarning, stacklevel=2)

    spec = importlib.util.spec_from_file_location(
        f"confiture_custom_{path.stem}",
        path,
    )
    if spec is None or spec.loader is None:
        msg = f"Cannot load module from {path}"
        raise ConfiturError(msg)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find the strategy subclass
    candidates = [
        obj
        for name, obj in vars(module).items()
        if (
            isinstance(obj, type)
            and issubclass(obj, AnonymizationStrategy)
            and obj is not AnonymizationStrategy
        )
    ]
    if not candidates:
        msg = f"No AnonymizationStrategy subclass found in {path.name}"
        raise ConfiturError(msg)
    if len(candidates) > 1:
        names = [c.__name__ for c in candidates]
        msg = f"Multiple strategy classes in {path.name}: {names}. Use one per file."
        raise ConfiturError(msg)

    logger.info("Loaded custom strategy %s from %s", candidates[0].__name__, path)
    return candidates[0]


def execute_timed(
    strategy: AnonymizationStrategy,
    value: Any,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> TimedResult:
    """Run ``strategy.anonymize(value)`` and report how long it took.

    The timeout is advisory: an execution that overruns it is logged at
    WARNING, not interrupted. Failures are logged and re-raised.

    Args:
        strategy: The strategy to run.
        value: The value to anonymize.
        timeout_s: Duration above which the run is logged as slow.

    Returns:
        The anonymized value with its timing.
    """
    name = strategy.__class__.__name__
    start = time.perf_counter()

    try:
        result = strategy.anonymize(value)
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.warning(
            "Custom strategy %s failed after %.1fms: %s",
            name,
            elapsed,
            exc,
        )
        raise

    elapsed = (time.perf_counter() - start) * 1000
    if elapsed > timeout_s * 1000:
        logger.warning(
            "Custom strategy %s exceeded timeout: %.1fms > %.0fms",
            name,
            elapsed,
            timeout_s * 1000,
        )

    logger.debug("Strategy %s executed in %.1fms", name, elapsed)
    return TimedResult(value=result, duration_ms=elapsed, strategy_name=name)
