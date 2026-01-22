"""Performance benchmarks for multi-agent coordination system.

These tests establish baseline performance metrics for:
- Intent registration at various scales
- Conflict detection complexity
- Database query performance
- CLI response times

The benchmarks help ensure the coordination system performs well
even with many concurrent agents and large numbers of active intents.
"""

from __future__ import annotations

import time
from typing import List

import pytest

from confiture.integrations.pggit.coordination import (
    ConflictDetector,
    Intent,
    IntentRegistry,
    IntentStatus,
    RiskLevel,
)


@pytest.fixture
def benchmark_registry(test_db_connection):
    """Create a fresh IntentRegistry for benchmarking."""
    if test_db_connection is None:
        pytest.skip("PostgreSQL database not available")

    # Drop tables before test to ensure clean state
    with test_db_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_intent_history CASCADE")
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_conflict CASCADE")
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_intent CASCADE")
        test_db_connection.commit()

    registry = IntentRegistry(test_db_connection)
    return registry


def create_sample_intent(
    agent_id: str,
    feature_name: str,
    table_name: str,
    column_name: str = "test_column",
) -> dict:
    """Create sample intent parameters for benchmarking."""
    return {
        "agent_id": agent_id,
        "feature_name": feature_name,
        "schema_changes": [
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"
        ],
        "tables_affected": [table_name],
        "risk_level": RiskLevel.LOW,
    }


class TestIntentRegistrationPerformance:
    """Benchmark intent registration at different scales."""

    def test_single_intent_registration(self, benchmark_registry):
        """Baseline: Register a single intent."""
        start_time = time.perf_counter()

        intent = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users"
        ))

        elapsed = time.perf_counter() - start_time

        assert intent is not None
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ Single intent registration: {elapsed*1000:.2f}ms")

    def test_register_10_intents(self, benchmark_registry):
        """Small team: Register 10 independent intents."""
        start_time = time.perf_counter()

        intents = []
        for i in range(10):
            intent = benchmark_registry.register(**create_sample_intent(
                f"agent_{i}",
                f"feature_{i}",
                f"table_{i}",  # Different tables = no conflicts
            ))
            intents.append(intent)

        elapsed = time.perf_counter() - start_time

        assert len(intents) == 10
        assert elapsed < 1.0  # Should be <1s for 10 intents
        avg_time = elapsed / 10
        print(f"\n✓ 10 intent registrations: {elapsed*1000:.2f}ms total, {avg_time*1000:.2f}ms avg")

    def test_register_100_intents(self, benchmark_registry):
        """Large organization: Register 100 independent intents."""
        start_time = time.perf_counter()

        intents = []
        for i in range(100):
            intent = benchmark_registry.register(**create_sample_intent(
                f"agent_{i}",
                f"feature_{i}",
                f"table_{i}",  # Different tables = no conflicts
            ))
            intents.append(intent)

        elapsed = time.perf_counter() - start_time

        assert len(intents) == 100
        assert elapsed < 10.0  # Should be <10s for 100 intents
        avg_time = elapsed / 100
        print(f"\n✓ 100 intent registrations: {elapsed*1000:.2f}ms total, {avg_time*1000:.2f}ms avg")

    def test_register_1000_intents_stress_test(self, benchmark_registry):
        """Stress test: Register 1,000 intents."""
        start_time = time.perf_counter()

        intents = []
        for i in range(1000):
            intent = benchmark_registry.register(**create_sample_intent(
                f"agent_{i}",
                f"feature_{i}",
                f"table_{i % 100}",  # Reuse tables to create some conflicts
            ))
            intents.append(intent)

        elapsed = time.perf_counter() - start_time

        assert len(intents) == 1000
        # No strict time limit - just measure
        avg_time = elapsed / 1000
        print(f"\n✓ 1,000 intent registrations: {elapsed:.2f}s total, {avg_time*1000:.2f}ms avg")


