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
"""

# Fixtures - convenient top-level imports
from confiture.testing.fixtures import (
    DataValidator,
    MigrationRunner,
    SchemaSnapshotter,
)
from confiture.testing.fixtures.data_validator import DataBaseline
from confiture.testing.fixtures.schema_snapshotter import (
    ColumnInfo,
    ConstraintInfo,
    ForeignKeyInfo,
    IndexInfo,
    SchemaChange,  # backward-compat alias for SnapshotChange
    SchemaSnapshot,
    SnapshotChange,  # noqa: F401
    TableSchema,
)

# Mutation testing framework
from confiture.testing.frameworks.mutation import (
    Mutation,
    MutationCategory,
    MutationMetrics,
    MutationRegistry,
    MutationReport,
    MutationSeverity,
)
from confiture.testing.frameworks.mutation import (
    MutationRunner as MutationTestRunner,
)

# Performance testing framework
from confiture.testing.frameworks.performance import (
    MigrationPerformanceProfiler,
    PerformanceOptimizationReport,
    PerformanceProfile,
)

# Migration loader utility
from confiture.testing.loader import (
    MigrationLoadError,
    MigrationNotFoundError,
    find_migration_by_version,
    load_migration,
)

# Migration sandbox
from confiture.testing.sandbox import MigrationSandbox, PreStateSimulationError

__all__ = [
    "ColumnInfo",
    "ConstraintInfo",
    # Fixture data classes
    "DataBaseline",
    "DataValidator",
    "ForeignKeyInfo",
    "IndexInfo",
    "MigrationLoadError",
    "MigrationNotFoundError",
    # Performance testing
    "MigrationPerformanceProfiler",
    "MigrationRunner",
    # Migration sandbox (context manager for testing)
    "MigrationSandbox",
    # Mutation testing
    "Mutation",
    "MutationCategory",
    "MutationMetrics",
    "MutationRegistry",
    "MutationReport",
    "MutationRunner",  # Alias for backwards compatibility
    "MutationSeverity",
    "MutationTestRunner",
    "PerformanceOptimizationReport",
    "PerformanceProfile",
    "PreStateSimulationError",
    "SchemaChange",
    "SchemaSnapshot",
    # Test fixtures
    "SchemaSnapshotter",
    "TableSchema",
    "find_migration_by_version",
    # Migration loader (most commonly used)
    "load_migration",
]
