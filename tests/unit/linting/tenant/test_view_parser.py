"""Tests for VIEW parsing for tenant detection."""

from confiture.core.linting.tenant.view_parser import ViewParser


class TestExtractTableAliases:
    """Tests for extracting table aliases from VIEW definitions."""

    def test_extract_table_aliases_simple(self):
        """Extract table and alias from simple FROM clause."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name
        FROM tb_item i;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "tb_item"}

    def test_extract_table_aliases_with_join(self):
        """Extract tables from FROM and JOIN clauses."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, o.name AS org_name
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "tb_item", "o": "tv_organization"}

    def test_extract_table_aliases_no_alias(self):
        """Handle tables without aliases."""
        sql = """
        CREATE VIEW v_item AS
        SELECT id, name FROM tb_item;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"tb_item": "tb_item"}

    def test_extract_table_aliases_schema_qualified(self):
        """Handle schema-qualified table names."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.* FROM myschema.tb_item i;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "myschema.tb_item"}

    def test_extract_table_aliases_with_as_keyword(self):
        """Handle explicit AS keyword for alias."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id FROM tb_item AS i;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "tb_item"}

    def test_extract_table_aliases_multiple_joins(self):
        """Handle multiple JOIN clauses."""
        sql = """
        CREATE VIEW v_order AS
        SELECT o.*, c.name, org.id
        FROM tb_order o
        INNER JOIN tb_customer c ON o.fk_customer = c.id
        LEFT JOIN tv_organization org ON c.fk_org = org.pk_organization;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {
            "o": "tb_order",
            "c": "tb_customer",
            "org": "tv_organization",
        }


class TestExtractJoinConditions:
    """Tests for extracting JOIN conditions from VIEW definitions."""

    def test_extract_join_on_fk(self):
        """Extract FK column from JOIN ON condition."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.id AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        assert len(joins) == 1
        assert joins[0].left_alias == "i"
        assert joins[0].left_column == "fk_org"
        assert joins[0].right_alias == "o"
        assert joins[0].right_column == "pk_organization"

    def test_extract_multiple_joins(self):
        """Extract conditions from multiple JOINs."""
        sql = """
        CREATE VIEW v_order AS
        SELECT o.*, c.name AS customer_name, org.id AS tenant_id
        FROM tb_order o
        JOIN tb_customer c ON o.fk_customer = c.id
        JOIN tv_organization org ON c.fk_org = org.pk_organization;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        assert len(joins) == 2

    def test_extract_join_reversed_order(self):
        """Handle JOIN condition with right side first."""
        sql = """
        CREATE VIEW v_item AS
        SELECT *
        FROM tb_item i
        JOIN tv_organization o ON o.pk_organization = i.fk_org;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        assert len(joins) == 1
        # Either order should be captured
        join = joins[0]
        columns = {join.left_column, join.right_column}
        assert "fk_org" in columns
        assert "pk_organization" in columns


class TestDetectTenantColumn:
    """Tests for detecting tenant columns in SELECT clause."""

    def test_detect_tenant_id_alias(self):
        """Detect column aliased as tenant_id."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.id AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id", "organization_id"])

        assert tenant_col is not None
        assert tenant_col.alias == "tenant_id"
        assert tenant_col.source_alias == "o"
        assert tenant_col.source_column == "id"

    def test_detect_organization_id_alias(self):
        """Detect column aliased as organization_id."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS organization_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id", "organization_id"])

        assert tenant_col is not None
        assert tenant_col.alias == "organization_id"

    def test_no_tenant_column_returns_none(self):
        """Return None if no tenant column detected."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name FROM tb_item i;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id"])

        assert tenant_col is None

    def test_detect_tenant_column_case_insensitive(self):
        """Tenant column detection is case-insensitive."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, o.id AS TENANT_ID
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id"])

        assert tenant_col is not None


class TestBuildTenantRelationship:
    """Tests for building TenantRelationship from VIEW SQL."""

    def test_build_relationship_from_view(self):
        """Build complete TenantRelationship from VIEW SQL."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.id AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        relationship = parser.build_tenant_relationship(sql, view_name="v_item")

        assert relationship is not None
        assert relationship.view_name == "v_item"
        assert relationship.source_table == "tb_item"
        assert relationship.required_fk == "fk_org"
        assert relationship.tenant_column == "tenant_id"
        assert relationship.fk_target_table == "tv_organization"

    def test_build_relationship_returns_none_for_non_tenant_view(self):
        """Return None for views without tenant pattern."""
        sql = """
        CREATE VIEW v_counts AS
        SELECT COUNT(*) as total FROM tb_item;
        """

        parser = ViewParser()
        relationship = parser.build_tenant_relationship(sql, view_name="v_counts")

        assert relationship is None

    def test_build_relationship_with_custom_patterns(self):
        """Build relationship with custom tenant column patterns."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.*, w.id AS workspace_id
        FROM tb_item i
        JOIN tb_workspace w ON i.fk_workspace = w.id;
        """

        parser = ViewParser()
        relationship = parser.build_tenant_relationship(
            sql,
            view_name="v_item",
            tenant_patterns=["workspace_id"],
        )

        assert relationship is not None
        assert relationship.tenant_column == "workspace_id"
        assert relationship.required_fk == "fk_workspace"


class TestExtractViewName:
    """Tests for extracting view name from CREATE VIEW statement."""

    def test_extract_view_name_simple(self):
        """Extract view name from simple CREATE VIEW."""
        sql = "CREATE VIEW v_item AS SELECT * FROM tb_item;"

        parser = ViewParser()
        name = parser.extract_view_name(sql)

        assert name == "v_item"

    def test_extract_view_name_or_replace(self):
        """Extract view name from CREATE OR REPLACE VIEW."""
        sql = "CREATE OR REPLACE VIEW v_item AS SELECT * FROM tb_item;"

        parser = ViewParser()
        name = parser.extract_view_name(sql)

        assert name == "v_item"

    def test_extract_view_name_schema_qualified(self):
        """Extract schema-qualified view name."""
        sql = "CREATE VIEW myschema.v_item AS SELECT * FROM tb_item;"

        parser = ViewParser()
        name = parser.extract_view_name(sql)

        assert name == "myschema.v_item"

    def test_extract_view_name_returns_none_for_non_view(self):
        """Return None for non-VIEW SQL."""
        sql = "CREATE TABLE tb_item (id INT);"

        parser = ViewParser()
        name = parser.extract_view_name(sql)

        assert name is None
