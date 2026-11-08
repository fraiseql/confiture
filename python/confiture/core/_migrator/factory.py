"""``Migrator.from_config`` factory.

A free function that builds a managed :class:`MigratorSession` from an
``Environment`` / config path.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession


def from_config(
    config: Environment | Path | str,
    *,
    migrations_dir: Path | str = Path("db/migrations"),
    connection_factory: Callable[[Any], Any] | None = None,
    migration_loader: Callable[[Path], type] | None = None,
) -> MigratorSession:
    """Create a managed ``MigratorSession`` from an ``Environment`` config.

    Accepts an ``Environment`` object, a ``Path`` to a YAML config file, or a
    string path. The returned ``MigratorSession`` must be used as a context
    manager so the database connection is properly closed.

    Raises:
        ConfigurationError: If the config file cannot be found or is invalid.
    """
    env = config if isinstance(config, Environment) else Environment.from_file(config)

    return MigratorSession(
        env,
        Path(migrations_dir),
        connection_factory=connection_factory,
        migration_loader=migration_loader,
    )
