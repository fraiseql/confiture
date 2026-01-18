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
    SchemaChange,
    SchemaSnapshot,
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
from confiture.testing.sandbox import MigrationSandbox

__all__ = [
    # Migration sandbox (context manager for testing)
    "MigrationSandbox",
    # Migration loader (most commonly used)
    "load_migration",
    "find_migration_by_version",
    "MigrationNotFoundError",
    "MigrationLoadError",
    # Test fixtures
    "SchemaSnapshotter",
    "DataValidator",
    "MigrationRunner",
    # Fixture data classes
    "DataBaseline",
    "SchemaSnapshot",
    "TableSchema",
    "ColumnInfo",
    "ConstraintInfo",
    "IndexInfo",
    "ForeignKeyInfo",
    "SchemaChange",
    # Mutation testing
    "Mutation",
    "MutationRegistry",
    "MutationTestRunner",
    "MutationRunner",  # Alias for backwards compatibility
    "MutationReport",
    "MutationMetrics",
    "MutationSeverity",
    "MutationCategory",
    # Performance testing
    "MigrationPerformanceProfiler",
    "PerformanceProfile",
    "PerformanceOptimizationReport",
]
