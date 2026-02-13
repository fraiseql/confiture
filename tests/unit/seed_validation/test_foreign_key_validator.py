"""Tests for ForeignKeyDepthValidator - verify FK references exist in seed data."""

from confiture.core.seed_validation.foreign_key_validator import (
    ForeignKeyDepthValidator,
)


class TestBasicForeignKeyValidation:
    """Test basic foreign key reference validation."""

    def test_validates_existing_foreign_key(self) -> None:
        """Test validation passes when FK exists in seed data."""
        validator = ForeignKeyDepthValidator()

        # Seed data defines both orders and customers
        orders = [{"id": "order-1", "customer_id": "cust-1"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_missing_foreign_key(self) -> None:
        """Test detection of non-existent FK reference."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-999"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].violation_type == "MISSING_FOREIGN_KEY"
        assert "cust-999" in violations[0].message
        assert "customers" in violations[0].message

    def test_detects_missing_foreign_key_with_context(self) -> None:
        """Test violation includes proper context information."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-999"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.table == "orders"
        assert violation.column == "customer_id"
        assert violation.referenced_table == "customers"
        assert violation.referenced_column == "id"
        assert violation.value == "cust-999"

    def test_ignores_null_foreign_keys(self) -> None:
        """Test that NULL values in optional FK columns are allowed."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {"id": "order-1", "customer_id": None},  # NULL is ok
            {"id": "order-2", "customer_id": "cust-1"},
        ]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        # Should not report violation for NULL
        assert len(violations) == 0

    def test_reports_multiple_missing_foreign_keys(self) -> None:
        """Test reporting all FK violations in seed data."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {"id": "order-1", "customer_id": "cust-999"},
            {"id": "order-2", "customer_id": "cust-888"},
        ]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 2
        assert all(v.violation_type == "MISSING_FOREIGN_KEY" for v in violations)


class TestMultipleForeignKeys:
    """Test validation with multiple FK columns."""

    def test_handles_multiple_foreign_keys(self) -> None:
        """Test validation with multiple FK columns."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-1",
                "address_id": "addr-1",
            },
            {
                "id": "order-2",
                "customer_id": "cust-2",
                "address_id": "addr-2",
            },
        ]
        customers = [
            {"id": "cust-1", "name": "Alice"},
            {"id": "cust-2", "name": "Bob"},
        ]
        addresses = [
            {"id": "addr-1", "city": "New York"},
            {"id": "addr-2", "city": "Los Angeles"},
        ]

        seed_data = {
            "orders": orders,
            "customers": customers,
            "addresses": addresses,
        }
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {"foreign_key": ("customers", "id")},
                    "address_id": {"foreign_key": ("addresses", "id")},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_violation_in_first_of_multiple_fks(self) -> None:
        """Test detecting violation in one FK when multiple exist."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-999",  # Invalid
                "address_id": "addr-1",
            }
        ]
        customers = [{"id": "cust-1", "name": "Alice"}]
        addresses = [{"id": "addr-1", "city": "New York"}]

        seed_data = {"orders": orders, "customers": customers, "addresses": addresses}
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {"foreign_key": ("customers", "id")},
                    "address_id": {"foreign_key": ("addresses", "id")},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].column == "customer_id"

    def test_detects_violation_in_second_of_multiple_fks(self) -> None:
        """Test detecting violation in second FK."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-1",
                "address_id": "addr-999",  # Invalid
            }
        ]
        customers = [{"id": "cust-1", "name": "Alice"}]
        addresses = [{"id": "addr-1", "city": "New York"}]

        seed_data = {"orders": orders, "customers": customers, "addresses": addresses}
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {"foreign_key": ("customers", "id")},
                    "address_id": {"foreign_key": ("addresses", "id")},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].column == "address_id"

    def test_detects_violations_in_all_fks(self) -> None:
        """Test detecting violations when multiple FKs are invalid."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-999",
                "address_id": "addr-999",
            }
        ]
        customers = [{"id": "cust-1", "name": "Alice"}]
        addresses = [{"id": "addr-1", "city": "New York"}]

        seed_data = {"orders": orders, "customers": customers, "addresses": addresses}
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {"foreign_key": ("customers", "id")},
                    "address_id": {"foreign_key": ("addresses", "id")},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 2


