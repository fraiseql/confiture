"""Integration tests for tenant isolation linting workflow.

Tests the complete workflow of detecting tenant patterns in VIEWs
and identifying missing FK columns in function INSERT statements.
"""

from pathlib import Path

from confiture.core.linting.schema_linter import LintReport
from confiture.core.linting.tenant import (
    TenantDetector,
    TenantIsolationFormatter,
    TenantIsolationRule,
)


class TestTenantIsolationFullWorkflow:
    """Integration tests for complete tenant isolation workflow."""

    def test_full_workflow_detects_violations(self, tmp_path: Path):
        """Test complete workflow: schema -> detect patterns -> find violations."""
        # Create realistic schema structure
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "10_tables").mkdir(parents=True)
        (schema_dir / "20_views").mkdir(parents=True)
        (schema_dir / "30_functions").mkdir(parents=True)

        # Create organization table
        (schema_dir / "10_tables" / "organization.sql").write_text("""
        CREATE TABLE tv_organization (
            pk_organization BIGINT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """)

        # Create item table with FK
        (schema_dir / "10_tables" / "item.sql").write_text("""
        CREATE TABLE tb_item (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            fk_org BIGINT REFERENCES tv_organization(pk_organization)
        );
        """)

        # Create tenant-filtered view
        view_sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.pk_organization AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """
        (schema_dir / "20_views" / "v_item.sql").write_text(view_sql)

        # Create function with missing FK (bad)
        bad_func_sql = """
        CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (nextval('seq'), p_name);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """
        (schema_dir / "30_functions" / "fn_create_item.sql").write_text(bad_func_sql)

        # Create function with FK (good)
        good_func_sql = """
        CREATE FUNCTION fn_create_item_safe(p_name TEXT, p_org BIGINT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name, fk_org) VALUES (nextval('seq'), p_name, p_org);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """
        (schema_dir / "30_functions" / "fn_create_item_safe.sql").write_text(good_func_sql)

        # Run the rule
        rule = TenantIsolationRule()
        report = LintReport()

        # Collect view files
        view_paths = list((schema_dir / "20_views").glob("*.sql"))
        function_paths = list((schema_dir / "30_functions").glob("*.sql"))

        rule.run_from_files(
            view_paths=view_paths,
            function_paths=function_paths,
            report=report,
        )

        # Verify violation detected
        assert report.total_violations == 1
        violation = report.warnings[0]
        assert "fn_create_item" in violation.object_name
        assert "fk_org" in violation.message
        # Should NOT flag the safe function
        assert "fn_create_item_safe" not in str(report.warnings)

    def test_workflow_with_multiple_tables_and_views(self, tmp_path: Path):
        """Test workflow with multiple tenant-filtered tables."""
        views_dir = tmp_path / "views"
        functions_dir = tmp_path / "functions"
        views_dir.mkdir()
        functions_dir.mkdir()

        # Create views for items and orders
        (views_dir / "v_item.sql").write_text("""
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        (views_dir / "v_order.sql").write_text("""
        CREATE VIEW v_order AS
        SELECT ord.*, o.pk_organization AS tenant_id
        FROM tb_order ord
        JOIN tv_organization o ON ord.fk_org = o.pk_organization;
        """)

        # Create functions - one bad for each table
        (functions_dir / "fn_items.sql").write_text("""
        CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, p_name);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """)

        (functions_dir / "fn_orders.sql").write_text("""
        CREATE FUNCTION fn_create_order(p_total NUMERIC) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_order (id, total) VALUES (1, p_total);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """)

        # Run the rule
        rule = TenantIsolationRule()
        report = LintReport()

        rule.run_from_directories(
            view_dirs=[views_dir],
            function_dirs=[functions_dir],
            report=report,
        )

        # Should find 2 violations (one per table)
        assert report.total_violations == 2
        violation_funcs = {v.object_name for v in report.warnings}
        assert "fn_create_item" in violation_funcs
        assert "fn_create_order" in violation_funcs

    def test_non_tenant_schema_no_violations(self, tmp_path: Path):
        """Non-tenant schema produces no violations."""
        views_dir = tmp_path / "views"
        functions_dir = tmp_path / "functions"
        views_dir.mkdir()
        functions_dir.mkdir()

        # Create view without tenant pattern
        (views_dir / "v_counts.sql").write_text("""
        CREATE VIEW v_counts AS
        SELECT COUNT(*) AS total FROM tb_item;
        """)

        # Create function
        (functions_dir / "fn_insert.sql").write_text("""
        CREATE FUNCTION fn_insert(p_name TEXT) RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, p_name);
        END;
        $$ LANGUAGE plpgsql;
        """)

        # Run the rule
        rule = TenantIsolationRule()
        report = LintReport()

        rule.run_from_directories(
            view_dirs=[views_dir],
            function_dirs=[functions_dir],
            report=report,
        )

        # No violations because no tenant patterns detected
        assert report.total_violations == 0


