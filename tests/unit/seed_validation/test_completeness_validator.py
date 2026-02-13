"""Tests for CompletenessValidator - checking required tables are seeded."""

from confiture.core.seed_validation.completeness_validator import (
    CompletenessValidator,
)


class TestBasicCompletenessValidation:
    """Test basic table completeness validation."""

    def test_detects_missing_required_table(self) -> None:
        """Test detecting when a required table is not seeded."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {"required": True},
            "roles": {"required": True},  # Missing!
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].table == "roles"
        assert violations[0].violation_type == "MISSING_REQUIRED_TABLE"

    def test_allows_all_required_tables_present(self) -> None:
        """Test that all required tables present passes validation."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1", "email": "alice@example.com"}],
            "roles": [{"id": "1", "name": "admin"}],
        }
        schema_context = {
            "users": {"required": True},
            "roles": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_allows_optional_tables_missing(self) -> None:
        """Test that optional tables can be missing."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1", "email": "alice@example.com"}],
        }
        schema_context = {
            "users": {"required": True},
            "audit_logs": {"required": False},  # Optional, OK to miss
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_empty_required_table(self) -> None:
        """Test detecting when a required table is empty."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1", "email": "alice@example.com"}],
            "roles": [],  # Empty required table!
        }
        schema_context = {
            "users": {"required": True},
            "roles": {"required": True, "min_rows": 1},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].table == "roles"
        assert violations[0].violation_type == "TABLE_TOO_SMALL"


class TestTableMinimumRowRequirements:
    """Test minimum row requirements for tables."""

    def test_detects_insufficient_rows(self) -> None:
        """Test detecting when table has fewer rows than required."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {"required": True, "min_rows": 5},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].violation_type == "TABLE_TOO_SMALL"
        assert violations[0].expected_count == 5
        assert violations[0].actual_count == 1

    def test_allows_sufficient_rows(self) -> None:
        """Test that tables with sufficient rows pass validation."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
                {"id": "3", "email": "charlie@example.com"},
            ]
        }
        schema_context = {
            "users": {"required": True, "min_rows": 3},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_allows_more_rows_than_required(self) -> None:
        """Test that having more rows than minimum is OK."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
                {"id": "3", "email": "charlie@example.com"},
                {"id": "4", "email": "diana@example.com"},
            ]
        }
        schema_context = {
            "users": {"required": True, "min_rows": 3},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0


class TestMultipleDependencies:
    """Test validation with multiple table dependencies."""

    def test_detects_multiple_missing_tables(self) -> None:
        """Test detecting multiple missing required tables."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1"}],
        }
        schema_context = {
            "users": {"required": True},
            "roles": {"required": True},
            "permissions": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 2
        tables = {v.table for v in violations}
        assert tables == {"roles", "permissions"}

    def test_detects_mixed_completeness_issues(self) -> None:
        """Test detecting multiple types of completeness violations."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [
                {"id": "1"},
                {"id": "2"},
            ],
            "roles": [],  # Empty
        }
        schema_context = {
            "users": {"required": True, "min_rows": 5},
            "roles": {"required": True, "min_rows": 1},
            "permissions": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 3
        violation_types = {v.violation_type for v in violations}
        assert "TABLE_TOO_SMALL" in violation_types
        assert "MISSING_REQUIRED_TABLE" in violation_types


class TestCompletenessEdgeCases:
    """Test edge cases in completeness validation."""

    def test_handles_no_required_tables(self) -> None:
        """Test when no tables are marked as required."""
        validator = CompletenessValidator()
        seed_data = {
            "audit_logs": [{"id": "1"}],
        }
        schema_context = {
            "users": {"required": False},
            "roles": {"required": False},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_empty_schema_context(self) -> None:
        """Test when schema context has no tables."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1"}],
        }
        schema_context = {}

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_empty_seed_data(self) -> None:
        """Test when seed data is empty."""
        validator = CompletenessValidator()
        seed_data = {}
        schema_context = {
            "users": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].violation_type == "MISSING_REQUIRED_TABLE"

    def test_ignores_tables_not_in_schema(self) -> None:
        """Test that extra tables in seed data don't cause issues."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1"}],
            "extra_table": [{"id": "1"}],  # Not in schema
        }
        schema_context = {
            "users": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_null_min_rows(self) -> None:
        """Test handling when min_rows is not specified."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [],  # Empty, but no min_rows requirement
        }
        schema_context = {
            "users": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        # Should pass - only missing table is a violation, not empty table without min_rows
        assert len(violations) == 0


class TestViolationStructure:
    """Test the structure of CompletenessViolation objects."""

    def test_violation_has_all_fields(self) -> None:
        """Test that violation contains all required fields."""
        validator = CompletenessValidator()
        seed_data = {}
        schema_context = {
            "users": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        violation = violations[0]
        assert hasattr(violation, "table")
        assert hasattr(violation, "violation_type")
        assert hasattr(violation, "message")
        assert hasattr(violation, "severity")

    def test_missing_table_violation_message(self) -> None:
        """Test message for missing table violation."""
        validator = CompletenessValidator()
        seed_data = {}
        schema_context = {
            "users": {"required": True},
        }

        violations = validator.validate(seed_data, schema_context)

        message = violations[0].message
        assert "users" in message.lower()
        assert "missing" in message.lower() or "required" in message.lower()

    def test_table_too_small_violation_includes_counts(self) -> None:
        """Test that table_too_small violation includes row counts."""
        validator = CompletenessValidator()
        seed_data = {
            "users": [{"id": "1"}],
        }
        schema_context = {
            "users": {"required": True, "min_rows": 5},
        }

        violations = validator.validate(seed_data, schema_context)

        violation = violations[0]
        assert hasattr(violation, "expected_count")
        assert hasattr(violation, "actual_count")
        assert violation.expected_count == 5
        assert violation.actual_count == 1
