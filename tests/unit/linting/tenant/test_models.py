"""Tests for tenant isolation models."""

from confiture.core.linting.tenant.models import (
    TenantConfig,
    TenantRelationship,
    TenantViolation,
)


class TestTenantRelationship:
    """Tests for TenantRelationship dataclass."""

    def test_create_tenant_relationship(self):
        """TenantRelationship stores view-table-FK relationship."""
        rel = TenantRelationship(
            view_name="v_item",
            source_table="tb_item",
            required_fk="fk_org",
            tenant_column="tenant_id",
            fk_target_table="tv_organization",
            fk_target_column="pk_organization",
        )

        assert rel.view_name == "v_item"
        assert rel.source_table == "tb_item"
        assert rel.required_fk == "fk_org"
        assert rel.tenant_column == "tenant_id"
        assert rel.fk_target_table == "tv_organization"
        assert rel.fk_target_column == "pk_organization"

    def test_tenant_relationship_default_tenant_column(self):
        """TenantRelationship defaults tenant_column to 'tenant_id'."""
        rel = TenantRelationship(
            view_name="v_item",
            source_table="tb_item",
            required_fk="fk_org",
        )

        assert rel.tenant_column == "tenant_id"

    def test_tenant_relationship_str(self):
        """TenantRelationship has readable string representation."""
        rel = TenantRelationship(
            view_name="v_item",
            source_table="tb_item",
            required_fk="fk_org",
            tenant_column="tenant_id",
        )

        result = str(rel)
        assert "v_item" in result
        assert "tb_item" in result
        assert "fk_org" in result

    def test_tenant_relationship_equality(self):
        """Two TenantRelationships with same values are equal."""
        rel1 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")
        rel2 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")

        assert rel1 == rel2

    def test_tenant_relationship_hashable(self):
        """TenantRelationship can be used in sets."""
        rel1 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")
        rel2 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")

        # Should be usable in a set
        rel_set = {rel1, rel2}
        assert len(rel_set) == 1


class TestTenantViolation:
    """Tests for TenantViolation dataclass."""

    def test_create_tenant_violation(self):
        """TenantViolation captures violation details."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            line_number=15,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
            insert_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        assert violation.function_name == "fn_create_item"
        assert violation.file_path == "functions/fn_create_item.sql"
        assert violation.line_number == 15
        assert violation.table_name == "tb_item"
        assert violation.missing_columns == ["fk_org"]
        assert violation.affected_views == ["v_item"]
        assert "INSERT INTO tb_item" in violation.insert_sql

    def test_violation_suggestion(self):
        """TenantViolation provides actionable suggestion."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            line_number=15,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        suggestion = violation.suggestion
        assert "fk_org" in suggestion
        assert "v_item" in suggestion

    def test_violation_suggestion_multiple_columns(self):
        """TenantViolation suggestion includes all missing columns."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="test.sql",
            line_number=1,
            table_name="tb_item",
            missing_columns=["fk_org", "fk_dept"],
            affected_views=["v_item"],
        )

        suggestion = violation.suggestion
        assert "fk_org" in suggestion
        assert "fk_dept" in suggestion

    def test_violation_severity_is_warning(self):
        """TenantViolation default severity is WARNING."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="test.sql",
            line_number=1,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert violation.severity == "warning"

    def test_violation_str(self):
        """TenantViolation has readable string representation."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="test.sql",
            line_number=15,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        result = str(violation)
        assert "fn_create_item" in result
        assert "15" in result
        assert "tb_item" in result
        assert "fk_org" in result


class TestTenantConfig:
    """Tests for TenantConfig dataclass."""

    def test_default_config(self):
        """Default config enables auto-detection."""
        config = TenantConfig()

        assert config.enabled is True
        assert config.mode == "auto"
        assert "tenant_id" in config.tenant_column_patterns
        assert any("fk_org" in p for p in config.fk_patterns)

    def test_explicit_mode_with_relationships(self):
        """Explicit mode can define relationships."""
        rel = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")
        config = TenantConfig(mode="explicit", relationships=[rel])

        assert config.mode == "explicit"
        assert len(config.relationships) == 1
        assert config.relationships[0].view_name == "v_item"

    def test_disabled_config(self):
        """Config can be disabled."""
        config = TenantConfig(enabled=False)

        assert config.enabled is False

    def test_config_from_dict(self):
        """Config can be loaded from dictionary (YAML parsing)."""
        data = {
            "enabled": True,
            "mode": "explicit",
            "relationships": [{"view": "v_item", "table": "tb_item", "required_fk": "fk_org"}],
        }

        config = TenantConfig.from_dict(data)

        assert config.mode == "explicit"
        assert len(config.relationships) == 1
        assert config.relationships[0].view_name == "v_item"
        assert config.relationships[0].source_table == "tb_item"
        assert config.relationships[0].required_fk == "fk_org"

    def test_config_from_dict_with_tenant_column(self):
        """Config from dict respects tenant_column override."""
        data = {
            "enabled": True,
            "mode": "explicit",
            "relationships": [
                {
                    "view": "v_item",
                    "table": "tb_item",
                    "required_fk": "fk_org",
                    "tenant_column": "organization_id",
                }
            ],
        }

        config = TenantConfig.from_dict(data)

        assert config.relationships[0].tenant_column == "organization_id"

    def test_config_from_dict_defaults(self):
        """Config from dict uses defaults for missing fields."""
        data = {}

        config = TenantConfig.from_dict(data)

        assert config.enabled is True
        assert config.mode == "auto"
        assert config.relationships == []

    def test_config_custom_patterns(self):
        """Config can have custom column patterns."""
        config = TenantConfig(
            tenant_column_patterns=["tenant_id", "workspace_id"],
            fk_patterns=["fk_workspace*", "workspace_id"],
        )

        assert "workspace_id" in config.tenant_column_patterns
        assert "fk_workspace*" in config.fk_patterns
