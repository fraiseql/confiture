"""Migration executor — public re-exports.

Detailed implementation lives in confiture.core._migrator.*

This module is the public face only — it holds no patch seams. Tests and
embedders inject through ``MigratorSession(connection_factory=..., migration_loader=...)``
or the class-level ``MigratorSession.default_*`` attributes.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    discover_migration_files,
    find_duplicate_migration_versions,
    parse_migration_filename,
)
from confiture.core._migrator.engine import Migrator
from confiture.core._migrator.events import UpEvent, UpObserver
from confiture.core._migrator.session import MigratorSession

# Names the session resolves through this module at call time. Tests patch
# either ``confiture.core.migrator.<name>`` (this namespace) or the defining
# module's attribute; the two function wrappers below honour both.
from confiture.core.locking import LockConfig, MigrationLock
from confiture.exceptions import SchemaError

__all__ = [
    "LockConfig",
    "MigrationLock",
    "Migrator",
    "MigratorSession",
    "UpEvent",
    "UpObserver",
    "_version_from_migration_filename",
    "discover_migration_files",
    "find_duplicate_migration_versions",
    "parse_migration_filename",
    "replay_migrations",
]


def replay_migrations(
    database_url: str, migrations_dir: Path, migration_table: str | None = None
) -> None:
    """``migrate up`` every migration in *migrations_dir* against *database_url*.

    What ``ExpectedSchemaDB.from_base_plus_migrations`` is handed to build the
    schema a repository's migrations produce.

    Raises:
        SchemaError: A migration failed to apply.
    """
    session = MigratorSession(
        config=None,
        migrations_dir=migrations_dir,
        database_url_override=database_url,
        migration_table_override=migration_table,
    )
    with session:
        result = session.up()
    if not result.success:
        raise SchemaError(
            f"Migration replay into the scratch database failed: {result.errors}",
            resolution_hint="Fix the failing migration, then retry the drift check.",
        )