class TestConflictDetectionPerformance:
    """Benchmark conflict detection at different complexities."""

    def test_simple_conflict_detection(self, benchmark_registry):
        """Simple: 2 intents, same table."""
        # Register first intent
        intent1 = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users", "email_verified"
        ))

        # Benchmark detecting conflicts with second intent
        intent2_params = create_sample_intent(
            "agent_2", "feature_2", "users", "phone_verified"
        )

        start_time = time.perf_counter()
        intent2 = benchmark_registry.register(**intent2_params)
        conflicts = benchmark_registry.get_conflicts(intent2.id)
        elapsed = time.perf_counter() - start_time

        assert len(conflicts) > 0  # Should detect table conflict
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ Simple conflict detection (2 intents): {elapsed*1000:.2f}ms")

    def test_moderate_conflict_detection(self, benchmark_registry):
        """Moderate: 10 intents, overlapping tables."""
        # Register 10 intents on 3 different tables
        for i in range(10):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}",
                f"feature_{i}",
                f"table_{i % 3}",  # 3 tables, so conflicts expected
                f"column_{i}"
            ))

        # Benchmark detecting conflicts with new intent
        new_intent_params = create_sample_intent(
            "agent_new", "feature_new", "table_0", "new_column"
        )

        start_time = time.perf_counter()
        new_intent = benchmark_registry.register(**new_intent_params)
        conflicts = benchmark_registry.get_conflicts(new_intent.id)
        elapsed = time.perf_counter() - start_time

        assert len(conflicts) > 0
        assert elapsed < 0.2  # Should be <200ms with 10 active intents
        print(f"\n✓ Moderate conflict detection (10 intents): {elapsed*1000:.2f}ms, {len(conflicts)} conflicts")

    def test_complex_conflict_detection(self, benchmark_registry):
        """Complex: 100 intents, many overlapping tables."""
        # Register 100 intents on 10 different tables
        for i in range(100):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}",
                f"feature_{i}",
                f"table_{i % 10}",  # 10 tables, lots of conflicts
                f"column_{i}"
            ))

        # Benchmark detecting conflicts with new intent
        new_intent_params = create_sample_intent(
            "agent_new", "feature_new", "table_0", "new_column"
        )

        start_time = time.perf_counter()
        new_intent = benchmark_registry.register(**new_intent_params)
        conflicts = benchmark_registry.get_conflicts(new_intent.id)
        elapsed = time.perf_counter() - start_time

        assert len(conflicts) > 0
        assert elapsed < 1.0  # Should be <1s even with 100 active intents
        print(f"\n✓ Complex conflict detection (100 intents): {elapsed*1000:.2f}ms, {len(conflicts)} conflicts")


class TestDatabaseQueryPerformance:
    """Benchmark database query operations."""

    def test_list_intents_no_filter(self, benchmark_registry):
        """List all intents with no filtering."""
        # Create 50 intents
        for i in range(50):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}", f"feature_{i}", f"table_{i}"
            ))

        # Benchmark listing all
        start_time = time.perf_counter()
        intents = benchmark_registry.list_intents()
        elapsed = time.perf_counter() - start_time

        assert len(intents) == 50
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ List 50 intents (no filter): {elapsed*1000:.2f}ms")

    def test_list_intents_with_status_filter(self, benchmark_registry):
        """List intents with status filter."""
        # Create 50 intents with mixed statuses
        for i in range(50):
            intent = benchmark_registry.register(**create_sample_intent(
                f"agent_{i}", f"feature_{i}", f"table_{i}"
            ))
            if i % 3 == 0:
                benchmark_registry.mark_in_progress(intent.id)
            elif i % 3 == 1:
                benchmark_registry.mark_completed(intent.id)

        # Benchmark filtering by status
        start_time = time.perf_counter()
        in_progress = benchmark_registry.list_intents(status=IntentStatus.IN_PROGRESS)
        elapsed = time.perf_counter() - start_time

        assert len(in_progress) > 0
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ List with status filter (50 total): {elapsed*1000:.2f}ms, {len(in_progress)} results")

    def test_list_intents_with_agent_filter(self, benchmark_registry):
        """List intents with agent ID filter."""
        # Create 50 intents from 5 different agents
        for i in range(50):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i % 5}", f"feature_{i}", f"table_{i}"
            ))

        # Benchmark filtering by agent
        start_time = time.perf_counter()
        agent_intents = benchmark_registry.list_intents(agent_id="agent_0")
        elapsed = time.perf_counter() - start_time

        assert len(agent_intents) == 10  # Should be 10 from agent_0
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ List with agent filter (50 total): {elapsed*1000:.2f}ms, {len(agent_intents)} results")

    def test_get_single_intent(self, benchmark_registry):
        """Get a single intent by ID."""
        intent = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users"
        ))

        # Benchmark retrieval
        start_time = time.perf_counter()
        retrieved = benchmark_registry.get_intent(intent.id)
        elapsed = time.perf_counter() - start_time

        assert retrieved is not None
        assert elapsed < 0.05  # Should be <50ms
        print(f"\n✓ Get single intent by ID: {elapsed*1000:.2f}ms")

    def test_status_update_performance(self, benchmark_registry):
        """Update intent status."""
        intent = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users"
        ))

        # Benchmark status update
        start_time = time.perf_counter()
        benchmark_registry.mark_in_progress(intent.id)
        elapsed = time.perf_counter() - start_time

        assert elapsed < 0.05  # Should be <50ms
        print(f"\n✓ Status update: {elapsed*1000:.2f}ms")

    def test_get_conflicts_for_intent(self, benchmark_registry):
        """Get all conflicts for a specific intent."""
        # Create scenario with conflicts
        for i in range(10):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}", f"feature_{i}", "users", f"column_{i}"
            ))

        # Create intent that conflicts with all
        conflicting_intent = benchmark_registry.register(**create_sample_intent(
            "agent_new", "feature_new", "users", "new_column"
        ))

        # Benchmark getting conflicts
        start_time = time.perf_counter()
        conflicts = benchmark_registry.get_conflicts(conflicting_intent.id)
        elapsed = time.perf_counter() - start_time

        assert len(conflicts) > 0
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ Get conflicts for intent: {elapsed*1000:.2f}ms, {len(conflicts)} conflicts")


