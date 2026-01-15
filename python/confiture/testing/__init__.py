"""Confiture Migration Testing Framework.

Comprehensive testing framework for PostgreSQL migrations including:
- Mutation testing (27 mutations across 4 categories)
- Performance profiling with regression detection
- Load testing with 100k+ row validation
- Advanced scenario testing
"""

from confiture.testing.frameworks.mutation import (
    Mutation,
    MutationRegistry,
    MutationRunner,
    MutationReport,
    MutationMetrics,
    MutationSeverity,
    MutationCategory,
)
from confiture.testing.frameworks.performance import (
    MigrationPerformanceProfiler,
    PerformanceProfile,
    PerformanceOptimizationReport,
)

__all__ = [
    # Mutation testing
    "Mutation",
    "MutationRegistry",
    "MutationRunner",
    "MutationReport",
    "MutationMetrics",
    "MutationSeverity",
    "MutationCategory",
    # Performance testing
    "MigrationPerformanceProfiler",
    "PerformanceProfile",
    "PerformanceOptimizationReport",
]
