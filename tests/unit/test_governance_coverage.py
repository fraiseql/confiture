"""Comprehensive tests for data governance pipeline.

Tests the governance system for anonymization workflows including context,
validation, and lifecycle management.
"""

import time

from confiture.core.anonymization.governance import (
    AnonymizationContext,
    GovernancePhase,
    ValidationResult,
)


class TestGovernancePhase:
    """Test GovernancePhase enum."""

    def test_phase_pre_validation(self):
        """Test PRE_VALIDATION phase."""
        assert GovernancePhase.PRE_VALIDATION.value == 1

    def test_phase_before_anonymization(self):
        """Test BEFORE_ANONYMIZATION phase."""
        assert GovernancePhase.BEFORE_ANONYMIZATION.value == 2

    def test_phase_anonymization(self):
        """Test ANONYMIZATION phase."""
        assert GovernancePhase.ANONYMIZATION.value == 3

    def test_phase_post_anonymization(self):
        """Test POST_ANONYMIZATION phase."""
        assert GovernancePhase.POST_ANONYMIZATION.value == 4

    def test_phase_cleanup(self):
        """Test CLEANUP phase."""
        assert GovernancePhase.CLEANUP.value == 5

    def test_all_phases_defined(self):
        """Test all phases are defined."""
        phases = list(GovernancePhase)
        assert len(phases) == 5

    def test_phase_ordering(self):
        """Test phases are in correct order."""
        phases = list(GovernancePhase)
        for i, phase in enumerate(phases):
            assert phase.value == i + 1


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_create_valid_result(self):
        """Test creating valid validation result."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
        )

        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.rows_checked == 0

    def test_create_invalid_result(self):
        """Test creating invalid validation result."""
        errors = ["Type mismatch", "Null value found"]
        result = ValidationResult(
            is_valid=False,
            errors=errors,
            warnings=["Data format unusual"],
        )

        assert result.is_valid is False
        assert result.errors == errors
        assert len(result.warnings) == 1

    def test_validation_with_counts(self):
        """Test validation result with row counts."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            rows_checked=1000,
            null_count=5,
        )

        assert result.rows_checked == 1000
        assert result.null_count == 5

    def test_validation_with_sample_values(self):
        """Test validation result with sample values."""
        samples = ["value1", "value2", "value3"]
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            sample_values=samples,
        )

        assert result.sample_values == samples

    def test_validation_default_sample_values(self):
        """Test that sample_values defaults to empty list."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
        )

        assert result.sample_values == []

    def test_validation_multiple_errors(self):
        """Test validation with multiple errors."""
        errors = [
            "Type validation failed",
            "Null values detected",
            "Format invalid",
            "Range exceeded",
        ]
        result = ValidationResult(
            is_valid=False,
            errors=errors,
            warnings=["Data quality low"],
        )

        assert len(result.errors) == 4
        assert result.is_valid is False

    def test_validation_multiple_warnings(self):
        """Test validation with multiple warnings."""
        warnings = [
            "High null count",
            "Unusual distribution",
            "Missing metadata",
        ]
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=warnings,
        )

        assert len(result.warnings) == 3
        assert result.is_valid is True


class TestAnonymizationContext:
    """Test AnonymizationContext dataclass."""

    def test_create_context_minimal(self):
        """Test creating context with minimal fields."""
        context = AnonymizationContext(
            operation_id="op-001",
            table_name="users",
            column_name="email",
            strategy_name="email_mask",
        )

        assert context.operation_id == "op-001"
        assert context.table_name == "users"
        assert context.column_name == "email"
        assert context.strategy_name == "email_mask"
        assert context.executed_by == "system"

    def test_create_context_full(self):
        """Test creating context with all fields."""
        context = AnonymizationContext(
            operation_id="op-002",
            table_name="customers",
            column_name="phone",
            strategy_name="phone_mask",
            rows_affected=500,
            executed_by="admin@example.com",
            reason="GDPR compliance",
            request_id="TICKET-123",
            department="Legal",
            data_minimization_applied=True,
            retention_days=90,
        )

        assert context.rows_affected == 500
        assert context.executed_by == "admin@example.com"
        assert context.reason == "GDPR compliance"
        assert context.department == "Legal"
        assert context.data_minimization_applied is True
        assert context.retention_days == 90

    def test_context_timing(self):
        """Test context timing fields."""
        context = AnonymizationContext(
            operation_id="op-003",
            table_name="data",
            column_name="col",
            strategy_name="strategy",
        )

        start_time = time.time()
        context.start_time = start_time
        time.sleep(0.01)
        context.end_time = time.time()

        duration = context.end_time - context.start_time
        assert duration > 0
        assert duration < 1  # Should be quick

    def test_context_counts(self):
        """Test context source and target counts."""
        context = AnonymizationContext(
            operation_id="op-004",
            table_name="users",
            column_name="email",
            strategy_name="hash",
            source_count=1000,
            target_count=1000,
        )

        assert context.source_count == 1000
        assert context.target_count == 1000

    def test_context_stats(self):
        """Test context statistics tracking."""
        context = AnonymizationContext(
            operation_id="op-005",
            table_name="data",
            column_name="col",
            strategy_name="strategy",
        )

        context.stats["processed"] = 500
        context.stats["failed"] = 2
        context.stats["skipped"] = 10

        assert context.stats["processed"] == 500
        assert context.stats["failed"] == 2

    def test_context_default_stats(self):
        """Test that stats defaults to empty dict."""
        context = AnonymizationContext(
            operation_id="op-006",
            table_name="table",
            column_name="col",
            strategy_name="strategy",
        )

        assert context.stats == {}
        assert isinstance(context.stats, dict)

    def test_duration_seconds_calculation(self):
        """Test duration_seconds property."""
        context = AnonymizationContext(
            operation_id="op-007",
            table_name="table",
            column_name="col",
            strategy_name="strategy",
        )

        context.start_time = 100.0
        context.end_time = 103.5

        assert context.duration_seconds == 3.5

    def test_context_request_tracking(self):
        """Test context for request tracking."""
        context = AnonymizationContext(
            operation_id="op-008",
            table_name="customers",
            column_name="ssn",
            strategy_name="redact",
            request_id="REQ-GDPR-2024-001",
            department="Compliance",
        )

        assert context.request_id == "REQ-GDPR-2024-001"
        assert context.department == "Compliance"

    def test_context_retention_policy(self):
        """Test context with retention policy."""
        context = AnonymizationContext(
            operation_id="op-009",
            table_name="logs",
            column_name="user_id",
            strategy_name="hash",
            retention_days=180,
        )

        assert context.retention_days == 180

    def test_context_data_minimization(self):
        """Test context with data minimization."""
        context = AnonymizationContext(
            operation_id="op-010",
            table_name="profiles",
            column_name="bio",
            strategy_name="redact",
            data_minimization_applied=True,
        )

        assert context.data_minimization_applied is True

    def test_context_multiple_operations(self):
        """Test multiple contexts with different operations."""
        contexts = [
            AnonymizationContext(
                operation_id=f"op-{i:03d}",
                table_name=f"table_{i}",
                column_name=f"col_{i}",
                strategy_name="strategy",
                rows_affected=i * 100,
            )
            for i in range(1, 6)
        ]

        assert len(contexts) == 5
        for i, ctx in enumerate(contexts):
            assert ctx.rows_affected == (i + 1) * 100


class TestGovernanceIntegration:
    """Integration tests for governance components."""

    def test_validation_to_context_flow(self):
        """Test flow from validation to context."""
        # Create validation result
        validation = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            rows_checked=1000,
            null_count=0,
        )

        # Create context based on validation
        context = AnonymizationContext(
            operation_id="op-flow-001",
            table_name="data",
            column_name="col",
            strategy_name="strategy",
            rows_affected=validation.rows_checked,
        )

        assert validation.is_valid is True
        assert context.rows_affected == validation.rows_checked

    def test_governance_phase_workflow(self):
        """Test workflow through all governance phases."""
        AnonymizationContext(
            operation_id="op-workflow",
            table_name="sensitive_data",
            column_name="pii",
            strategy_name="tokenization",
            rows_affected=5000,
        )

        # Simulate phase progression
        phases = [
            GovernancePhase.PRE_VALIDATION,
            GovernancePhase.BEFORE_ANONYMIZATION,
            GovernancePhase.ANONYMIZATION,
            GovernancePhase.POST_ANONYMIZATION,
            GovernancePhase.CLEANUP,
        ]

        for phase in phases:
            assert phase in GovernancePhase

    def test_context_with_validation_results(self):
        """Test context combined with validation results."""
        validations = [
            ValidationResult(
                is_valid=True,
                errors=[],
                warnings=[],
                rows_checked=1000,
            ),
            ValidationResult(
                is_valid=True,
                errors=[],
                warnings=["High null count"],
                rows_checked=1000,
                null_count=50,
            ),
        ]

        context = AnonymizationContext(
            operation_id="op-combined",
            table_name="users",
            column_name="email",
            strategy_name="mask",
            rows_affected=sum(v.rows_checked for v in validations),
        )

        assert context.rows_affected == 2000
        assert all(v.is_valid for v in validations)

    def test_context_lifecycle_complete(self):
        """Test complete context lifecycle."""
        # Create context
        context = AnonymizationContext(
            operation_id="op-lifecycle",
            table_name="customers",
            column_name="phone",
            strategy_name="phone_mask",
            rows_affected=1000,
            executed_by="compliance@example.com",
            reason="GDPR Right to Erasure",
            request_id="TICKET-GDPR-001",
            department="Legal",
        )

        # Simulate execution
        context.start_time = time.time()
        context.source_count = 1000
        context.stats["processed"] = 1000
        context.stats["failed"] = 0
        context.target_count = 1000
        context.end_time = time.time()

        # Verify complete lifecycle
        assert context.start_time > 0
        assert context.end_time >= context.start_time
        assert context.duration_seconds >= 0
        assert context.source_count == context.target_count
        assert context.stats["processed"] == context.rows_affected

    def test_context_error_scenarios(self):
        """Test context for error scenarios."""
        context = AnonymizationContext(
            operation_id="op-error",
            table_name="data",
            column_name="col",
            strategy_name="strategy",
            rows_affected=1000,
        )

        # Simulate partial failure
        context.source_count = 1000
        context.stats["processed"] = 950
        context.stats["failed"] = 50
        context.target_count = 950

        assert context.stats["failed"] > 0
        assert context.source_count != context.target_count

    def test_multiple_contexts_independence(self):
        """Test that multiple contexts are independent."""
        ctx1 = AnonymizationContext(
            operation_id="op-1",
            table_name="table1",
            column_name="col1",
            strategy_name="strategy",
        )

        ctx2 = AnonymizationContext(
            operation_id="op-2",
            table_name="table2",
            column_name="col2",
            strategy_name="strategy",
        )

        ctx1.stats["value"] = 100
        ctx2.stats["value"] = 200

        assert ctx1.stats["value"] == 100
        assert ctx2.stats["value"] == 200
        assert ctx1.stats is not ctx2.stats

    def test_governance_phase_transitions(self):
        """Test valid governance phase transitions."""
        AnonymizationContext(
            operation_id="op-transitions",
            table_name="data",
            column_name="col",
            strategy_name="strategy",
        )

        # Valid transition sequence
        valid_sequence = [
            GovernancePhase.PRE_VALIDATION,
            GovernancePhase.BEFORE_ANONYMIZATION,
            GovernancePhase.ANONYMIZATION,
            GovernancePhase.POST_ANONYMIZATION,
            GovernancePhase.CLEANUP,
        ]

        for i, phase in enumerate(valid_sequence):
            if i > 0:
                assert phase.value > valid_sequence[i - 1].value
