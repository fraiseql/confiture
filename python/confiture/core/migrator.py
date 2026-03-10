"""Migration executor — public re-exports.

Detailed implementation lives in confiture.core._migrator.*
"""

from confiture.core._migrator.discovery import (
    _version_from_migration_filename,
    find_duplicate_migration_versions,
)
from confiture.core._migrator.engine import Migrator
from confiture.core._migrator.session import MigratorSession

# Re-export names that tests patch via this module's namespace.
# These must be present here so that patch("confiture.core.migrator.<name>")
# resolves correctly.  The session module looks them up through this module
# at call time (not at import time) to respect test patches.
from confiture.core.connection import create_connection, load_migration_class
from confiture.core.locking import LockConfig, MigrationLock

__all__ = [
    "Migrator",
    "MigratorSession",
    "_version_from_migration_filename",
    "find_duplicate_migration_versions",
    "create_connection",
    "load_migration_class",
    "LockConfig",
    "MigrationLock",
]
