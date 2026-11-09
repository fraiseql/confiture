"""The ``migration:`` settings and DSN the migrate commands read from their config file."""

from dataclasses import dataclass
from pathlib import Path

from confiture.config.environment import MigrationConfig, migration_block
from confiture.core import connection as _core_connection


@dataclass(frozen=True)
class MigrationSettings:
    """What ``migrate`` commands read from a config file: its ``migration:`` block and DSN."""

    migration: MigrationConfig
    database_url: str | None


def migration_settings(config: Path) -> MigrationSettings | None:
    """The ``migration:`` settings of the file ``config`` names, wherever it lives.

    ``None`` when the file does not exist: the defaults apply. An invalid block is
    ``ConfigurationError`` ``CONFIG_002`` (exit 5), read through
    :func:`~confiture.config.environment.migration_block`. Only the block is
    validated, so a minimal or legacy (``database:`` block, no ``include_dirs``) file
    still works.
    """
    if not config.exists():
        return None
    data = _core_connection.load_config(config) or {}
    migration = migration_block(data, config)
    try:
        database_url: str | None = _core_connection.dsn_from_config(data)
    # Reason: a config without a usable DSN is 'no URL' for these settings, whatever the cause
    except Exception:
        database_url = None
    return MigrationSettings(migration=migration, database_url=database_url)


def _effective_rebuild_threshold(explicit: int | None, config: Path) -> int:
    """``--rebuild-threshold``, else ``migration.rebuild_threshold`` from the config."""
    if explicit is not None:
        return explicit
    settings = migration_settings(config)
    return (settings.migration if settings else migration_block({}, config)).rebuild_threshold
