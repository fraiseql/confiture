"""Confiture Migration Testing Framework.

Comprehensive testing framework for PostgreSQL migrations including:
- Migration loader utility for easy test setup
- Test fixtures (SchemaSnapshotter, DataValidator, MigrationRunner)
- Mutation testing (27 mutations across 4 categories)
- Performance profiling with regression detection
- Load testing with 100k+ row validation
- Advanced scenario testing

Example:
    >>> from confiture.testing import load_migration, SchemaSnapshotter, DataValidator
    >>> Migration003 = load_migration("003_move_catalog_tables")
    >>> # or by version:
    >>> Migration003 = load_migration(version="003")

The names are resolved lazily (PEP 562). ``confiture.testing.pytest_plugin`` is loaded
by pytest through its ``pytest11`` entry point at the start of *every* pytest session
that has confiture installed; importing this package must therefore not pull in the
whole of ``confiture.core`` — that cost every user's test start-up, and it imported
the package before coverage could start recording.
"""

from __future__ import annotations

import importlib
from typing import Any

# public name → (module, attribute)
_LAZY: dict[str, tuple[str, str]] = {
    # Test fixtures
    "DataValidator": ("confiture.testing.fixtures", "DataValidator"),
    "MigrationRunner": ("confiture.testing.fixtures", "MigrationRunner"),
    "SchemaSnapshotter": ("confiture.testing.fixtures", "SchemaSnapshotter"),
    # Fixture data classes
    "DataBaseline": ("confiture.testing.fixtures.data_validator", "DataBaseline"),
    "ColumnInfo": ("confiture.testing.fixtures.schema_snapshotter", "ColumnInfo"),
    "ConstraintInfo": ("confiture.testing.fixtures.schema_snapshotter", "ConstraintInfo"),
    "ForeignKeyInfo": ("confiture.testing.fixtures.schema_snapshotter", "ForeignKeyInfo"),
    "IndexInfo": ("confiture.testing.fixtures.schema_snapshotter", "IndexInfo"),
    "SchemaChange": ("confiture.testing.fixtures.schema_snapshotter", "SchemaChange"),
    "SchemaSnapshot": ("confiture.testing.fixtures.schema_snapshotter", "SchemaSnapshot"),
    "SnapshotChange": ("confiture.testing.fixtures.schema_snapshotter", "SnapshotChange"),
    "TableSchema": ("confiture.testing.fixtures.schema_snapshotter", "TableSchema"),
    # Mutation testing
    "Mutation": ("confiture.testing.frameworks.mutation", "Mutation"),
    "MutationCategory": ("confiture.testing.frameworks.mutation", "MutationCategory"),
    "MutationMetrics": ("confiture.testing.frameworks.mutation", "MutationMetrics"),
    "MutationRegistry": ("confiture.testing.frameworks.mutation", "MutationRegistry"),
    "MutationReport": ("confiture.testing.frameworks.mutation", "MutationReport"),
    "MutationSeverity": ("confiture.testing.frameworks.mutation", "MutationSeverity"),
    "MutationRunner": ("confiture.testing.frameworks.mutation", "MutationRunner"),
    "MutationTestRunner": ("confiture.testing.frameworks.mutation", "MutationRunner"),
    # Performance testing
    "MigrationPerformanceProfiler": (
        "confiture.testing.frameworks.performance",
        "MigrationPerformanceProfiler",
    ),
    "PerformanceOptimizationReport": (
        "confiture.testing.frameworks.performance",
        "PerformanceOptimizationReport",
    ),
    "PerformanceProfile": ("confiture.testing.frameworks.performance", "PerformanceProfile"),
    # Migration loader utility
    "MigrationLoadError": ("confiture.testing.loader", "MigrationLoadError"),
    "MigrationNotFoundError": ("confiture.testing.loader", "MigrationNotFoundError"),
    "find_migration_by_version": ("confiture.testing.loader", "find_migration_by_version"),
    "load_migration": ("confiture.testing.loader", "load_migration"),
    # Migration sandbox (context manager for testing)
    "MigrationSandbox": ("confiture.testing.sandbox", "MigrationSandbox"),
    "PreStateSimulationError": ("confiture.testing.sandbox", "PreStateSimulationError"),
}

__all__ = [
    "ColumnInfo",
    "ConstraintInfo",
    "DataBaseline",
    "DataValidator",
    "ForeignKeyInfo",
    "IndexInfo",
    "MigrationLoadError",
    "MigrationNotFoundError",
    "MigrationPerformanceProfiler",
    "MigrationRunner",
    "MigrationSandbox",
    "Mutation",
    "MutationCategory",
    "MutationMetrics",
    "MutationRegistry",
    "MutationReport",
    "MutationRunner",
    "MutationSeverity",
    "MutationTestRunner",
    "PerformanceOptimizationReport",
    "PerformanceProfile",
    "PreStateSimulationError",
    "SchemaChange",
    "SchemaSnapshot",
    "SchemaSnapshotter",
    "SnapshotChange",
    "TableSchema",
    "find_migration_by_version",
    "load_migration",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module 'confiture.testing' has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module_name), attribute)
    globals()[name] = value  # cache: the next access is a plain attribute lookup
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))
