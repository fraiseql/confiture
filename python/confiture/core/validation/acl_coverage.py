"""``migrate validate --check-acls`` logic: every CREATE TABLE has a GRANT.

Static check (no database). Loads the optional ``acls:`` block, then lints the
migrations directory for tables missing matching grants — either inline or in
the configured global grant-sweep directory.
"""

from __future__ import annotations

from pathlib import Path

from confiture.exceptions import ConfigurationError


def check_acl_coverage(migrations_dir: Path, config_path: Path):  # noqa: ANN201
    """Lint *migrations_dir* for ACL coverage against the config's ``acls:`` block.

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
        raise ConfigurationError(
            f"Config file not found: {config_path}", error_code="CONFIG_004"
        )

    config_data = load_config(config_path)
    # No-op when the project hasn't adopted the `acls:` block yet.
    expectations = load_acl_expectations(config_data, config_path, require=False)

    grant_dir_raw = (
        config_data.get("migration", {}).get("grant_dir")
        if isinstance(config_data, dict)
        else None
    ) or "db/7_grant"
    grant_dir = (config_path.parent / grant_dir_raw).resolve()

    return SchemaLinter().lint_migrations(
        migrations_dir=migrations_dir,
        expectations=expectations,
        grant_dir=grant_dir if grant_dir.exists() else None,
    )
