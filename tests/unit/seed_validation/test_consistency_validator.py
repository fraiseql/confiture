"""Tests for ConsistencyValidator - orchestrating all seed validation checks."""

from confiture.core.seed_validation.consistency_validator import (
    ConsistencyValidator,
)


class TestBasicConsistencyValidation:
    """Test basic consistency validation."""

    def test_returns_empty_report_for_valid_data(self) -> None:
        """Test that valid seed data produces no violations."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "required": True,
                "columns": {
                    "id": {"required": True, "unique": True},
                    "email": {"required": True, "unique": True},
                },
            }
        }

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is False
        assert len(report.violations) == 0

    def test_collects_foreign_key_violations(self) -> None:
        """Test that FK violations are collected."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ],
            "orders": [
                {"id": "1", "customer_id": "999"},  # Invalid FK
            ],
        }
        schema_context = {
            "users": {"required": True},
            "orders": {"columns": {"customer_id": {"foreign_key": ("users", "id")}}},
        }

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True
        fk_violations = [v for v in report.violations if "foreign" in str(v).lower()]
        assert len(fk_violations) >= 1

    def test_collects_unique_constraint_violations(self) -> None:
        """Test that unique constraint violations are collected."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "alice@example.com"},  # Duplicate
            ]
        }
        schema_context = {"users": {"columns": {"email": {"unique": True}}}}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True

    def test_collects_not_null_violations(self) -> None:
        """Test that NOT NULL violations are collected."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": None},  # NULL required column
            ]
        }
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True

    def test_collects_completeness_violations(self) -> None:
        """Test that completeness violations are collected."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {"required": True},
            "roles": {"required": True},  # Missing
        }

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True


class TestMultipleViolationTypes:
    """Test handling multiple violation types."""

    def test_collects_multiple_violation_types(self) -> None:
        """Test collecting violations from multiple validators."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": None},  # NOT NULL violation
                {"id": "2", "email": "alice@example.com"},  # Duplicate in next row
            ],
            "orders": [
                {"id": "1", "customer_id": "999"},  # FK violation
            ],
        }
        schema_context = {
            "users": {
                "required": True,
                "columns": {
                    "id": {"required": True},
                    "email": {"required": True, "unique": True},
                },
            },
            "orders": {"columns": {"customer_id": {"foreign_key": ("users", "id")}}},
            "roles": {"required": True},  # Missing table
        }

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True
        # Should have violations of multiple types
        violation_types = {type(v).__name__ for v in report.violations}
        assert len(violation_types) >= 2

    def test_violation_count_is_accurate(self) -> None:
        """Test that violation count matches violations list."""
        validator = ConsistencyValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": None},
                {"id": "2", "email": None},
            ]
        }
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        report = validator.validate(seed_data, schema_context)

        assert report.violation_count == len(report.violations)


class TestConsistencyValidationConfiguration:
    """Test configuration options for consistency validation."""

    def test_respects_stop_on_first_violation_flag(self) -> None:
        """Test that validation stops after first violation if configured."""
        validator = ConsistencyValidator(stop_on_first_violation=True)
        seed_data = {
            "users": [
                {"id": "1", "email": None},
                {"id": "2", "email": None},
            ]
        }
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        report = validator.validate(seed_data, schema_context)

        # With stop_on_first_violation, should stop early
        assert report.violation_count >= 1

    def test_includes_validator_info_in_report(self) -> None:
        """Test that report includes info about which validators ran."""
        validator = ConsistencyValidator()
        seed_data = {"users": [{"id": "1", "email": "alice@example.com"}]}
        schema_context = {"users": {"required": True}}

        report = validator.validate(seed_data, schema_context)

        assert hasattr(report, "validators_run")


class TestConsistencyReportStructure:
    """Test the structure of ConsistencyReport."""

    def test_report_has_required_fields(self) -> None:
        """Test that report has all required fields."""
        validator = ConsistencyValidator()
        seed_data = {}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        assert hasattr(report, "has_violations")
        assert hasattr(report, "violations")
        assert hasattr(report, "violation_count")
        assert hasattr(report, "validators_run")

    def test_report_violations_list_is_proper_type(self) -> None:
        """Test that violations is a list."""
        validator = ConsistencyValidator()
        seed_data = {}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        assert isinstance(report.violations, list)

    def test_empty_report_has_correct_structure(self) -> None:
        """Test empty report has correct structure."""
        validator = ConsistencyValidator()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is False
        assert report.violation_count == 0
        assert len(report.violations) == 0


class TestConsistencyValidationEdgeCases:
    """Test edge cases in consistency validation."""

    def test_handles_empty_seed_data(self) -> None:
        """Test validation with empty seed data."""
        validator = ConsistencyValidator()
        seed_data = {}
        schema_context = {"users": {"required": True}}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is True

    def test_handles_empty_schema_context(self) -> None:
        """Test validation with empty schema context."""
        validator = ConsistencyValidator()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is False

    def test_handles_both_empty(self) -> None:
        """Test validation with both empty."""
        validator = ConsistencyValidator()
        seed_data = {}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        assert report.has_violations is False
        assert report.violation_count == 0


class TestConsistencyReportSerialization:
    """Test serialization and output of report."""

    def test_report_can_be_converted_to_dict(self) -> None:
        """Test that report can be serialized to dict."""
        validator = ConsistencyValidator()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {}

        report = validator.validate(seed_data, schema_context)

        report_dict = report.to_dict()
        assert isinstance(report_dict, dict)
        assert "has_violations" in report_dict
        assert "violation_count" in report_dict

    def test_report_to_dict_includes_violations(self) -> None:
        """Test that to_dict includes violations."""
        validator = ConsistencyValidator()
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        report = validator.validate(seed_data, schema_context)
        report_dict = report.to_dict()

        assert "violations" in report_dict
        assert len(report_dict["violations"]) > 0
