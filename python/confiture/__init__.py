"""Confiture: PostgreSQL migrations, sweetly done 🍓

Confiture is a modern PostgreSQL migration tool with a build-from-scratch
philosophy and 4 migration strategies.

Example:
    >>> from confiture import __version__
    >>> print(__version__)
    0.6.2

Library API example::

    from confiture import Migrator

    with Migrator.from_config("db/environments/prod.yaml") as m:
        status = m.status()
        if status.has_pending:
            result = m.up()
"""

from typing import Any

from confiture.core.linting import SchemaLinter
from confiture.exceptions import ExternalGeneratorError

__version__ = "0.6.3"
__author__ = "Lionel Hamayon"
__email__ = "lionel.hamayon@evolution-digitale.fr"

__all__ = [
    "__version__",
    "__author__",
    "__email__",
    # Core classes
    "Migrator",
    "MigratorSession",
    "Environment",
    "SchemaBuilder",
    "SchemaLinter",
    "SchemaSnapshotGenerator",
    "BaselineDetector",
    # Exceptions
    "ExternalGeneratorError",
    # Result models
    "StatusResult",
    "MigrationInfo",
    "MigrateUpResult",
    "MigrateDownResult",
    "MigrateReinitResult",
    "MigrationApplied",
]


def __getattr__(name: str) -> Any:
    """Lazy imports to avoid circular dependency issues at module load time."""
    if name == "SchemaBuilder":
        from confiture.core.builder import SchemaBuilder

        return SchemaBuilder
    if name == "Migrator":
        from confiture.core.migrator import Migrator

        return Migrator
    if name == "MigratorSession":
        from confiture.core.migrator import MigratorSession

        return MigratorSession
    if name == "Environment":
        from confiture.config.environment import Environment

        return Environment
    if name == "SchemaSnapshotGenerator":
        from confiture.core.schema_snapshot import SchemaSnapshotGenerator

        return SchemaSnapshotGenerator
    if name == "BaselineDetector":
        from confiture.core.baseline_detector import BaselineDetector

        return BaselineDetector
    if name == "StatusResult":
        from confiture.models.results import StatusResult

        return StatusResult
    if name == "MigrationInfo":
        from confiture.models.results import MigrationInfo

        return MigrationInfo
    if name == "MigrateUpResult":
        from confiture.models.results import MigrateUpResult

        return MigrateUpResult
    if name == "MigrateDownResult":
        from confiture.models.results import MigrateDownResult

        return MigrateDownResult
    if name == "MigrateReinitResult":
        from confiture.models.results import MigrateReinitResult

        return MigrateReinitResult
    if name == "MigrationApplied":
        from confiture.models.results import MigrationApplied

        return MigrationApplied
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
