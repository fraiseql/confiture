"""Tests for auto-detection of multi-tenant schemas."""

from confiture.core.linting.tenant.function_parser import FunctionInfo, InsertStatement
from confiture.core.linting.tenant.models import TenantRelationship
from confiture.core.linting.tenant.tenant_detector import TenantDetector


class TestIsMultiTenantSchema:
    """Tests for detecting if a schema is multi-tenant."""

    def test_detects_multi_tenant_with_tenant_views(self):
        """Detect multi-tenant schema when views have tenant columns."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.id, i.name, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """,
            """
            CREATE VIEW v_order AS
            SELECT ord.*, o.id AS tenant_id
            FROM tb_order ord
            JOIN tv_organization o ON ord.fk_org = o.pk_organization;
            """,
        ]

        detector = TenantDetector()
        is_tenant = detector.is_multi_tenant_schema(view_sqls)

        assert is_tenant is True

    def test_not_multi_tenant_without_tenant_views(self):
        """Not multi-tenant when views lack tenant columns."""
        view_sqls = [
            """
            CREATE VIEW v_counts AS
            SELECT COUNT(*) AS total FROM tb_item;
            """,
            """
            CREATE VIEW v_summary AS
            SELECT name, created_at FROM tb_audit_log;
            """,
        ]

        detector = TenantDetector()
        is_tenant = detector.is_multi_tenant_schema(view_sqls)

        assert is_tenant is False

    def test_multi_tenant_with_custom_patterns(self):
        """Detect multi-tenant with custom tenant column patterns."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, w.id AS workspace_id
            FROM tb_item i
            JOIN tb_workspace w ON i.fk_workspace = w.id;
            """
        ]

        detector = TenantDetector(tenant_patterns=["workspace_id"])
        is_tenant = detector.is_multi_tenant_schema(view_sqls)

        assert is_tenant is True

    def test_empty_views_not_multi_tenant(self):
        """Empty view list is not multi-tenant."""
        detector = TenantDetector()
        is_tenant = detector.is_multi_tenant_schema([])

        assert is_tenant is False


class TestDetectRelationships:
    """Tests for detecting tenant relationships from VIEWs."""

    def test_detect_single_relationship(self):
        """Detect tenant relationship from single VIEW."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.id, i.name, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]

        detector = TenantDetector()
        relationships = detector.detect_relationships(view_sqls)

        assert len(relationships) == 1
        rel = relationships[0]
        assert rel.view_name == "v_item"
        assert rel.source_table == "tb_item"
        assert rel.required_fk == "fk_org"

    def test_detect_multiple_relationships(self):
        """Detect relationships from multiple VIEWs."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """,
            """
            CREATE VIEW v_order AS
            SELECT ord.*, o.id AS tenant_id
            FROM tb_order ord
            JOIN tv_organization o ON ord.fk_org = o.pk_organization;
            """,
        ]

        detector = TenantDetector()
        relationships = detector.detect_relationships(view_sqls)

        assert len(relationships) == 2
        tables = {r.source_table for r in relationships}
        assert tables == {"tb_item", "tb_order"}

    def test_skip_non_tenant_views(self):
        """Skip views without tenant patterns."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """,
            """
            CREATE VIEW v_counts AS
            SELECT COUNT(*) AS total FROM tb_item;
            """,
        ]

        detector = TenantDetector()
        relationships = detector.detect_relationships(view_sqls)

        # Only the tenant VIEW should be detected
        assert len(relationships) == 1
        assert relationships[0].view_name == "v_item"


