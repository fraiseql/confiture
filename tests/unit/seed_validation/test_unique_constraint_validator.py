"""Tests for UniqueConstraintValidator - detecting duplicate values in UNIQUE columns."""

from confiture.core.seed_validation.unique_constraint_validator import (
    UniqueConstraintValidator,
)


class TestBasicUniqueConstraintValidation:
    """Test basic unique constraint validation."""

    def test_detects_duplicate_in_unique_column(self) -> None:
        """Test detecting duplicate value in UNIQUE column."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
                {"id": "3", "email": "alice@example.com"},  # Duplicate!
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].table == "users"
        assert violations[0].column == "email"
        assert violations[0].value == "alice@example.com"
        assert violations[0].violation_type == "DUPLICATE_UNIQUE_VALUE"

    def test_allows_unique_values(self) -> None:
        """Test that unique values pass validation."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
                {"id": "3", "email": "charlie@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_ignores_non_unique_columns(self) -> None:
        """Test that non-unique columns are not checked."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "status": "active"},
                {"id": "2", "status": "active"},  # Duplicate, but not unique
                {"id": "3", "status": "active"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "status": {"unique": False},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_allows_multiple_nulls_in_unique_column(self) -> None:
        """Test that multiple NULL values are allowed in UNIQUE column."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "nickname": "alice"},
                {"id": "2", "nickname": None},
                {"id": "3", "nickname": None},  # Duplicate NULL
                {"id": "4", "nickname": "bob"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "nickname": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # NULL values should not trigger violations
        assert len(violations) == 0


class TestMultipleUniqueConstraints:
    """Test multiple UNIQUE constraints in a table."""

    def test_validates_multiple_unique_columns(self) -> None:
        """Test validation of multiple UNIQUE columns."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com", "username": "alice"},
                {"id": "2", "email": "bob@example.com", "username": "bob"},
                {"id": "3", "email": "alice@example.com", "username": "charlie"},  # Duplicate email
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                    "username": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].column == "email"
        assert violations[0].value == "alice@example.com"

    def test_detects_duplicates_in_multiple_columns(self) -> None:
        """Test detecting duplicates in multiple UNIQUE columns."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com", "username": "alice"},
                {"id": "2", "email": "bob@example.com", "username": "bob"},
                {"id": "3", "email": "alice@example.com", "username": "alice"},  # Both duplicate
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                    "username": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 2
        columns = {v.column for v in violations}
        assert columns == {"email", "username"}


class TestCompositeUniqueConstraints:
    """Test composite (multi-column) UNIQUE constraints."""

    def test_detects_duplicate_composite_key(self) -> None:
        """Test detecting duplicate composite UNIQUE key."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "user_preferences": [
                {"user_id": "1", "theme": "dark", "language": "en"},
                {"user_id": "2", "theme": "light", "language": "fr"},
                {"user_id": "1", "theme": "dark", "language": "en"},  # Duplicate composite
            ]
        }
        schema_context = {
            "user_preferences": {
                "columns": {
                    "user_id": {},
                    "theme": {},
                    "language": {},
                },
                "unique_constraints": [{"columns": ["user_id", "theme", "language"]}],
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].violation_type == "DUPLICATE_COMPOSITE_KEY"

    def test_allows_partial_duplicates_in_composite_key(self) -> None:
        """Test that partial duplicates in composite key are allowed."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "user_preferences": [
                {"user_id": "1", "theme": "dark", "language": "en"},
                {"user_id": "1", "theme": "dark", "language": "fr"},  # Different language
                {"user_id": "1", "theme": "light", "language": "en"},  # Different theme
            ]
        }
        schema_context = {
            "user_preferences": {
                "columns": {
                    "user_id": {},
                    "theme": {},
                    "language": {},
                },
                "unique_constraints": [{"columns": ["user_id", "theme", "language"]}],
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0


class TestUniqueConstraintEdgeCases:
    """Test edge cases in unique constraint validation."""

    def test_handles_case_sensitive_matching(self) -> None:
        """Test that UNIQUE validation is case-sensitive."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "ALICE@EXAMPLE.COM"},  # Different case
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # Default: case-sensitive, so no violation
        assert len(violations) == 0

    def test_handles_uuid_values(self) -> None:
        """Test UNIQUE validation with UUID values."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {
                    "id": "01234567-89ab-cdef-0123-456789abcdef",
                    "guid": "11111111-2222-3333-4444-555555555555",
                },
                {
                    "id": "fedcba98-7654-3210-fedc-ba9876543210",
                    "guid": "11111111-2222-3333-4444-555555555555",
                },  # Duplicate GUID
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "guid": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].column == "guid"

    def test_handles_numeric_values(self) -> None:
        """Test UNIQUE validation with numeric values."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "products": [
                {"id": "1", "sku": "123"},
                {"id": "2", "sku": "456"},
                {"id": "3", "sku": "123"},  # Duplicate SKU
            ]
        }
        schema_context = {
            "products": {
                "columns": {
                    "sku": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].value == "123"

    def test_handles_empty_table(self) -> None:
        """Test UNIQUE validation with empty table."""
        validator = UniqueConstraintValidator()
        seed_data = {"users": []}
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_table_not_in_seed_data(self) -> None:
        """Test UNIQUE validation when table not in seed data."""
        validator = UniqueConstraintValidator()
        seed_data = {"other_table": [{"id": "1"}]}
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0


class TestViolationStructure:
    """Test the structure of UniqueConstraintViolation objects."""

    def test_violation_has_all_fields(self) -> None:
        """Test that violation contains all required fields."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        violation = violations[0]
        assert hasattr(violation, "table")
        assert hasattr(violation, "column")
        assert hasattr(violation, "value")
        assert hasattr(violation, "duplicate_count")
        assert hasattr(violation, "violation_type")
        assert hasattr(violation, "message")
        assert hasattr(violation, "severity")

    def test_violation_message_is_descriptive(self) -> None:
        """Test that violation message is human-readable."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        message = violations[0].message
        assert "users" in message.lower()
        assert "email" in message.lower()
        assert "alice@example.com" in message

    def test_violation_includes_duplicate_count(self) -> None:
        """Test that violation reports how many duplicates found."""
        validator = UniqueConstraintValidator()
        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "alice@example.com"},
                {"id": "3", "email": "alice@example.com"},
                {"id": "4", "email": "alice@example.com"},
            ]
        }
        schema_context = {
            "users": {
                "columns": {
                    "email": {"unique": True},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert violations[0].duplicate_count == 4
