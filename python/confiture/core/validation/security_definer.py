"""``migrate validate --check-security-definer`` logic (issue #161).

Two paths share the same report type and formatter:

- **Static** (:func:`check_security_definer`): parses DDL source with pglast.
  No database required; ideal for pre-commit / CI on DDL repositories.
- **Live** (:func:`check_security_definer_live`): queries ``pg_proc.proconfig``
  directly.  Authoritative for migrate-strategy databases where
  ``ALTER FUNCTION … SET search_path`` may have been applied separately from
  the original ``CREATE``, which would false-positive on the static path.

Default severity is ``warning`` (advisory, exit 0). Set
``security_lint.severity: error`` in the environment config to make the
check a hard CI gate (exit 1 when ``has_errors``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.exceptions import ConfigurationError


@dataclass(frozen=True)
class SecurityDefinerReport:
    """sec_002 findings plus the gate decision.

    ``has_errors`` mirrors the gate used by ownership_coverage: advisory
    warnings do not fail, only ERROR-severity violations cause exit 1.
    """

    violations: list[LintViolation]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == RuleSeverity.ERROR for v in self.violations)


def check_security_definer(scan_paths: list[Path], config_path: Path) -> SecurityDefinerReport:
    """Run sec_002 across *scan_paths*.

    Returns:
        A :class:`SecurityDefinerReport`. No-op (empty) when the config has
        no ``security_lint:`` block or ``security_lint.enabled`` is false.

    Raises:
        ConfigurationError: the config file does not exist, or
            ``security_lint:`` is malformed.
    """
    from confiture.core.connection import load_config
    from confiture.core.linting.libraries.security_definer import (
        Sec002SecurityDefinerSearchPath,
    )
    from confiture.core.validation.config_loaders import load_security_lint

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = load_config(config_path)
    sec_lint = load_security_lint(config_data, config_path, require=False)

    if sec_lint is None or not sec_lint.enabled:
        return SecurityDefinerReport(violations=[])

    severity = RuleSeverity.ERROR if sec_lint.severity == "error" else RuleSeverity.WARNING
    rule = Sec002SecurityDefinerSearchPath(
        apply_to=sec_lint.apply_to,
        ignore=sec_lint.ignore,
        severity=severity,
    )
    return SecurityDefinerReport(violations=rule.check(scan_paths))


def check_security_definer_live(
    *,
    config_path: Path,
    schemas: str,
    ssh_via: str | None,
    exclude_extensions: bool = True,
) -> SecurityDefinerReport:
    """Query ``pg_proc`` for unpinned SECURITY DEFINER callables.

    Mirrors :func:`~confiture.core.validation.signature_drift.check_signature_drift`
    for connection plumbing (config, optional SSH tunnel).

    Args:
        config_path: Config file resolving the database connection.
        schemas: Comma-separated schema names to scan (e.g. ``"public,auth"``).
        ssh_via: Optional ``user@host`` SSH tunnel target overriding the config.
        exclude_extensions: Skip extension-owned functions (default ``True``).

    Returns:
        A :class:`SecurityDefinerReport`. No-op (empty) when the config has
        no ``security_lint:`` block or ``security_lint.enabled`` is false.

    Raises:
        ConfigurationError: config missing, connection failed, or
            ``security_lint:`` malformed.
    """
    from confiture.core.connection import load_config, open_connection
    from confiture.core.linting.libraries.security_definer import (
        Sec002SecurityDefinerSearchPath,
    )
    from confiture.core.validation.config_loaders import load_security_lint
    from confiture.core.validation.signature_drift import _ssh_override

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = load_config(config_path)
    sec_lint = load_security_lint(config_data, config_path, require=False)

    if sec_lint is None or not sec_lint.enabled:
        return SecurityDefinerReport(violations=[])

    severity = RuleSeverity.ERROR if sec_lint.severity == "error" else RuleSeverity.WARNING
    rule = Sec002SecurityDefinerSearchPath(
        apply_to=sec_lint.apply_to,
        ignore=sec_lint.ignore,
        severity=severity,
    )
    schema_list = [s.strip() for s in schemas.split(",") if s.strip()]

    effective_config = _ssh_override(config_data, ssh_via) if ssh_via else config_data
    with open_connection(effective_config) as conn:
        violations = rule.check_live(
            conn,
            schemas=schema_list,
            exclude_extensions=exclude_extensions,
        )

    return SecurityDefinerReport(violations=violations)


def emit_remediation(report: SecurityDefinerReport, output_path: Path) -> int:
    """Write a SQL remediation script for all violations that have ``suggested_fix``.

    Each ``ALTER FUNCTION … SET search_path`` statement is written verbatim,
    one per line.  Violations without a fix (e.g. live-path rows for procedures
    that require ``ALTER PROCEDURE``) are skipped silently.

    Args:
        report: The report returned by :func:`check_security_definer` or
            :func:`check_security_definer_live`.
        output_path: Where to write the ``.sql`` file.

    Returns:
        Number of statements written.
    """
    stmts = [v.suggested_fix for v in report.violations if v.suggested_fix]
    output_path.write_text("\n".join(stmts) + ("\n" if stmts else ""))
    return len(stmts)
