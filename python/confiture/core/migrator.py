"""Migration executor — public re-exports.

Detailed implementation lives in confiture.core._migrator.*
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import Connection

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)
from confiture.core._migrator.engine import Migrator
from confiture.core._migrator.events import UpEvent, UpObserver
from confiture.core._migrator.session import MigratorSession

# Names the session resolves through this module at call time. Tests patch
# either ``confiture.core.migrator.<name>`` (this namespace) or the defining
# module's attribute; the two function wrappers below honour both.
from confiture.core.locking import LockConfig, MigrationLock


def create_connection(config: Any) -> Connection:
    """Open a connection — resolved through :mod:`confiture.core.connection` at call time."""
    from confiture.core import connection as _connection

    return _connection.create_connection(config)


def load_migration_class(migration_file: Path) -> type:
    """Load a migration class — resolved through :mod:`confiture.core.connection` at call time."""
    from confiture.core import connection as _connection

    return _connection.load_migration_class(migration_file)


__all__ = [
    "UpEvent",
    "UpObserver",
    "Migrator",
    "MigratorSession",
    "_version_from_migration_filename",
    "find_duplicate_migration_versions",
    "create_connection",
    "load_migration_class",
    "LockConfig",
    "MigrationLock",
]
