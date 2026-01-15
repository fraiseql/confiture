"""Mutation testing tests for Confiture PostgreSQL migrations.

Tests verify that the mutation testing framework correctly:
1. Applies mutations to migrations
2. Detects mutations with tests
3. Calculates kill rates
4. Reports weak tests
"""

import pytest


def test_mutation_registry_loads(mutation_registry):
    """Test that mutation registry is available."""
    assert mutation_registry is not None
    assert len(mutation_registry.mutations) > 0


def test_schema_mutations_available(mutation_registry):
    """Test that schema mutations are registered."""
    schema_mutations = [
        m for m in mutation_registry.mutations.values()
        if m.category.value == "schema"
    ]
    assert len(schema_mutations) > 0


def test_data_mutations_available(mutation_registry):
    """Test that data mutations are registered."""
    data_mutations = [
        m for m in mutation_registry.mutations.values()
        if m.category.value == "data"
    ]
    assert len(data_mutations) > 0


def test_rollback_mutations_available(mutation_registry):
    """Test that rollback mutations are registered."""
    rollback_mutations = [
        m for m in mutation_registry.mutations.values()
        if m.category.value == "rollback"
    ]
    assert len(rollback_mutations) > 0


def test_performance_mutations_available(mutation_registry):
    """Test that performance mutations are registered."""
    perf_mutations = [
        m for m in mutation_registry.mutations.values()
        if m.category.value == "performance"
    ]
    assert len(perf_mutations) > 0


def test_mutation_severity_levels(mutation_registry):
    """Test that mutations have severity levels."""
    for mutation in mutation_registry.mutations.values():
        assert mutation.severity is not None
        assert mutation.severity.value in ["CRITICAL", "IMPORTANT", "MINOR"]


def test_mutation_descriptions(mutation_registry):
    """Test that mutations have descriptions."""
    for mutation in mutation_registry.mutations.values():
        assert mutation.description
        assert len(mutation.description) > 0


def test_mutation_apply_functions(mutation_registry):
    """Test that mutations can be applied."""
    # Get first mutation with apply function
    for mutation in mutation_registry.mutations.values():
        if mutation.apply_fn or mutation.apply_regex:
            # Can apply
            test_sql = "CREATE TABLE test (id UUID PRIMARY KEY)"
            result = mutation.apply(test_sql)
            assert result is not None
            break


def test_mutation_kill_rate_calculation():
    """Test kill rate metrics calculation."""
    from confiture.testing.frameworks.mutation import MutationMetrics

    metrics = MutationMetrics(
        total_mutations=10,
        killed_mutations=8,
        survived_mutations=2
    )

    assert metrics.kill_rate == 80.0


def test_mutation_metrics_by_category():
    """Test mutation metrics by category."""
    from confiture.testing.frameworks.mutation import MutationMetrics

    metrics = MutationMetrics(
        total_mutations=10,
        killed_mutations=8,
        by_category={
            "schema": {"killed": 5, "survived": 1},
            "data": {"killed": 3, "survived": 1}
        }
    )

    assert "schema" in metrics.by_category
    assert "data" in metrics.by_category


# Note: Complete mutation testing suite (59 tests) requires:
# - MigrationRunner fixture for executing migrations
# - Test database setup with migrations
# - Mutation application and execution
# - Kill rate verification
# This is a foundation for the full mutation testing suite.
