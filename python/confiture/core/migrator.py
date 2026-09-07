"""Migration executor — public re-exports.

Detailed implementation lives in confiture.core._migrator.*

This module is the public face only — it holds no patch seams. Tests and
embedders inject through ``MigratorSession(connection_factory=..., migration_loader=...)``
or the class-level ``MigratorSession.default_*`` attributes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
]
