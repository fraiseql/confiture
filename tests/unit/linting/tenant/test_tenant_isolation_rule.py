"""Tests for TenantIsolationRule integration with schema linter."""

from pathlib import Path

from confiture.core.linting.schema_linter import LintReport, RuleSeverity
from confiture.core.linting.tenant.tenant_isolation_rule import TenantIsolationRule


class TestTenantIsolationRule:
    """Tests for the TenantIsolationRule linting rule."""

    def test_run_returns_empty_for_non_tenant_schema(self):
        """Non-tenant schema returns no violations."""
        view_sqls = [
            """
            CREATE VIEW v_counts AS
            SELECT COUNT(*) AS total FROM tb_item;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule()
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert report.total_violations == 0

    def test_run_detects_missing_fk_in_insert(self):
        """Detect missing FK column in INSERT statement."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.id, i.name, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule()
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert report.total_violations == 1
        assert report.warnings[0].rule_id == "tenant_001"
        assert "fk_org" in report.warnings[0].message

    def test_run_no_violation_when_fk_present(self):
        """No violation when INSERT includes required FK."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name, fk_org) VALUES (1, 'test', 123);
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule()
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert report.total_violations == 0

    def test_run_reports_affected_views(self):
        """Violation message includes affected views."""
        view_sqls = [
            """
            CREATE VIEW v_item_active AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization
            WHERE i.active = true;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule()
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert report.total_violations == 1
        assert "v_item_active" in report.warnings[0].message

    def test_severity_can_be_configured(self):
        """Rule severity can be configured."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule(severity=RuleSeverity.ERROR)
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert len(report.errors) == 1
        assert len(report.warnings) == 0

    def test_custom_tenant_patterns(self):
        """Custom tenant column patterns can be configured."""
        view_sqls = [
            """
            CREATE VIEW v_item AS
            SELECT i.*, w.id AS workspace_id
            FROM tb_item i
            JOIN tb_workspace w ON i.fk_workspace = w.id;
            """
        ]
        function_sqls = [
            """
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
            """
        ]

        rule = TenantIsolationRule(tenant_patterns=["workspace_id"])
        report = LintReport()
        rule.run(view_sqls=view_sqls, function_sqls=function_sqls, report=report)

        assert report.total_violations == 1
        assert "fk_workspace" in report.warnings[0].message


class TestTenantIsolationRuleFromFiles:
    """Tests for running rule against SQL files."""

    def test_run_from_files(self, tmp_path: Path):
        """Run rule against SQL files in directories."""
        # Create view file
        views_dir = tmp_path / "views"
        views_dir.mkdir()
        view_file = views_dir / "v_item.sql"
        view_file.write_text("""
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # Create function file
        functions_dir = tmp_path / "functions"
        functions_dir.mkdir()
        func_file = functions_dir / "fn_create_item.sql"
        func_file.write_text("""
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
            END;
            $$ LANGUAGE plpgsql;
        """)

        rule = TenantIsolationRule()
        report = LintReport()
        rule.run_from_files(
            view_paths=[view_file],
            function_paths=[func_file],
            report=report,
        )

        assert report.total_violations == 1
        violation = report.warnings[0]
        assert violation.file_path == str(func_file)
        assert "fk_org" in violation.message

    def test_run_from_directories(self, tmp_path: Path):
        """Run rule against SQL files in directories."""
        # Create view file
        views_dir = tmp_path / "views"
        views_dir.mkdir()
        (views_dir / "v_item.sql").write_text("""
            CREATE VIEW v_item AS
            SELECT i.*, o.id AS tenant_id
            FROM tb_item i
            JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # Create function file
        functions_dir = tmp_path / "functions"
        functions_dir.mkdir()
        (functions_dir / "fn_create_item.sql").write_text("""
            CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
            BEGIN
                INSERT INTO tb_item (id, name) VALUES (1, 'test');
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

        assert report.total_violations == 1


class TestTenantIsolationRuleMetadata:
    """Tests for rule metadata."""

    def test_rule_id(self):
        """Rule has correct ID."""
        rule = TenantIsolationRule()
        assert rule.rule_id == "tenant_001"

    def test_rule_name(self):
        """Rule has descriptive name."""
        rule = TenantIsolationRule()
        assert "tenant" in rule.rule_name.lower()

    def test_rule_description(self):
        """Rule has description."""
        rule = TenantIsolationRule()
        assert rule.description
        assert "INSERT" in rule.description or "FK" in rule.description
