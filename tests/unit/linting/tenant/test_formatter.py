"""Tests for tenant isolation CLI output formatter."""

from confiture.core.linting.tenant.formatter import TenantIsolationFormatter
from confiture.core.linting.tenant.models import TenantRelationship, TenantViolation


class TestFormatRelationships:
    """Tests for formatting detected tenant relationships."""

    def test_format_single_relationship(self):
        """Format single tenant relationship."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            )
        ]

        formatter = TenantIsolationFormatter()
        output = formatter.format_relationships(relationships)

        assert "v_item" in output
        assert "tb_item" in output
        assert "fk_org" in output

    def test_format_multiple_relationships(self):
        """Format multiple tenant relationships."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_order",
                source_table="tb_order",
                required_fk="fk_customer",
            ),
        ]

        formatter = TenantIsolationFormatter()
        output = formatter.format_relationships(relationships)

        assert "v_item" in output
        assert "v_order" in output

    def test_format_empty_relationships(self):
        """Empty relationships returns empty string."""
        formatter = TenantIsolationFormatter()
        output = formatter.format_relationships([])

        assert output == ""


class TestFormatViolations:
    """Tests for formatting tenant violations."""

    def test_format_single_violation(self):
        """Format single violation with full details."""
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

        formatter = TenantIsolationFormatter()
        output = formatter.format_violations(violations)

        assert "fn_create_item" in output
        assert "functions/items.sql" in output
        assert "15" in output
        assert "fk_org" in output
        assert "v_item" in output

    def test_format_violation_includes_suggestion(self):
        """Formatted violation includes suggestion."""
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

        formatter = TenantIsolationFormatter()
        output = formatter.format_violations(violations)

        # Should include suggestion text
        assert "Add" in output or "suggestion" in output.lower()

    def test_format_multiple_missing_columns(self):
        """Format violation with multiple missing columns."""
        violations = [
            TenantViolation(
                function_name="fn_create_item",
                file_path="functions/items.sql",
                line_number=15,
                table_name="tb_item",
                missing_columns=["fk_org", "fk_dept"],
                affected_views=["v_item"],
            )
        ]

        formatter = TenantIsolationFormatter()
        output = formatter.format_violations(violations)

        assert "fk_org" in output
        assert "fk_dept" in output

    def test_format_empty_violations(self):
        """Empty violations returns empty string or success message."""
        formatter = TenantIsolationFormatter()
        output = formatter.format_violations([])

        # Either empty or success indicator
        assert output == "" or "no issues" in output.lower() or len(output) == 0


class TestFormatSummary:
    """Tests for formatting summary."""

    def test_format_summary_with_violations(self):
        """Format summary showing violation count."""
        formatter = TenantIsolationFormatter()
        output = formatter.format_summary(
            functions_checked=5,
            violations_found=2,
        )

        assert "5" in output
        assert "2" in output

    def test_format_summary_no_violations(self):
        """Format summary with no violations."""
        formatter = TenantIsolationFormatter()
        output = formatter.format_summary(
            functions_checked=5,
            violations_found=0,
        )

        assert "5" in output
        assert "0" in output or "no" in output.lower()


class TestFormatComplete:
    """Tests for complete formatted output."""

    def test_format_complete_output(self):
        """Format complete output with relationships and violations."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            )
        ]
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

        formatter = TenantIsolationFormatter()
        output = formatter.format_complete(
            relationships=relationships,
            violations=violations,
            functions_checked=5,
        )

        # Should have all sections
        assert "v_item" in output
        assert "fn_create_item" in output
        assert "fk_org" in output
