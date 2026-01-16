"""Phase 6 Performance Profiling System.

Provides:
- Query profiler with observable overhead tracking
- Statistical baseline management with confidence intervals
- Regression detection
"""
from __future__ import annotations


from .baseline_manager import (
    BaselineStorage,
    InMemoryBaselineStorage,
    IssueSeverity,
    PerformanceBaseline,
    PerformanceBaselineManager,
    RegressionResult,
)
from .query_profiler import ProfilingMetadata, QueryProfile, QueryProfiler

# Backward compatibility alias
BaselineManager = PerformanceBaselineManager

__all__ = [
    # Query Profiling
    "QueryProfiler",
    "QueryProfile",
    "ProfilingMetadata",
    # Baseline Management
    "PerformanceBaselineManager",
    "BaselineManager",  # Alias for backward compatibility
    "PerformanceBaseline",
    "BaselineStorage",
    "InMemoryBaselineStorage",
    "RegressionResult",
    "IssueSeverity",
]