class TestTenantDetectorWorkflow:
    """Integration tests for TenantDetector workflow."""

    def test_detect_relationships_from_multiple_views(self):
        """Detect tenant relationships from multiple VIEWs."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.pk_organization AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """,
            """
            CREATE VIEW v_order AS
            SELECT ord.*, o.pk_organization AS tenant_id
            FROM tb_order ord
            JOIN tv_organization o ON ord.fk_org = o.pk_organization;
            """,
            """
            CREATE VIEW v_counts AS
            SELECT COUNT(*) AS total FROM tb_item;
            """,  # Non-tenant view
        ]

        detector = TenantDetector()

        # Should detect multi-tenant
        assert detector.is_multi_tenant_schema(view_sqls) is True

        # Should detect 2 relationships (not the counts view)
        relationships = detector.detect_relationships(view_sqls)
        assert len(relationships) == 2

        # Build requirements map
        requirements = detector.build_requirements_map(relationships)
        assert "tb_item" in requirements
        assert "tb_order" in requirements
        assert requirements["tb_item"] == ["fk_org"]

    def test_custom_tenant_patterns(self):
        """Test with custom tenant column patterns (e.g., workspace_id)."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, w.id AS workspace_id
            FROM tb_item i
            JOIN tb_workspace w ON i.fk_workspace = w.id;
            """
        ]

        # Default patterns won't detect this
        detector_default = TenantDetector()
        assert detector_default.is_multi_tenant_schema(view_sqls) is False

        # Custom patterns will detect it
        detector_custom = TenantDetector(tenant_patterns=["workspace_id"])
        assert detector_custom.is_multi_tenant_schema(view_sqls) is True

        relationships = detector_custom.detect_relationships(view_sqls)
        assert len(relationships) == 1
        assert relationships[0].required_fk == "fk_workspace"


class TestFormatterWorkflow:
    """Integration tests for formatter workflow."""

    def test_format_complete_report(self):
        """Format complete report with relationships and violations."""
        # Run detection first
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.pk_organization AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]

        detector = TenantDetector()
        relationships = detector.detect_relationships(view_sqls)

        # Create a mock violation
        from confiture.core.linting.tenant.models import TenantViolation

        violations = [
            TenantViolation(
                function_name="fn_create_item",
                file_path="functions/items.sql",
                line_number=15,
                table_name="tb_item",
                missing_columns=["fk_org"],
                affected_views=["v_item"],
            )
        ]

        # Format output
        formatter = TenantIsolationFormatter()
        output = formatter.format_complete(
            relationships=relationships,
            violations=violations,
            functions_checked=5,
        )

        # Verify output contains all expected sections
        assert "multi-tenant patterns" in output.lower()
        assert "v_item" in output
        assert "tb_item" in output
        assert "fk_org" in output
        assert "fn_create_item" in output
        assert "Summary" in output


class TestEdgeCases:
    """Integration tests for edge cases."""

    def test_insert_without_column_list(self, tmp_path: Path):
        """INSERT without explicit column list is skipped (cannot analyze)."""
        views_dir = tmp_path / "views"
        functions_dir = tmp_path / "functions"
        views_dir.mkdir()
        functions_dir.mkdir()

        (views_dir / "v_item.sql").write_text("""
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # INSERT without column list
        (functions_dir / "fn_insert.sql").write_text("""
        CREATE FUNCTION fn_insert() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item VALUES (1, 'test', 123);
        END;
        $$ LANGUAGE plpgsql;
        """)

        rule = TenantIsolationRule()
        report = LintReport()

        rule.run_from_directories(
            view_dirs=[views_dir],
            function_dirs=[functions_dir],
            report=report,
        )

        # Cannot analyze INSERT without column list, so no violation
        assert report.total_violations == 0

    def test_schema_qualified_table_names(self, tmp_path: Path):
        """Schema-qualified table names are handled correctly."""
        views_dir = tmp_path / "views"
        functions_dir = tmp_path / "functions"
        views_dir.mkdir()
        functions_dir.mkdir()

        (views_dir / "v_item.sql").write_text("""
        CREATE VIEW myschema.v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM myschema.tb_item i
        JOIN myschema.tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # Function uses schema-qualified name
        (functions_dir / "fn_insert.sql").write_text("""
        CREATE FUNCTION fn_insert(p_name TEXT) RETURNS VOID AS $$
        BEGIN
            INSERT INTO myschema.tb_item (id, name) VALUES (1, p_name);
        END;
        $$ LANGUAGE plpgsql;
        """)

        rule = TenantIsolationRule()
        report = LintReport()

        rule.run_from_directories(
            view_dirs=[views_dir],
            function_dirs=[functions_dir],
            report=report,
        )

        # Should detect violation even with schema-qualified names
        assert report.total_violations == 1
        assert "fk_org" in report.warnings[0].message

    def test_case_insensitive_column_matching(self, tmp_path: Path):
        """Column names are matched case-insensitively."""
        views_dir = tmp_path / "views"
        functions_dir = tmp_path / "functions"
        views_dir.mkdir()
        functions_dir.mkdir()

        (views_dir / "v_item.sql").write_text("""
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # Function uses uppercase FK_ORG
        (functions_dir / "fn_insert.sql").write_text("""
        CREATE FUNCTION fn_insert(p_name TEXT, p_org BIGINT) RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id, name, FK_ORG) VALUES (1, p_name, p_org);
        END;
        $$ LANGUAGE plpgsql;
        """)

        rule = TenantIsolationRule()
        report = LintReport()

        rule.run_from_directories(
            view_dirs=[views_dir],
            function_dirs=[functions_dir],
            report=report,
        )

        # Should NOT report violation because FK_ORG matches fk_org
        assert report.total_violations == 0
