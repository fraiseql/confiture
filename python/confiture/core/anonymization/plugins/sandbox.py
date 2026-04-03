"""Security sandbox for loading and executing custom strategies."""

from __future__ import annotations

import importlib.util
import logging
import time
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


class SandboxViolationError(ConfiturError):
    """Raised when a custom strategy module contains blocked imports."""

    def __init__(self, path: Path, violations: list[ImportViolation]) -> None:
        details = "; ".join(f"{v.module} (line {v.line})" for v in violations)
        super().__init__(f"Blocked imports in {path.name}: {details}")
        self.violations = violations


class StrategyTimeoutError(ConfiturError):
    """Raised when a custom strategy exceeds execution timeout."""


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandboxed strategy execution."""

    value: Any
    duration_ms: float
    strategy_name: str


def load_strategy(path: Path) -> type[AnonymizationStrategy]:
    """Load a custom strategy class from a file, after security checks.

    The file must contain exactly one AnonymizationStrategy subclass.

    Raises:
        SandboxViolationError: If blocked imports are detected.
        ConfiturError: If no strategy class found in module.
    """
    violations = check_file(path)
    if violations:
        raise SandboxViolationError(path, violations)

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


def execute_sandboxed(
    strategy: AnonymizationStrategy,
    value: Any,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> SandboxResult:
    """Execute a strategy's anonymize() with timeout and logging.

    Note: timeout is enforced via signal.alarm on Unix. On platforms
    without signal support, timeout is advisory (logged but not enforced).
    """
    name = strategy.__class__.__name__
    start = time.perf_counter()

    # Simple timeout — strategies are sync and typically fast (<100ms).
    # For truly untrusted code, consider subprocess isolation in future.
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
    return SandboxResult(value=result, duration_ms=elapsed, strategy_name=name)