class TestBuildRequirementsMap:
    """Tests for building requirements map from relationships."""

    def test_build_requirements_from_relationships(self):
        """Build table -> required columns map from relationships."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_order",
                source_table="tb_order",
                required_fk="fk_org",
            ),
        ]

        detector = TenantDetector()
        requirements = detector.build_requirements_map(relationships)

        assert requirements == {
            "tb_item": ["fk_org"],
            "tb_order": ["fk_org"],
        }

    def test_multiple_fks_for_same_table(self):
        """Collect multiple FK requirements for same table."""
        relationships = [
            TenantRelationship(
                view_name="v_item_by_org",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_item_by_dept",
                source_table="tb_item",
                required_fk="fk_dept",
            ),
        ]

        detector = TenantDetector()
        requirements = detector.build_requirements_map(relationships)

        assert "tb_item" in requirements
        assert set(requirements["tb_item"]) == {"fk_org", "fk_dept"}

    def test_empty_relationships_returns_empty_map(self):
        """Empty relationships list returns empty map."""
        detector = TenantDetector()
        requirements = detector.build_requirements_map([])

        assert requirements == {}


class TestBuildViewMap:
    """Tests for building table -> views map."""

    def test_build_view_map_from_relationships(self):
        """Build table -> affected views map."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_order",
                source_table="tb_order",
                required_fk="fk_org",
            ),
        ]

        detector = TenantDetector()
        view_map = detector.build_view_map(relationships)

        assert view_map == {
            "tb_item": ["v_item"],
            "tb_order": ["v_order"],
        }

    def test_multiple_views_for_same_table(self):
        """Collect multiple views for same table."""
        relationships = [
            TenantRelationship(
                view_name="v_item_active",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_item_archived",
                source_table="tb_item",
                required_fk="fk_org",
            ),
        ]

        detector = TenantDetector()
        view_map = detector.build_view_map(relationships)

        assert "tb_item" in view_map
        assert set(view_map["tb_item"]) == {"v_item_active", "v_item_archived"}


class TestAnalyzeSchema:
    """Tests for complete schema analysis."""

    def test_analyze_schema_returns_violations(self):
        """Analyze schema and return tenant violations."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]

        functions = [
            FunctionInfo(
                name="fn_create_item",
                body="INSERT INTO tb_item (id, name) VALUES (1, 'test');",
                inserts=[
                    InsertStatement(
                        table_name="tb_item",
                        columns=["id", "name"],  # Missing fk_org
                        line_number=1,
                        raw_sql="INSERT INTO tb_item (id, name) VALUES (1, 'test')",
                    )
                ],
            )
        ]

        detector = TenantDetector()
        violations = detector.analyze_schema(
            view_sqls=view_sqls,
            functions=functions,
            file_path="functions/items.sql",
        )

        assert len(violations) == 1
        assert violations[0].function_name == "fn_create_item"
        assert violations[0].missing_columns == ["fk_org"]
        assert "v_item" in violations[0].affected_views

    def test_analyze_schema_no_violations_when_fk_present(self):
        """No violations when INSERT includes FK columns."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]

        functions = [
            FunctionInfo(
                name="fn_create_item",
                body="INSERT INTO tb_item (id, name, fk_org) VALUES (...);",
                inserts=[
                    InsertStatement(
                        table_name="tb_item",
                        columns=["id", "name", "fk_org"],  # FK present
                        line_number=1,
                        raw_sql="INSERT INTO tb_item (id, name, fk_org) VALUES (...)",
                    )
                ],
            )
        ]

        detector = TenantDetector()
        violations = detector.analyze_schema(
            view_sqls=view_sqls,
            functions=functions,
            file_path="functions/items.sql",
        )

        assert violations == []

    def test_analyze_schema_non_tenant_returns_empty(self):
        """Non-tenant schema returns no violations."""
        view_sqls = [
            """
            CREATE VIEW v_counts AS
            SELECT COUNT(*) AS total FROM tb_item;
            """
        ]

        functions = [
            FunctionInfo(
                name="fn_create_item",
                body="INSERT INTO tb_item (id, name) VALUES (1, 'test');",
                inserts=[
                    InsertStatement(
                        table_name="tb_item",
                        columns=["id", "name"],
                        line_number=1,
                        raw_sql="INSERT INTO tb_item (id, name) VALUES (1, 'test')",
                    )
                ],
            )
        ]

        detector = TenantDetector()
        violations = detector.analyze_schema(
            view_sqls=view_sqls,
            functions=functions,
            file_path="functions/items.sql",
        )

        # No tenant views, so no violations
        assert violations == []
