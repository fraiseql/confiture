"""Environment-file settings the migrate commands read (`migration:` block, DSN).

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _MigrationSettings:
    """What ``migrate`` commands read from an environment file: its ``migration:`` block and DSN."""

    migration: Any  # MigrationConfig
    database_url: str | None


def _load_environment_if_present(config: Path) -> _MigrationSettings | None:
    """The ``migration:`` settings behind ``db/environments/<name>.yaml``, or None if absent.

    Absence is not an error — defaults apply. An invalid ``migration:`` block *is*
    (``ConfigurationError`` ``CONFIG_002``, exit 5) instead of being swallowed into
    "defaults apply", which made a malformed file a silently non-strict run.
    Only the block these commands read is validated, so a minimal or legacy
    (``database:`` block, no ``include_dirs``) file still works.
    """
    if not (
        config.parent.name == "environments"
        and config.parent.parent.name == "db"
        and config.exists()
    ):
        return None
    from pydantic import ValidationError as _PydanticValidationError

    from confiture.config.environment import MigrationConfig
    from confiture.core.connection import dsn_from_config, load_config
    from confiture.exceptions import ConfigurationError

    data = load_config(config) or {}
    if not isinstance(data, dict):
        # An already-built Environment (tests patch load_config to return one).
        return _MigrationSettings(
            migration=getattr(data, "migration", MigrationConfig()),
            database_url=getattr(data, "database_url", None),
        )
    try:
        migration = MigrationConfig.model_validate(data.get("migration") or {})
    except _PydanticValidationError as e:
        raise ConfigurationError(
            f"Invalid `migration:` settings in {config}: {e}",
            error_code="CONFIG_002",
            context={"file_path": str(config)},
            resolution_hint=f"Fix the `migration:` block in {config}.",
        ) from e
    try:
        database_url: str | None = dsn_from_config(data)
    except Exception:  # noqa: BLE001 — a file with no DSN at all still yields its settings
        database_url = None
    return _MigrationSettings(migration=migration, database_url=database_url)


def _effective_rebuild_threshold(explicit: int | None, config: Path) -> int:
    """``--rebuild-threshold``, else ``migration.rebuild_threshold`` from the config, else 5."""
    if explicit is not None:
        return explicit
    env = _load_environment_if_present(config)
    if env is not None:
        return int(env.migration.rebuild_threshold)
    if config.exists():
        from confiture.core.connection import load_config

        data = load_config(config) or {}
        value = (data.get("migration") or {}).get("rebuild_threshold")
        if value is not None:
            return int(value)
    return 5
