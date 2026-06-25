"""``Migrator.from_config`` factory (peeled from engine.py).

A free function that builds a managed :class:`MigratorSession` from an
``Environment`` / config path. ``MigratorSession`` is imported lazily inside the
function so this module carries no import-time dependency on ``session`` (which
imports the engine) — keeping the package free of an import cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confiture.config.environment import Environment
    from confiture.core._migrator.session import MigratorSession


def from_config(
    config: Environment | Path | str,
    *,
    migrations_dir: Path | str = Path("db/migrations"),
) -> MigratorSession:
    """Create a managed ``MigratorSession`` from an ``Environment`` config.

    Accepts an ``Environment`` object, a ``Path`` to a YAML config file, or a
    string path. The returned ``MigratorSession`` must be used as a context
    manager so the database connection is properly closed.

    Raises:
        ConfigurationError: If the config file cannot be found or is invalid.
    """
    from confiture.config.environment import Environment
    from confiture.core._migrator.session import MigratorSession

    if isinstance(config, Environment):
        env = config
    else:
        import yaml

        config_path = Path(config)
        if not config_path.exists():
            from confiture.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Configuration file not found: {config_path}",
                error_code="CONFIG_004",
                context={"file_path": str(config_path)},
                resolution_hint=f"Create a config file at {config_path} or use an existing one",
            )
        with open(config_path) as f:
            raw: dict[str, Any] = yaml.safe_load(f)
        # Issue #168: the migrate-only Python entry point must accept the same
        # minimal ``database_url``-only config the CLI's ``migrate up`` accepts.
        # The CLI loads a raw dict (``connection.load_config``) and never
        # validates the build-only fields ``name``/``include_dirs``; those are
        # never read on the migrate path either (``MigratorSession`` uses only
        # ``database_url`` and ``migration.tracking_table``).  Default them when
        # absent so ``from_config`` isn't stricter than the CLI.  A truly
        # invalid config (e.g. missing ``database_url``) still fails validation.
        if isinstance(raw, dict):
            raw.setdefault("name", config_path.stem)
            raw.setdefault("include_dirs", [])
        try:
            env = Environment.model_validate(raw)
        except Exception as e:
            if "ValidationError" in type(e).__name__:
                from confiture.exceptions import ConfigurationError

                raise ConfigurationError(
                    f"Invalid configuration in {config_path}: {e}",
                    error_code="CONFIG_002",
                    context={"file_path": str(config_path)},
                    resolution_hint=f"Fix validation errors in {config_path}",
                ) from e
            raise

    return MigratorSession(env, Path(migrations_dir))
