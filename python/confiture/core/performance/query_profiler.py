"""Query profiler with observable overhead tracking - Phase 6."""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

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
        connection: Any | None = None,
    ) -> tuple[QueryProfile | None, ProfilingMetadata]:
        """Profile query with overhead tracking.

        Supports two modes:
        1. Real profiling: If connection is provided, executes EXPLAIN ANALYZE
        2. Simulated profiling: Falls back to simulation if no connection

        Args:
            query: SQL query to profile
            params: Query parameters (for parameterized queries)
            connection: Optional psycopg Connection object for real profiling

        Returns:
            Tuple of (QueryProfile, ProfilingMetadata)
        """
        import random

        self.query_count += 1
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        if random.random() > self.sampling_rate:
            # Sampling: skip profiling
            return None, self._simulate_profile(query_hash)

        # Profile the query
        if connection:
            return await self._profile_with_database(
                query, params, query_hash, connection
            )
        else:
            # Fall back to simulation
            return await self._simulate_profile_async(query, query_hash)

    async def _profile_with_database(
        self,
        query: str,
        params: tuple,
        query_hash: str,
        connection: Any,
    ) -> tuple[QueryProfile, ProfilingMetadata]:
        """Profile query using real database connection (psycopg)."""
        profiling_start = time.perf_counter()
        skipped_reasons = []

        try:
            # Execute query and capture timing
            query_start = time.perf_counter()
            result = connection.execute(query, params)
            rows = result.fetchall() if hasattr(result, "fetchall") else []
            query_duration = time.perf_counter() - query_start

            # Get EXPLAIN ANALYZE plan
            plan_start = time.perf_counter()
            explain_query = f"EXPLAIN (ANALYZE, BUFFERS) {query}"
            try:
                explain_result = connection.execute(explain_query, params)
                plan_lines = [row[0] for row in explain_result.fetchall()]
                plan = "\n".join(plan_lines)
            except Exception as e:
                logger.warning(f"Could not analyze query plan: {e}")
                plan = None
                skipped_reasons.append("EXPLAIN ANALYZE failed")

            plan_duration = time.perf_counter() - plan_start

        except Exception as e:
            logger.error(f"Error profiling query: {e}")
            return None, ProfilingMetadata(
                total_queries=1,
                profiled_queries=0,
                sampling_rate=self.sampling_rate,
                profiling_overhead_ms=0,
                query_time_without_profiling_ms=0,
                profiling_overhead_percent=0.0,
                confidence_level=0.0,
                is_deterministic=False,
                skipped_analysis_reasons=[f"Error: {str(e)}"],
            )

        profiling_overhead = time.perf_counter() - profiling_start - query_duration
        profiling_overhead_percent = (
            (profiling_overhead / query_duration * 100) if query_duration > 0 else 0
        )

        # Skip expensive analysis if overhead exceeds target
        if profiling_overhead_percent > self.target_overhead_percent:
            logger.warning(
                f"Profiling overhead {profiling_overhead_percent:.1f}% exceeds "
                f"target {self.target_overhead_percent}%"
            )
            skipped_reasons.append(
                f"Overhead {profiling_overhead_percent:.1f}% > {self.target_overhead_percent}%"
            )

        # Parse plan for characteristics
        plan_text = plan or ""
        has_sequential_scans = "Seq Scan" in plan_text
        has_sorts = "Sort" in plan_text

        profile = QueryProfile(
            query_hash=query_hash,
            query_text=query,
            execution_count=1,
            total_duration_ms=int(query_duration * 1000),
            avg_duration_ms=query_duration * 1000,
            min_duration_ms=int(query_duration * 1000),
            max_duration_ms=int(query_duration * 1000),
            has_sequential_scans=has_sequential_scans,
            has_sorts=has_sorts,
            estimated_rows=0,  # Would need to parse EXPLAIN for this
            actual_rows=len(rows),
            plan_quality_estimate=0.95,  # Real profiling confidence
        )

        metadata = ProfilingMetadata(
            total_queries=1,
            profiled_queries=1,
            sampling_rate=self.sampling_rate,
            profiling_overhead_ms=int(profiling_overhead * 1000),
            query_time_without_profiling_ms=int(query_duration * 1000),
            profiling_overhead_percent=profiling_overhead_percent,
            confidence_level=0.95,  # High confidence for real execution
            is_deterministic=self.sampling_rate == 1.0,
            skipped_analysis_reasons=skipped_reasons,
        )

        self.profiles[query_hash] = profile
        self.profiling_metadata[query_hash] = metadata

        return profile, metadata

    async def _simulate_profile_async(
        self, query: str, query_hash: str
    ) -> tuple[QueryProfile, ProfilingMetadata]:
        """Simulate query profiling (async wrapper)."""
        profile, metadata = self._simulate_profile_sync(query, query_hash)
        return profile, metadata

    def _simulate_profile_sync(
        self, query: str, query_hash: str
    ) -> tuple[QueryProfile, ProfilingMetadata]:
        """Simulate query profiling without database connection."""
        query_start = time.perf_counter()
        # Simulated execution
        result = []
        query_duration = time.perf_counter() - query_start

        # Simulated EXPLAIN ANALYZE
        plan = "Seq Scan on table (cost=0.00..100.00)"
        profiling_overhead = query_duration * 0.01  # Simulate 1% overhead
        profiling_overhead_percent = 1.0

        profile = QueryProfile(
            query_hash=query_hash,
            query_text=query,
            execution_count=1,
            total_duration_ms=int(query_duration * 1000),
            avg_duration_ms=query_duration * 1000,
            min_duration_ms=int(query_duration * 1000),
            max_duration_ms=int(query_duration * 1000),
            has_sequential_scans="Seq Scan" in plan,
            has_sorts="Sort" in plan,
            estimated_rows=0,
            actual_rows=len(result),
            plan_quality_estimate=0.8,  # Lower confidence for simulation
        )

        metadata = ProfilingMetadata(
            total_queries=1,
            profiled_queries=1,
            sampling_rate=self.sampling_rate,
            profiling_overhead_ms=int(profiling_overhead * 1000),
            query_time_without_profiling_ms=int(query_duration * 1000),
            profiling_overhead_percent=profiling_overhead_percent,
            confidence_level=0.8,  # Lower confidence for simulation
            is_deterministic=self.sampling_rate == 1.0,
            skipped_analysis_reasons=["Using simulated profiling (no database connection)"],
        )

        self.profiles[query_hash] = profile
        self.profiling_metadata[query_hash] = metadata

        return profile, metadata

    def _simulate_profile(self, query_hash: str) -> ProfilingMetadata:
        """Simulate skipped profiling due to sampling."""
        start = time.perf_counter()
        # Simulated query execution
        duration = time.perf_counter() - start

        return ProfilingMetadata(
            total_queries=1,
            profiled_queries=0,
            sampling_rate=self.sampling_rate,
            profiling_overhead_ms=0,
            query_time_without_profiling_ms=int(duration * 1000),
            profiling_overhead_percent=0.0,
            confidence_level=self.sampling_rate,
            is_deterministic=self.sampling_rate == 1.0,
            skipped_analysis_reasons=["Sampling (profiling skipped)"],
        )

    def get_profile(self, query_hash: str) -> QueryProfile | None:
        """Get profile for a query."""
        return self.profiles.get(query_hash)

    def get_metadata(self, query_hash: str) -> ProfilingMetadata | None:
        """Get metadata for a query."""
        return self.profiling_metadata.get(query_hash)

    def get_all_profiles(self) -> list[QueryProfile]:
        """Get all profiles."""
        return list(self.profiles.values())
