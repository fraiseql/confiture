"""Query profiler with observable overhead tracking - Phase 6."""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueryProfile:
    """Individual query profile."""

    query_hash: str
    query_text: str
    execution_count: int
    total_duration_ms: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    has_sequential_scans: bool
    has_sorts: bool
    estimated_rows: int
    actual_rows: int
    plan_quality_estimate: float  # 0.0-1.0


@dataclass
class ProfilingMetadata:
    """Metadata about profiling run."""

    total_queries: int
    profiled_queries: int  # Might be sampled
    sampling_rate: float  # 0.0-1.0
    profiling_overhead_ms: int
    query_time_without_profiling_ms: int
    profiling_overhead_percent: float
    confidence_level: float  # 0.0-1.0, lower if sampled
    is_deterministic: bool  # False if sampling
    skipped_analysis_reasons: list[str] = field(default_factory=list)


class QueryProfiler:
    """Profile query performance with overhead tracking."""

    def __init__(
        self,
        target_overhead_percent: float = 5.0,
        sampling_rate: float = 1.0,  # 1.0 = profile all
    ):
        self.target_overhead_percent = target_overhead_percent
        self.sampling_rate = sampling_rate
        self.profiles: dict[str, QueryProfile] = {}
        self.profiling_metadata: dict[str, ProfilingMetadata] = {}
        self.query_count = 0

    async def profile_query(
        self,
        query: str,
        params: tuple = (),
        connection: Optional[Any] = None,
    ) -> tuple[Optional[QueryProfile], ProfilingMetadata]:
        """Profile query with overhead tracking."""
        import random

        self.query_count += 1
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        if random.random() > self.sampling_rate:
            # Sampling: skip profiling
            start = time.perf_counter()
            # Simulated query execution
            duration = time.perf_counter() - start

            return None, ProfilingMetadata(
                total_queries=1,
                profiled_queries=0,
                sampling_rate=self.sampling_rate,
                profiling_overhead_ms=0,
                query_time_without_profiling_ms=int(duration * 1000),
                profiling_overhead_percent=0.0,
                confidence_level=self.sampling_rate,
                is_deterministic=self.sampling_rate == 1.0,
                skipped_analysis_reasons=["Sampling"],
            )

        # Profile the query
        profiling_start = time.perf_counter()

        # Execute query (simulated)
        query_start = time.perf_counter()
        # Simulated execution
        result = []
        query_duration = time.perf_counter() - query_start

        # Get query plan (simulated)
        plan_start = time.perf_counter()
        plan = None
        try:
            # Simulated EXPLAIN ANALYZE
            plan = "Seq Scan on table (cost=0.00..100.00)"
        except Exception as e:
            logger.warning(f"Could not analyze query plan: {e}")

        plan_duration = time.perf_counter() - plan_start

        profiling_overhead = time.perf_counter() - profiling_start - query_duration
        profiling_overhead_percent = (profiling_overhead / query_duration * 100) if query_duration > 0 else 0

        skipped_reasons = []
        # Skip expensive analysis if overhead exceeds target
        if profiling_overhead_percent > self.target_overhead_percent:
            logger.warning(
                f"Profiling overhead {profiling_overhead_percent:.1f}% exceeds "
                f"target {self.target_overhead_percent}%. Skipping detailed analysis."
            )
            skipped_reasons.append(
                f"Overhead {profiling_overhead_percent:.1f}% > "
                f"target {self.target_overhead_percent}%"
            )
            plan = None

        profile = QueryProfile(
            query_hash=query_hash,
            query_text=query,
            execution_count=1,
            total_duration_ms=int(query_duration * 1000),
            avg_duration_ms=query_duration * 1000,
            min_duration_ms=int(query_duration * 1000),
            max_duration_ms=int(query_duration * 1000),
            has_sequential_scans="Seq Scan" in (plan or ""),
            has_sorts="Sort" in (plan or ""),
            estimated_rows=0,
            actual_rows=len(result),
            plan_quality_estimate=1.0,
        )

        metadata = ProfilingMetadata(
            total_queries=1,
            profiled_queries=1,
            sampling_rate=self.sampling_rate,
            profiling_overhead_ms=int(profiling_overhead * 1000),
            query_time_without_profiling_ms=int(query_duration * 1000),
            profiling_overhead_percent=profiling_overhead_percent,
            confidence_level=self.sampling_rate,
            is_deterministic=self.sampling_rate == 1.0,
            skipped_analysis_reasons=skipped_reasons,
        )

        self.profiles[query_hash] = profile
        self.profiling_metadata[query_hash] = metadata

        return profile, metadata

    def get_profile(self, query_hash: str) -> Optional[QueryProfile]:
        """Get profile for a query."""
        return self.profiles.get(query_hash)

    def get_metadata(self, query_hash: str) -> Optional[ProfilingMetadata]:
        """Get metadata for a query."""
        return self.profiling_metadata.get(query_hash)

    def get_all_profiles(self) -> list[QueryProfile]:
        """Get all profiles."""
        return list(self.profiles.values())
