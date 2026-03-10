"""Test that VerifyAllResult.results is properly typed."""

from typing import get_type_hints

from confiture.core.migration_verifier import VerifyResult
from confiture.models.results import VerifyAllResult


def test_verify_all_result_results_typed() -> None:
    """Test that VerifyAllResult.results is typed as list[VerifyResult]."""

    # Get type hints for VerifyAllResult with proper namespace
    # We need to include VerifyResult in the namespace for proper resolution
    import confiture.core.migration_verifier
    import confiture.models.results

    namespace = {
        **vars(confiture.models.results),
        **vars(confiture.core.migration_verifier),
    }

    hints = get_type_hints(VerifyAllResult, globalns=namespace)

    # Check that "results" field is typed
    assert "results" in hints
    results_type = hints["results"]

    # Verify it's a list type
    assert hasattr(results_type, "__origin__"), f"Expected generic type, got {results_type}"
    assert results_type.__origin__ is list

    # Verify it contains VerifyResult
    assert len(results_type.__args__) > 0
    assert results_type.__args__[0] is VerifyResult


def test_verify_all_result_instantiation() -> None:
    """Test that VerifyAllResult can be instantiated with VerifyResult objects."""
    from pathlib import Path

    # Create sample VerifyResult objects
    result1 = VerifyResult(
        version="001",
        name="init",
        verify_file=Path("db/migrations/001_init.verify.sql"),
        status="verified",
        actual_value=10,
    )
    result2 = VerifyResult(
        version="002",
        name="add_users",
        verify_file=Path("db/migrations/002_add_users.verify.sql"),
        status="verified",
        actual_value=5,
    )

    # Create VerifyAllResult with list of VerifyResult
    verify_all = VerifyAllResult(
        results=[result1, result2],
        verified_count=2,
        failed_count=0,
        skipped_count=0,
        total_applied=2,
    )

    assert verify_all.verified_count == 2
    assert len(verify_all.results) == 2
    assert verify_all.results[0] is result1
    assert verify_all.results[1] is result2
