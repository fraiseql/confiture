"""Tests for Level 3 - Resolution function validation.

Cycle 3-6: Resolution function validation to detect schema drift bug.

This is the CRITICAL level that prevents the 360-test-failure incident
where a table moved from tenant→catalog schema and the resolution
function was never updated.
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    ViolationSeverity,
)


class TestLevel3ResolutionValidator:
    """Test Level 3 resolution function validation."""

    def test_validator_initialization(self) -> None:
        """Can create a Level3ResolutionValidator."""
        validator = Level3ResolutionValidator()
        assert validator is not None

    def test_detects_schema_drift_tenant_to_catalog(self) -> None:
        """CRITICAL: Detects when resolution function references wrong schema.

        This is the bug that caused 360 test failures.
        """
        # Resolution function referencing wrong schema
        func_body = """
        CREATE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_manufacturer (id, name)  -- Wrong schema!
            SELECT id, name FROM prep_seed.tb_manufacturer;
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()

        # Mock the database lookup to say table is in catalog
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_manufacturer",
            func_body=func_body,
            expected_table="tb_manufacturer",
        )

        # Should detect the schema drift
        assert any(v.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER for v in violations)

        # Should be CRITICAL severity
        drift_violation = next(
            v for v in violations if v.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER
        )
        assert drift_violation.severity == ViolationSeverity.CRITICAL
        assert "tenant" in drift_violation.message
        assert "catalog" in drift_violation.message

    def test_detects_missing_fk_transformation(self) -> None:
        """Detects missing JOIN for FK transformation."""
        # Resolution function missing JOIN for manufacturer FK
        func_body = """
        CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
        BEGIN
            INSERT INTO catalog.tb_product (id, fk_manufacturer, name)
            SELECT id, NULL, name FROM prep_seed.tb_product;
            -- Missing: JOIN for fk_manufacturer_id
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_product",
            func_body=func_body,
            expected_table="tb_product",
            fk_columns=["fk_manufacturer_id"],  # FK in prep_seed
        )

        # Should detect missing FK transformation
        assert any(v.pattern == PrepSeedPattern.MISSING_FK_TRANSFORMATION for v in violations)

    def test_passes_valid_resolution_function(self) -> None:
        """Valid resolution function passes validation."""
        func_body = """
        CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
        BEGIN
            INSERT INTO catalog.tb_product (id, fk_manufacturer, name)
            SELECT
                p.id,
                m.pk_manufacturer,
                p.name
            FROM prep_seed.tb_product p
            LEFT JOIN catalog.tb_manufacturer m ON m.id = p.fk_manufacturer_id;
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_product",
            func_body=func_body,
            expected_table="tb_product",
            fk_columns=["fk_manufacturer_id"],
        )

        # Should have no violations for a valid function
        assert len(violations) == 0

    def test_detects_multiple_issues(self) -> None:
        """Can detect multiple issues in one function."""
        func_body = """
        CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_product (id, fk_manufacturer, name)
            SELECT id, NULL, name FROM prep_seed.tb_product;
            -- Wrong schema AND missing FK transformation
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_product",
            func_body=func_body,
            expected_table="tb_product",
            fk_columns=["fk_manufacturer_id"],
        )

        # Should detect both issues
        patterns = {v.pattern for v in violations}
        assert PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER in patterns
        assert PrepSeedPattern.MISSING_FK_TRANSFORMATION in patterns

    def test_schema_drift_violation_has_impact_description(self) -> None:
        """Schema drift violations include impact description."""
        func_body = """
        CREATE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_manufacturer",
            func_body=func_body,
            expected_table="tb_manufacturer",
        )

        drift_violation = next(
            v for v in violations if v.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER
        )

        # Should describe impact (dependent tables)
        assert drift_violation.impact is not None
        assert "dependent" in drift_violation.impact.lower()

    def test_auto_fix_available_for_schema_drift(self) -> None:
        """Schema drift violations are auto-fixable."""
        func_body = """
        CREATE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
        END;
        $$ LANGUAGE plpgsql;
        """

        validator = Level3ResolutionValidator()
        validator.get_table_schema = lambda t: "catalog"  # type: ignore

        violations = validator.validate_function(
            func_name="fn_resolve_tb_manufacturer",
            func_body=func_body,
            expected_table="tb_manufacturer",
        )

        drift_violation = next(
            v for v in violations if v.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER
        )

        assert drift_violation.fix_available is True
        assert drift_violation.suggestion is not None
        assert "catalog.tb_manufacturer" in drift_violation.suggestion
