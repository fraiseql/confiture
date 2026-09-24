"""Tests for Level 3 - Resolution function validation.

Resolution function validation to detect the schema drift bug.

This is the CRITICAL level that prevents the 360-test-failure incident
where a table moved from tenant→catalog schema and the resolution
function was never updated.
"""

from __future__ import annotations

from confiture.core.schema_sources import read_schema
from confiture.core.seed.validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.resolvers import find_resolvers

TABLES = """
CREATE TABLE prep_seed.tb_manufacturer (id UUID PRIMARY KEY, name TEXT);
CREATE TABLE catalog.tb_manufacturer (id UUID, pk_manufacturer BIGINT PRIMARY KEY, name TEXT);
CREATE TABLE prep_seed.tb_product (id UUID PRIMARY KEY, fk_manufacturer_id UUID, name TEXT);
CREATE TABLE catalog.tb_product (
    id UUID, pk_product BIGINT PRIMARY KEY, fk_manufacturer BIGINT, name TEXT
);
"""


def _validate(function: str) -> list[PrepSeedViolation]:
    read = read_schema(TABLES + function)
    (resolver,) = find_resolvers(read, catalog_schema="catalog")
    return Level3ResolutionValidator(read.model).validate(resolver)


def _drift(violations: list[PrepSeedViolation]) -> PrepSeedViolation:
    return next(v for v in violations if v.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER)


WRONG_SCHEMA = """
CREATE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
BEGIN
    INSERT INTO tenant.tb_manufacturer (id, name)  -- Wrong schema!
    SELECT id, name FROM prep_seed.tb_manufacturer;
END;
$$ LANGUAGE plpgsql;
"""


class TestLevel3ResolutionValidator:
    """Test Level 3 resolution function validation."""

    def test_detects_schema_drift_tenant_to_catalog(self) -> None:
        """CRITICAL: Detects when resolution function references wrong schema.

        This is the bug that caused 360 test failures.
        """
        drift = _drift(_validate(WRONG_SCHEMA))
        assert drift.severity == ViolationSeverity.CRITICAL
        assert "tenant" in drift.message
        assert "catalog" in drift.message

    def test_detects_missing_fk_transformation(self) -> None:
        """Detects missing JOIN for FK transformation."""
        violations = _validate("""
        CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
        BEGIN
            INSERT INTO catalog.tb_product (id, fk_manufacturer, name)
            SELECT id, NULL, name FROM prep_seed.tb_product;
            -- Missing: JOIN for fk_manufacturer_id
        END;
        $$ LANGUAGE plpgsql;
        """)
        assert any(v.pattern == PrepSeedPattern.MISSING_FK_TRANSFORMATION for v in violations)

    def test_passes_valid_resolution_function(self) -> None:
        """Valid resolution function passes validation."""
        violations = _validate("""
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
        """)
        assert violations == []

    def test_detects_multiple_issues(self) -> None:
        """Can detect multiple issues in one function."""
        violations = _validate("""
        CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_product (id, fk_manufacturer, name)
            SELECT id, NULL, name FROM prep_seed.tb_product;
            -- Wrong schema AND missing FK transformation
        END;
        $$ LANGUAGE plpgsql;
        """)
        patterns = {v.pattern for v in violations}
        assert PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER in patterns
        assert PrepSeedPattern.MISSING_FK_TRANSFORMATION in patterns

    def test_a_foreign_key_names_the_parent_table(self) -> None:
        """A declared foreign key says which table the column points at, not its name."""
        read = read_schema(
            TABLES.replace("fk_manufacturer_id UUID,", "fk_maker_id UUID,").replace(
                "fk_manufacturer BIGINT,", "fk_maker BIGINT,"
            )
            + "ALTER TABLE prep_seed.tb_product ADD FOREIGN KEY (fk_maker_id)"
            " REFERENCES prep_seed.tb_manufacturer (id);\n"
            + """
            CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
            BEGIN
                INSERT INTO catalog.tb_product (id, fk_maker, name)
                SELECT p.id, m.pk_manufacturer, p.name
                FROM prep_seed.tb_product p
                JOIN catalog.tb_manufacturer m ON m.id = p.fk_maker_id;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        (resolver,) = find_resolvers(read, catalog_schema="catalog")
        assert Level3ResolutionValidator(read.model).validate(resolver) == []

    def test_a_table_the_schema_does_not_define_is_not_drift(self) -> None:
        violations = _validate("""
        CREATE FUNCTION fn_resolve_tb_elsewhere() RETURNS void AS $$
        BEGIN
            INSERT INTO audit.tb_elsewhere (id) SELECT id FROM prep_seed.tb_product;
        END;
        $$ LANGUAGE plpgsql;
        """)
        assert violations == []

    def test_schema_drift_violation_has_impact_description(self) -> None:
        """Schema drift violations include impact description."""
        drift = _drift(_validate(WRONG_SCHEMA))
        assert drift.impact is not None
        assert "dependent" in drift.impact.lower()

    def test_auto_fix_available_for_schema_drift(self) -> None:
        """Schema drift violations are auto-fixable."""
        drift = _drift(_validate(WRONG_SCHEMA))
        assert drift.fix_available is True
        assert drift.suggestion is not None
        assert "catalog.tb_manufacturer" in drift.suggestion
