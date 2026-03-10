"""Confiture: PostgreSQL migrations, sweetly done 🍓

Confiture is a modern PostgreSQL migration tool with a build-from-scratch
philosophy and 4 migration strategies.

Example:
    >>> from confiture import __version__
    >>> print(__version__)
    0.7.2

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

__version__ = "0.7.2"
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
    "ConfiturError",
    "ConfigurationError",
    "MigrationError",
    "SchemaError",
    "SQLError",
    "RollbackError",
    "SeedError",
    "RestoreError",
    "PreconditionError",
    "PreconditionValidationError",
    "ExternalGeneratorError",
    "GrantAccompanimentError",
    "RebuildError",
    "VerifyFileError",
    # Git accompaniment
    "GrantAccompanimentChecker",
    "GrantAccompanimentReport",
    # Migration verification
    "MigrationVerifier",
    "VerifyResult",
    "VerifyAllResult",
    # Introspection layer
    "FunctionIntrospector",
    "FunctionInfo",
    "FunctionParam",
    "FunctionCatalog",
    "TypeMapper",
    "DependencyGraph",
    # Result models
    "MigrationStatus",
    "StatusResult",
    "MigrationInfo",
    "MigrateUpResult",
    "MigrateDownResult",
    "MigrateReinitResult",
    "MigrateRebuildResult",
    "MigrationApplied",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Core
    "SchemaBuilder": ("confiture.core.builder", "SchemaBuilder"),
    "Migrator": ("confiture.core.migrator", "Migrator"),
    "MigratorSession": ("confiture.core.migrator", "MigratorSession"),
    "Environment": ("confiture.config.environment", "Environment"),
    "SchemaSnapshotGenerator": ("confiture.core.schema_snapshot", "SchemaSnapshotGenerator"),
    "BaselineDetector": ("confiture.core.baseline_detector", "BaselineDetector"),
    # Introspection layer
    "FunctionIntrospector": ("confiture.core.introspection.functions", "FunctionIntrospector"),
    "FunctionInfo": ("confiture.models.function_info", "FunctionInfo"),
    "FunctionParam": ("confiture.models.function_info", "FunctionParam"),
    "FunctionCatalog": ("confiture.models.function_info", "FunctionCatalog"),
    "TypeMapper": ("confiture.core.introspection.type_mapping", "TypeMapper"),
    "DependencyGraph": ("confiture.core.introspection.dependency_graph", "DependencyGraph"),
    # Result models
    "MigrationStatus": ("confiture.models.results", "MigrationStatus"),
    "StatusResult": ("confiture.models.results", "StatusResult"),
    "MigrationInfo": ("confiture.models.results", "MigrationInfo"),
    "MigrateUpResult": ("confiture.models.results", "MigrateUpResult"),
    "MigrateDownResult": ("confiture.models.results", "MigrateDownResult"),
    "MigrateReinitResult": ("confiture.models.results", "MigrateReinitResult"),
    "MigrateRebuildResult": ("confiture.models.results", "MigrateRebuildResult"),
    "MigrationApplied": ("confiture.models.results", "MigrationApplied"),
    "VerifyAllResult": ("confiture.models.results", "VerifyAllResult"),
    # Exceptions
    "RebuildError": ("confiture.exceptions", "RebuildError"),
    "GrantAccompanimentError": ("confiture.exceptions", "GrantAccompanimentError"),
    "VerifyFileError": ("confiture.exceptions", "VerifyFileError"),
    "ConfiturError": ("confiture.exceptions", "ConfiturError"),
    "ConfigurationError": ("confiture.exceptions", "ConfigurationError"),
    "MigrationError": ("confiture.exceptions", "MigrationError"),
    "SchemaError": ("confiture.exceptions", "SchemaError"),
    "SQLError": ("confiture.exceptions", "SQLError"),
    "RollbackError": ("confiture.exceptions", "RollbackError"),
    "SeedError": ("confiture.exceptions", "SeedError"),
    "RestoreError": ("confiture.exceptions", "RestoreError"),
    # Preconditions
    "PreconditionError": ("confiture.core.preconditions", "PreconditionError"),
    "PreconditionValidationError": ("confiture.core.preconditions", "PreconditionValidationError"),
    # Grant accompaniment
    "GrantAccompanimentChecker": (
        "confiture.core.grant_accompaniment",
        "GrantAccompanimentChecker",
    ),
    "GrantAccompanimentReport": ("confiture.models.git", "GrantAccompanimentReport"),
    # Migration verification
    "MigrationVerifier": ("confiture.core.migration_verifier", "MigrationVerifier"),
    "VerifyResult": ("confiture.core.migration_verifier", "VerifyResult"),
}


def __getattr__(name: str) -> Any:
    """Lazy imports to avoid circular dependency issues at module load time."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = __import__(module_path, fromlist=[attr_name])
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
