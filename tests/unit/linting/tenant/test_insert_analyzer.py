"""Tests for INSERT analyzer for missing tenant columns."""

from confiture.core.linting.tenant.function_parser import InsertStatement
from confiture.core.linting.tenant.insert_analyzer import InsertAnalyzer


class TestFindMissingColumns:
    """Tests for detecting missing tenant FK columns in INSERT statements."""

    def test_detect_missing_fk_column(self):
        """Detect when INSERT is missing required FK column."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == ["fk_org"]

    def test_no_missing_when_fk_present(self):
        """No missing columns when FK is included."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name", "fk_org"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name, fk_org) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == []

    def test_no_requirements_for_table(self):
        """No violations for tables without tenant requirements."""
        insert = InsertStatement(
            table_name="tb_audit_log",
            columns=["id", "action"],
            line_number=15,
            raw_sql="INSERT INTO tb_audit_log (id, action) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}  # Different table

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == []

    def test_multiple_missing_columns(self):
        """Detect multiple missing FK columns."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org", "fk_dept"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert set(missing) == {"fk_org", "fk_dept"}

    def test_partial_missing_columns(self):
        """Detect some but not all missing FK columns."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name", "fk_org"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name, fk_org) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org", "fk_dept"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == ["fk_dept"]

    def test_unknown_columns_returns_none(self):
        """INSERT without column list cannot be analyzed."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=None,  # No column list
            line_number=15,
            raw_sql="INSERT INTO tb_item VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        # Returns None to indicate cannot analyze
        assert missing is None

    def test_schema_qualified_table_matches(self):
        """Schema-qualified table name matches requirements."""
        insert = InsertStatement(
            table_name="myschema.tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO myschema.tb_item (id, name) VALUES (...)",
        )

        # Requirements may or may not include schema
        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == ["fk_org"]

    def test_case_insensitive_column_match(self):
        """Column matching is case-insensitive."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name", "FK_ORG"],  # Uppercase
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name, FK_ORG) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}  # Lowercase

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == []


class TestBuildViolation:
    """Tests for building TenantViolation from analysis results."""

    def test_build_violation_from_analysis(self):
        """Create TenantViolation from analysis results."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        analyzer = InsertAnalyzer()
        violation = analyzer.build_violation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            insert=insert,
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert violation.function_name == "fn_create_item"
        assert violation.file_path == "functions/fn_create_item.sql"
        assert violation.line_number == 15
        assert violation.table_name == "tb_item"
        assert violation.missing_columns == ["fk_org"]
        assert violation.affected_views == ["v_item"]

    def test_violation_includes_suggestion(self):
        """Built violation includes actionable suggestion."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        analyzer = InsertAnalyzer()
        violation = analyzer.build_violation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            insert=insert,
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert "fk_org" in violation.suggestion
        assert "v_item" in violation.suggestion

    def test_violation_includes_raw_sql(self):
        """Built violation includes raw INSERT SQL."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (1, 'test')",
        )

        analyzer = InsertAnalyzer()
        violation = analyzer.build_violation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            insert=insert,
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert violation.insert_sql == "INSERT INTO tb_item (id, name) VALUES (1, 'test')"


class TestAnalyzeFunction:
    """Tests for analyzing a complete function."""

    def test_analyze_function_with_violation(self):
        """Analyze function and return violations."""
        from confiture.core.linting.tenant.function_parser import FunctionInfo

        func = FunctionInfo(
            name="fn_create_item",
            body="BEGIN INSERT INTO tb_item (id, name) VALUES (1, 'test'); END;",
            inserts=[
                InsertStatement(
                    table_name="tb_item",
                    columns=["id", "name"],
                    line_number=1,
                    raw_sql="INSERT INTO tb_item (id, name) VALUES (1, 'test')",
                )
            ],
        )

        requirements = {"tb_item": ["fk_org"]}
        view_map = {"tb_item": ["v_item"]}

        analyzer = InsertAnalyzer()
        violations = analyzer.analyze_function(
            func,
            requirements=requirements,
            view_map=view_map,
            file_path="functions/items.sql",
        )

        assert len(violations) == 1
        assert violations[0].function_name == "fn_create_item"
        assert violations[0].missing_columns == ["fk_org"]

    def test_analyze_function_no_violations(self):
        """Analyze function with correct INSERT returns no violations."""
        from confiture.core.linting.tenant.function_parser import FunctionInfo

        func = FunctionInfo(
            name="fn_create_item",
            body="BEGIN INSERT INTO tb_item (id, name, fk_org) VALUES (1, 'test', 123); END;",
            inserts=[
                InsertStatement(
                    table_name="tb_item",
                    columns=["id", "name", "fk_org"],
                    line_number=1,
                    raw_sql="INSERT INTO tb_item (id, name, fk_org) VALUES (1, 'test', 123)",
                )
            ],
        )

        requirements = {"tb_item": ["fk_org"]}
        view_map = {"tb_item": ["v_item"]}

        analyzer = InsertAnalyzer()
        violations = analyzer.analyze_function(
            func,
            requirements=requirements,
            view_map=view_map,
            file_path="functions/items.sql",
        )

        assert violations == []

    def test_analyze_function_multiple_inserts(self):
        """Analyze function with multiple INSERT statements."""
        from confiture.core.linting.tenant.function_parser import FunctionInfo

        func = FunctionInfo(
            name="fn_create_items",
            body="...",
            inserts=[
                InsertStatement(
                    table_name="tb_item",
                    columns=["id", "name"],  # Missing fk_org
                    line_number=5,
                    raw_sql="INSERT INTO tb_item ...",
                ),
                InsertStatement(
                    table_name="tb_item",
                    columns=["id", "name", "fk_org"],  # Correct
                    line_number=10,
                    raw_sql="INSERT INTO tb_item ...",
                ),
            ],
        )

        requirements = {"tb_item": ["fk_org"]}
        view_map = {"tb_item": ["v_item"]}

        analyzer = InsertAnalyzer()
        violations = analyzer.analyze_function(
            func,
            requirements=requirements,
            view_map=view_map,
            file_path="functions/items.sql",
        )

        # Only the first INSERT should have a violation
        assert len(violations) == 1
        assert violations[0].line_number == 5
