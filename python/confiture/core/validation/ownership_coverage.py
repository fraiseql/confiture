"""``migrate validate --check-ownership-coverage`` logic (issues #124/#137).

Static check (no database). Verifies every created relation is paired with an
``ALTER … OWNER TO <expected_owner>`` (own_001) and flags bare ``ALTER … OWNER
TO`` on objects the migration didn't create (own_002).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.exceptions import ConfigurationError


@dataclass(frozen=True)
class OwnershipCoverageReport:
    """Ownership-coverage findings plus the gate decision.

    ``has_errors`` mirrors the historical gate: warnings (own_002 guarded) print
    but do not fail; only ERROR-severity violations block (exit 1).
    """

    violations: list[LintViolation]

    @property
    def has_errors(self) -> bool:
        return any(v.severity == RuleSeverity.ERROR for v in self.violations)


def check_ownership_coverage(
    migrations_dir: Path, config_path: Path
) -> OwnershipCoverageReport:
    """Run own_001 + own_002 against *migrations_dir*.

    Returns:
        An :class:`OwnershipCoverageReport`. No-op (empty) when the config has no
        ``ownership:`` block or ``ownership.lint_enabled`` is false.

    Raises:
        ConfigurationError: the config file does not exist, or ``ownership:`` is
            malformed.
    """
    from confiture.core.connection import load_config
    from confiture.core.linting.libraries.ownership import (
        Own001OwnershipCoverage,
        Own002BareAlterOwner,
    )
    from confiture.core.validation.config_loaders import load_ownership_expectation

    if not config_path.exists():
        raise ConfigurationError(
            f"Config file not found: {config_path}", error_code="CONFIG_004"
        )

    config_data = load_config(config_path)
    # No-op when the project hasn't adopted the `ownership:` block yet.
    ownership_exp = load_ownership_expectation(config_data, config_path, require=False)

    violations: list[LintViolation] = []
    if ownership_exp is not None:
        violations = Own001OwnershipCoverage(expectation=ownership_exp).check(migrations_dir)
        # Issue #137 — own_002 sibling rule: bare `ALTER … OWNER TO` on objects
        # the migration didn't create.
        violations.extend(Own002BareAlterOwner(expectation=ownership_exp).check(migrations_dir))

    return OwnershipCoverageReport(violations=violations)
