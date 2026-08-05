"""``migrate validate --check-function-uniqueness`` logic (issue #136).

Static check (no database). Verifies every ``CREATE FUNCTION`` / ``CREATE
PROCEDURE`` in the scanned DDL directories has a unique fully-qualified
signature — two files defining the same ``schema.name(args)`` are silently
shadowed by ``confiture build``, so func_001 catches the duplicate first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.linting.schema_linter import LintViolation
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.validation.context import ValidationContext


@dataclass(frozen=True)
class FunctionUniquenessReport:
    """func_001 findings plus the gate decision (any violation fails)."""

    violations: list[LintViolation]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def check_function_uniqueness(
    scan_paths: list[Path],
    config_path: Path,
    ctx: ValidationContext | None = None,
) -> FunctionUniquenessReport:
    """Run func_001 across *scan_paths*.

    Args:
        scan_paths: DDL directories to scan.
        config_path: Config file carrying the optional ``function_coverage:`` block.
        ctx: Shared per-run resources; supplies the already-parsed config.

    Returns:
        A :class:`FunctionUniquenessReport`. No-op (empty) when the config has no
        ``function_coverage:`` block or ``function_coverage.enabled`` is false.

    Raises:
        ConfigurationError: the config file does not exist, or
            ``function_coverage:`` is malformed.
    """
    from confiture.core.connection import load_config
    from confiture.core.linting.libraries.functions import Func001FunctionUniqueness
    from confiture.core.validation.config_loaders import load_function_coverage

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = ctx.config_data if ctx is not None else load_config(config_path)
    coverage = load_function_coverage(config_data, config_path, require=False)

    violations: list[LintViolation] = []
    if coverage is not None and coverage.enabled:
        violations = Func001FunctionUniqueness(coverage=coverage).check(scan_paths)

    return FunctionUniquenessReport(violations=violations)
