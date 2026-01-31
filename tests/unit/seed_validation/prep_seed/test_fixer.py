"""Tests for PrepSeed auto-fixer.

Cycle 7: Auto-fix schema reference updates.
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.fixer import PrepSeedFixer


class TestPrepSeedFixer:
    """Test PrepSeed auto-fixer for schema drift."""

    def test_fixer_initialization(self) -> None:
        """Can create a PrepSeedFixer."""
        fixer = PrepSeedFixer()
        assert fixer is not None

    def test_fix_schema_drift_tenant_to_catalog(self) -> None:
        """Can fix schema drift by updating schema references."""
        # Broken function with tenant.tb_manufacturer
        func_body = """
        CREATE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
        BEGIN
            INSERT INTO tenant.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
        END;
        $$ LANGUAGE plpgsql;
        """

        fixer = PrepSeedFixer()
        # Specify we're replacing tenant with catalog
        fixed = fixer.fix_schema_drift(
            func_body, "tb_manufacturer", "catalog", wrong_schema="tenant"
        )

        # Should replace tenant with catalog
        assert "catalog.tb_manufacturer" in fixed
        assert "tenant.tb_manufacturer" not in fixed
        assert "prep_seed.tb_manufacturer" in fixed  # Unchanged

    def test_fix_multiple_occurrences(self) -> None:
        """Fixes all occurrences of wrong schema reference."""
        func_body = """
        BEGIN
            INSERT INTO tenant.tb_manufacturer (id, name)
            VALUES ...
            UPDATE tenant.tb_manufacturer SET ...
        END;
        """

        fixer = PrepSeedFixer()
        fixed = fixer.fix_schema_drift(
            func_body, "tb_manufacturer", "catalog", wrong_schema="tenant"
        )

        # Should fix both INSERT and UPDATE
        assert "catalog.tb_manufacturer" in fixed
        assert "tenant.tb_manufacturer" not in fixed

    def test_preserves_table_name(self) -> None:
        """Doesn't accidentally modify similar names."""
        func_body = """
        INSERT INTO tenant.tb_manufacturer (id)
        SELECT m.id FROM tenant.tb_manufacturer_history m;
        """

        fixer = PrepSeedFixer()
        fixed = fixer.fix_schema_drift(
            func_body, "tb_manufacturer", "catalog", wrong_schema="tenant"
        )

        # Should update tb_manufacturer but not tb_manufacturer_history
        assert "catalog.tb_manufacturer" in fixed
        # tb_manufacturer_history should still have tenant prefix
        assert "tenant.tb_manufacturer_history" in fixed

    def test_case_insensitive_fix(self) -> None:
        """Fixes schema references regardless of case."""
        func_body = """
        INSERT INTO TENANT.TB_MANUFACTURER (id)
        VALUES ...
        """

        fixer = PrepSeedFixer()
        fixed = fixer.fix_schema_drift(
            func_body, "tb_manufacturer", "catalog", wrong_schema="tenant"
        )

        # Should fix even with different case
        assert "catalog" in fixed.lower()
        assert "tenant" not in fixed.lower()