class TestCLIResponseTime:
    """Benchmark CLI command response times.

    Note: These test the underlying operations that CLI commands use.
    Actual CLI response time includes additional overhead from Typer,
    Rich formatting, and connection establishment (~50-100ms).
    """

    def test_register_command_response(self, benchmark_registry):
        """Simulate 'confiture coordinate register' operation."""
        start_time = time.perf_counter()

        # This is what the CLI command does internally
        intent = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users"
        ))
        conflicts = benchmark_registry.get_conflicts(intent.id)

        elapsed = time.perf_counter() - start_time

        assert intent is not None
        assert elapsed < 0.15  # Core operation should be <150ms
        print(f"\n✓ Register command (core ops): {elapsed*1000:.2f}ms")

    def test_list_command_response(self, benchmark_registry):
        """Simulate 'confiture coordinate list-intents' operation."""
        # Create 20 intents
        for i in range(20):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}", f"feature_{i}", f"table_{i}"
            ))

        start_time = time.perf_counter()
        intents = benchmark_registry.list_intents()
        elapsed = time.perf_counter() - start_time

        assert len(intents) == 20
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ List command (20 intents): {elapsed*1000:.2f}ms")

    def test_status_command_response(self, benchmark_registry):
        """Simulate 'confiture coordinate status' operation."""
        intent = benchmark_registry.register(**create_sample_intent(
            "agent_1", "feature_1", "users"
        ))

        start_time = time.perf_counter()

        # This is what the CLI command does
        retrieved = benchmark_registry.get_intent(intent.id)
        conflicts = benchmark_registry.get_conflicts(intent.id)

        elapsed = time.perf_counter() - start_time

        assert retrieved is not None
        assert elapsed < 0.1  # Should be <100ms
        print(f"\n✓ Status command (core ops): {elapsed*1000:.2f}ms")

    def test_check_command_response(self, benchmark_registry):
        """Simulate 'confiture coordinate check' operation."""
        # Create 10 existing intents
        for i in range(10):
            benchmark_registry.register(**create_sample_intent(
                f"agent_{i}", f"feature_{i}", "users", f"column_{i}"
            ))

        start_time = time.perf_counter()

        # Check command lists active intents and detects conflicts
        active = benchmark_registry.list_intents(status=IntentStatus.REGISTERED)
        active.extend(benchmark_registry.list_intents(status=IntentStatus.IN_PROGRESS))

        # Create temporary intent for checking
        from confiture.integrations.pggit.coordination import Intent
        from uuid import uuid4
        temp_intent = Intent(
            id=str(uuid4()),
            agent_id="agent_new",
            feature_name="feature_new",
            branch_name="feature/feature_new_001",
            schema_changes=["ALTER TABLE users ADD COLUMN new_col TEXT"],
            tables_affected=["users"],
        )

        # Detect conflicts with all active intents
        detector = benchmark_registry._detector
        all_conflicts = []
        for existing in active:
            conflicts = detector.detect_conflicts(temp_intent, existing)
            all_conflicts.extend(conflicts)

        elapsed = time.perf_counter() - start_time

        assert elapsed < 0.2  # Should be <200ms with 10 active intents
        print(f"\n✓ Check command (10 active intents): {elapsed*1000:.2f}ms, {len(all_conflicts)} conflicts")


class TestScalabilitySummary:
    """Summary benchmark showing system scalability."""

    def test_scalability_summary(self, benchmark_registry):
        """Comprehensive scalability test across different scales."""
        results = {}

        # Test 1: Single intent
        start = time.perf_counter()
        benchmark_registry.register(**create_sample_intent("a1", "f1", "t1"))
        results["1 intent"] = time.perf_counter() - start

        # Test 2: 10 intents
        start = time.perf_counter()
        for i in range(10):
            benchmark_registry.register(**create_sample_intent(
                f"a{i+2}", f"f{i+2}", f"t{i+2}"
            ))
        results["10 intents"] = time.perf_counter() - start

        # Test 3: 50 more intents
        start = time.perf_counter()
        for i in range(50):
            benchmark_registry.register(**create_sample_intent(
                f"a{i+12}", f"f{i+12}", f"t{i+12}"
            ))
        results["50 intents"] = time.perf_counter() - start

        # Test 4: List all (61 total)
        start = time.perf_counter()
        all_intents = benchmark_registry.list_intents()
        results["list 61 intents"] = time.perf_counter() - start

        # Test 5: Conflict detection with all active
        new_intent = benchmark_registry.register(**create_sample_intent(
            "new_agent", "new_feature", "t1", "new_col"  # Conflicts with first
        ))
        start = time.perf_counter()
        conflicts = benchmark_registry.get_conflicts(new_intent.id)
        results["conflict detection (61 active)"] = time.perf_counter() - start

        # Print summary
        print("\n" + "="*60)
        print("SCALABILITY SUMMARY")
        print("="*60)
        for operation, elapsed in results.items():
            print(f"{operation:30s}: {elapsed*1000:6.2f}ms")
        print("="*60)

        # Verify reasonable performance
        assert results["1 intent"] < 0.1
        assert results["list 61 intents"] < 0.15
        assert results["conflict detection (61 active)"] < 0.5