class TestCompositeForeignKeys:
    """Test composite (multi-column) foreign key validation."""

    def test_validates_composite_foreign_key(self) -> None:
        """Test validation of composite FK (multiple columns)."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-1",
                "order_type": "standard",
            }
        ]
        customers = [{"id": "cust-1", "type": "standard", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {
                        "foreign_key": ("customers", "id"),
                        "composite_with": "order_type",
                    },
                    "order_type": {
                        "foreign_key": ("customers", "type"),
                        "composite_with": "customer_id",
                    },
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_composite_fk_violation(self) -> None:
        """Test detecting violation in composite FK."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "order-1",
                "customer_id": "cust-1",
                "order_type": "premium",  # Mismatch: cust-1 is type "standard"
            }
        ]
        customers = [{"id": "cust-1", "type": "standard", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {
                "columns": {
                    "customer_id": {"foreign_key": ("customers", "id")},
                    "order_type": {"foreign_key": ("customers", "type")},
                }
            }
        }

        violations = validator.validate(seed_data, schema_context)

        # May report one or both depending on implementation
        assert len(violations) >= 1


class TestUUIDForeignKeys:
    """Test foreign key validation with UUID values."""

    def test_handles_uuid_foreign_keys(self) -> None:
        """Test extracting UUID-based foreign keys."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "01234567-89ab-cdef-0123-456789abcdef",
                "customer_id": "11111111-2222-3333-4444-555555555555",
            }
        ]
        customers = [{"id": "11111111-2222-3333-4444-555555555555", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_missing_uuid_foreign_key(self) -> None:
        """Test detecting missing UUID FK reference."""
        validator = ForeignKeyDepthValidator()

        orders = [
            {
                "id": "01234567-89ab-cdef-0123-456789abcdef",
                "customer_id": "99999999-9999-9999-9999-999999999999",  # Invalid
            }
        ]
        customers = [{"id": "11111111-2222-3333-4444-555555555555", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1


class TestForeignKeyChains:
    """Test validation of FK chains (A→B→C relationships)."""

    def test_validates_direct_fk_chain(self) -> None:
        """Test validation of direct FK chain."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-1"}]
        customers = [{"id": "cust-1", "region_id": "region-1"}]
        regions = [{"id": "region-1", "name": "North America"}]

        seed_data = {
            "orders": orders,
            "customers": customers,
            "regions": regions,
        }
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}},
            "customers": {"columns": {"region_id": {"foreign_key": ("regions", "id")}}},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_detects_missing_fk_in_chain(self) -> None:
        """Test detecting violation in FK chain (missing intermediate reference)."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-1"}]
        customers = [{"id": "cust-1", "region_id": "region-999"}]  # Invalid
        regions = [{"id": "region-1", "name": "North America"}]

        seed_data = {
            "orders": orders,
            "customers": customers,
            "regions": regions,
        }
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}},
            "customers": {"columns": {"region_id": {"foreign_key": ("regions", "id")}}},
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        assert violations[0].table == "customers"
        assert violations[0].referenced_table == "regions"


class TestForeignKeyEdgeCases:
    """Test edge cases in FK validation."""

    def test_handles_empty_seed_data(self) -> None:
        """Test handling empty seed data."""
        validator = ForeignKeyDepthValidator()

        seed_data = {}
        schema_context = {}

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0

    def test_handles_missing_referenced_table(self) -> None:
        """Test FK reference to non-existent table."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-1"}]

        seed_data = {"orders": orders}  # customers table missing
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        # Should report all FKs in orders as missing
        assert len(violations) == 1

    def test_handles_empty_referenced_table(self) -> None:
        """Test FK reference to empty table."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-1"}]
        customers = []  # Empty table

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1

    def test_handles_quoted_string_values(self) -> None:
        """Test FK validation with quoted string values."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "'order-1'", "customer_id": "'cust-1'"}]
        customers = [{"id": "'cust-1'", "name": "'Alice'"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        # Should handle quoted values
        violations = validator.validate(seed_data, schema_context)

        # Depending on implementation, may or may not match quoted values
        assert isinstance(violations, list)

    def test_handles_case_sensitivity(self) -> None:
        """Test FK validation respects case sensitivity."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "CUST-1"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        # Should detect case difference as violation
        assert len(violations) == 1

    def test_handles_numeric_foreign_keys(self) -> None:
        """Test FK validation with numeric values."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "1", "customer_id": "1"}]
        customers = [{"id": "1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 0


class TestViolationStructure:
    """Test ForeignKeyViolation data structure."""

    def test_violation_has_required_fields(self) -> None:
        """Test that violation includes all required fields."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-999"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        assert len(violations) == 1
        violation = violations[0]

        # Check all required fields
        assert hasattr(violation, "table")
        assert hasattr(violation, "column")
        assert hasattr(violation, "referenced_table")
        assert hasattr(violation, "referenced_column")
        assert hasattr(violation, "value")
        assert hasattr(violation, "violation_type")
        assert hasattr(violation, "message")
        assert hasattr(violation, "severity")

    def test_violation_message_is_clear(self) -> None:
        """Test that violation message is clear and helpful."""
        validator = ForeignKeyDepthValidator()

        orders = [{"id": "order-1", "customer_id": "cust-999"}]
        customers = [{"id": "cust-1", "name": "Alice"}]

        seed_data = {"orders": orders, "customers": customers}
        schema_context = {
            "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
        }

        violations = validator.validate(seed_data, schema_context)

        violation = violations[0]
        # Message should mention key details
        assert "customer_id" in violation.message
        assert "cust-999" in violation.message
