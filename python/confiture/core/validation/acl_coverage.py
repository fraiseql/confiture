"""``migrate validate --check-acls`` logic: every CREATE TABLE has a GRANT.

Static check (no database). Loads the optional ``acls:`` block, then lints the
migrations directory for tables missing matching grants — either inline or in
the configured global grant-sweep directory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.validation.context import ValidationContext


def check_acl_coverage(  # noqa: ANN201
    migrations_dir: Path,
    config_path: Path,
    ctx: ValidationContext | None = None,
):
    """Lint *migrations_dir* for ACL coverage against the config's ``acls:`` block.

    Args:
        migrations_dir: Directory of migration files to lint.
        config_path: Config file carrying the optional ``acls:`` block.
        ctx: Shared per-run resources; supplies the already-parsed config.

    Returns:
        The :class:`~confiture.models.lint.LintReport` from the schema linter.
        No-op (empty report) when the config has no ``acls:`` block.

    Raises:
        ConfigurationError: the config file does not exist, or ``acls:`` is
            malformed.
    """
    from confiture.core.connection import load_config
    from confiture.core.linting.schema_linter import SchemaLinter
    from confiture.core.validation.config_loaders import load_acl_expectations

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = ctx.config_data if ctx is not None else load_config(config_path)
    # No-op when the project hasn't adopted the `acls:` block yet.
    expectations = load_acl_expectations(config_data, config_path, require=False)

    grant_dir_raw = (
        config_data.get("migration", {}).get("grant_dir") if isinstance(config_data, dict) else None
    ) or "db/7_grant"
    grant_dir = (config_path.parent / grant_dir_raw).resolve()

    return SchemaLinter().lint_migrations(
        migrations_dir=migrations_dir,
        expectations=expectations,
        grant_dir=grant_dir if grant_dir.exists() else None,
    )
