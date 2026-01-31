"""Tests for Level 2 - Schema consistency validation.

Cycles 4-7: Validates schema mapping, FK types, trinity pattern, self-references.
"""

from __future__ import annotations

from dataclasses import dataclass

from confiture.core.seed_validation.prep_seed.level_2_schema import (
    Level2SchemaValidator,
    TableDefinition,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
)


@dataclass
class MockTable:
    """Mock table for testing."""

    name: str
    schema: str
    columns: dict[str, str]  # column_name -> type


class TestLevel2SchemaValidator:
    """Test Level 2 schema consistency validation."""

    def test_validator_initialization(self) -> None:
        """Can create a Level2SchemaValidator."""
        validator = Level2SchemaValidator()
        assert validator is not None

    def test_detects_missing_final_table(self) -> None:
        """Detects when prep_seed table has no corresponding final table."""
        prep_table = TableDefinition(
            name="tb_manufacturer",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "name": "TEXT",
            },
        )

        validator = Level2SchemaValidator()

        # Mock database with no matching final table
        validator.get_final_table = lambda name: None  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should detect missing final table
        assert any(v.pattern == PrepSeedPattern.MISSING_FK_MAPPING for v in violations)

    def test_validates_final_table_exists(self) -> None:
        """Validates when final table exists."""
        prep_table = TableDefinition(
            name="tb_manufacturer",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "name": "TEXT",
            },
        )

        final_table = TableDefinition(
            name="tb_manufacturer",
            schema="catalog",
            columns={
                "id": "UUID",
                "pk_manufacturer": "BIGINT",
                "name": "TEXT",
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should have no violations for existing final table
        assert len(violations) == 0

    def test_detects_missing_fk_mapping(self) -> None:
        """Detects when FK column in prep_seed has no matching column in final."""
        prep_table = TableDefinition(
            name="tb_product",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "fk_manufacturer_id": "UUID",
            },
        )

        final_table = TableDefinition(
            name="tb_product",
            schema="catalog",
            columns={
                "id": "UUID",
                "pk_product": "BIGINT",
                "fk_category": "BIGINT",  # Has fk_category but not fk_manufacturer
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should detect missing FK mapping
        assert any(v.pattern == PrepSeedPattern.MISSING_FK_MAPPING for v in violations)

    def test_validates_fk_type_mapping(self) -> None:
        """Validates that FK columns map UUID -> BIGINT."""
        prep_table = TableDefinition(
            name="tb_product",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "fk_manufacturer_id": "UUID",
            },
        )

        final_table = TableDefinition(
            name="tb_product",
            schema="catalog",
            columns={
                "id": "UUID",
                "pk_product": "BIGINT",
                "fk_manufacturer": "BIGINT",  # Correct type mapping
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should have no violations for correct FK type mapping
        assert len(violations) == 0

    def test_detects_trinity_pattern_violations(self) -> None:
        """Detects when trinity pattern not followed in final table."""
        prep_table = TableDefinition(
            name="tb_manufacturer",
            schema="prep_seed",
            columns={"id": "UUID"},
        )

        # Final table missing pk_* column (trinity pattern incomplete)
        final_table = TableDefinition(
            name="tb_manufacturer",
            schema="catalog",
            columns={
                "id": "UUID",
                # Missing: pk_manufacturer BIGINT
                "name": "TEXT",
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should detect missing pk_* column
        assert any(v.message and "pk_" in v.message for v in violations)

    def test_detects_self_reference(self) -> None:
        """Detects self-referencing FK columns."""
        prep_table = TableDefinition(
            name="tb_product",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "fk_parent_product_id": "UUID",  # References same table
            },
        )

        validator = Level2SchemaValidator()

        violations = validator.detect_self_references(prep_table)

        # Should detect self-reference
        assert any(v.pattern == PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING for v in violations)

    def test_detects_self_reference_in_mapping(self) -> None:
        """Marks self-references with special handling note."""
        prep_table = TableDefinition(
            name="tb_node",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "fk_parent_node_id": "UUID",
            },
        )

        final_table = TableDefinition(
            name="tb_node",
            schema="catalog",
            columns={
                "id": "UUID",
                "pk_node": "BIGINT",
                "fk_parent_node": "BIGINT",
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should have self-reference handling note in violations
        assert any(v.pattern == PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING for v in violations)

    def test_valid_trinity_pattern_passes(self) -> None:
        """Valid trinity pattern passes all checks."""
        prep_table = TableDefinition(
            name="tb_manufacturer",
            schema="prep_seed",
            columns={
                "id": "UUID",
                "fk_category_id": "UUID",
                "name": "TEXT",
            },
        )

        final_table = TableDefinition(
            name="tb_manufacturer",
            schema="catalog",
            columns={
                "id": "UUID",
                "pk_manufacturer": "BIGINT",
                "fk_category": "BIGINT",
                "name": "TEXT",
            },
        )

        validator = Level2SchemaValidator()
        validator.get_final_table = lambda name: final_table  # type: ignore

        violations = validator.validate_schema_mapping(prep_table)

        # Should pass all checks
        assert len(violations) == 0
