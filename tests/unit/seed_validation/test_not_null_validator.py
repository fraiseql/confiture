"""Tests for NotNullValidator - verifying required columns have values."""

from confiture.core.seed_validation.not_null_validator import (
    NotNullValidator,
)


class TestBasicNotNullValidation:
    """Test basic NOT NULL constraint validation."""

    def test_detects_null_in_required_column(self) -> None:
        """Test detecting NULL value in NOT NULL column."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": None},  # NULL in required column!
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].table == "users"
        assert violations[0].column == "email"
        assert violations[0].violation_type == "NULL_IN_REQUIRED_COLUMN"

    def test_allows_values_in_required_columns(self) -> None:
        """Test that values in required columns pass validation."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com", "name": "Alice"},
                {"id": "2", "email": "bob@example.com", "name": "Bob"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                    "name": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_allows_null_in_optional_columns(self) -> None:
        """Test that NULL values in optional columns are allowed."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com", "phone": None},
                {"id": "2", "email": "bob@example.com", "phone": "555-1234"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                    "phone": {"required": False},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_multiple_nulls_in_required_column(self) -> None:
        """Test detecting multiple NULL values in required column."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": None},
                {"id": "2", "email": None},
                {"id": "3", "email": "charlie@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Should report violations for each NULL
        assert len(violations) == 2


class TestMultipleRequiredColumns:
    """Test multiple required columns in a table."""

    def test_detects_nulls_in_multiple_required_columns(self) -> None:
        """Test detecting NULLs in multiple required columns."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com", "name": "Alice"},
                {"id": "2", "email": None, "name": None},  # Both NULL!
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                    "name": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 2
        columns = {v.column for v in violations}
        assert columns == {"email", "name"}

    def test_validates_mixed_required_and_optional(self) -> None:
        """Test validation with mix of required and optional columns."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {
                    "id": "1",
                    "email": "alice@example.com",
                    "name": "Alice",
                    "phone": None,
                    "bio": None,
                },
                {
                    "id": "2",
                    "email": None,
                    "name": "Bob",
                    "phone": "555-1234",
                    "bio": "Developer",
                },
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                    "name": {"required": True},
                    "phone": {"required": False},
                    "bio": {"required": False},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Should only report violations for required columns with NULL
        assert len(violations) == 1
        assert violations[0].column == "email"


class TestNotNullEdgeCases:
    """Test edge cases in NOT NULL validation."""

    def test_handles_empty_string_as_value(self) -> None:
        """Test that empty string is treated as a value, not NULL."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": ""},  # Empty string, not NULL
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Empty string is a valid value
        assert len(violations) == 0

    def test_handles_zero_as_value(self) -> None:
        """Test that zero is treated as a value, not NULL."""
        validator = NotNullValidator()
        seed_data = {
            "products": [
                {"id": "1", "quantity": 0},  # Zero, not NULL
            ]
        }
        schema_context = {
            "products": {
                "columns": {
                    "quantity": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_false_as_value(self) -> None:
        """Test that false is treated as a value, not NULL."""
        validator = NotNullValidator()
        seed_data = {
            "settings": [
                {"id": "1", "enabled": False},  # False, not NULL
            ]
        }
        schema_context = {
            "settings": {
                "columns": {
                    "enabled": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_uuid_values(self) -> None:
        """Test NOT NULL validation with UUID values."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "01234567-89ab-cdef-0123-456789abcdef"},
                {"id": None},  # NULL UUID
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "id": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].column == "id"

    def test_handles_empty_table(self) -> None:
        """Test NOT NULL validation with empty table."""
        validator = NotNullValidator()
        seed_data = {"users": []}
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_table_not_in_seed_data(self) -> None:
        """Test NOT NULL validation when table not in seed data."""
        validator = NotNullValidator()
        seed_data = {"other_table": [{"id": "1"}]}
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_missing_column_in_row(self) -> None:
        """Test NOT NULL validation when column is missing from row dict."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2"},  # email column missing
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Missing column should be treated as NULL
        assert len(violations) == 1


class TestViolationStructure:
    """Test the structure of NotNullViolation objects."""

    def test_violation_has_all_fields(self) -> None:
        """Test that violation contains all required fields."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": None},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        violation = violations[0]
        assert hasattr(violation, "table")
        assert hasattr(violation, "column")
        assert hasattr(violation, "row_index")
        assert hasattr(violation, "violation_type")
        assert hasattr(violation, "message")
        assert hasattr(violation, "severity")

    def test_violation_message_is_descriptive(self) -> None:
        """Test that violation message is human-readable."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": None},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        message = violations[0].message
        assert "users" in message.lower()
        assert "email" in message.lower()
        assert "null" in message.lower() or "required" in message.lower()

    def test_violation_includes_row_index(self) -> None:
        """Test that violation reports which row has the NULL."""
        validator = NotNullValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": None},
                {"id": "3", "email": "charlie@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"required": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Violation should be for row index 1 (second row)
        assert violations[0].row_index == 1
