"""``migrate validate --check-acls`` logic: every CREATE TABLE has a GRANT.

Static check (no database). Loads the optional ``acls:`` block, then lints the
migrations directory for tables missing matching grants — either inline or in
the configured global grant-sweep directory.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from confiture.config.environment import DEFAULT_GRANT_DIR
from confiture.core import connection as _core_connection
from confiture.core.linting.schema_linter import SchemaLinter
from confiture.core.validation.config_loaders import load_acl_expectations
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from confiture.core.validation.context import ValidationContext


def check_acl_coverage(
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

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = ctx.config_data if ctx is not None else _core_connection.load_config(config_path)
    # No-op when the project hasn't adopted the `acls:` block yet.
    expectations = load_acl_expectations(config_data, config_path, require=False)

    # The sweep is the project's, read from where the command runs as
    # ``--migrations-dir`` and the git checks' grant directory are (#715); the
    # config sits in ``db/environments/``, which holds no sweep. A project with no
    # sweep at the default path has none; one it names and lacks is said.
    configured = (
        config_data.get("migration", {}).get("grant_dir") if isinstance(config_data, dict) else None
    )
    grant_dir = Path(configured or DEFAULT_GRANT_DIR)
    if not configured and not grant_dir.is_dir():
        grant_dir = None

    return SchemaLinter.lint_migrations(
        migrations_dir=migrations_dir,
        expectations=expectations,
        grant_dir=grant_dir,
    )
