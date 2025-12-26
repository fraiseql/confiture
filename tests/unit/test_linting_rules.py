"""Tests for individual linting rules."""

import pytest

from confiture.core.linting import (
    NamingConventionRule,
    PrimaryKeyRule,
    DocumentationRule,
    MultiTenantRule,
    MissingIndexRule,
    SecurityRule,
)
from confiture.models.lint import Violation, LintSeverity


# Mock Table and Column classes for testing
class MockColumn:
    """Mock Column for testing."""

    def __init__(
        self,
        name,
        column_type="TEXT",
        is_primary_key=False,
        is_foreign_key=False,
    ):
        self.name = name
        self.column_type = column_type
        self.is_primary_key = is_primary_key
        self.is_foreign_key = is_foreign_key


class MockIndex:
    """Mock Index for testing."""

    def __init__(self, name, columns):
        self.name = name
        self.columns = columns


class MockTable:
    """Mock Table for testing."""

    def __init__(self, name, columns=None, indexes=None, comment=None):
        self.name = name
        self.columns = columns or []
        self.indexes = indexes or []
        self.comment = comment


class TestNamingConventionRule:
    """Tests for NamingConventionRule."""

    def test_naming_rule_detects_camel_case_table(self):
        """Should detect table names not in snake_case."""
        rule = NamingConventionRule()
        tables = [MockTable(name="UserTable")]

        violations = rule.lint(tables, {"style": "snake_case"})

        assert len(violations) > 0
        assert any("UserTable" in v.message for v in violations)
        assert all(v.severity == LintSeverity.ERROR for v in violations)

    def test_naming_rule_detects_camel_case_columns(self):
        """Should detect column names not in snake_case."""
        rule = NamingConventionRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="userId"),
                    MockColumn(name="firstName"),
                ],
            )
        ]

        violations = rule.lint(tables, {"style": "snake_case"})

        assert any("userId" in v.message for v in violations)
        assert any("firstName" in v.message for v in violations)

    def test_naming_rule_accepts_snake_case(self):
        """Should not report violations for snake_case names."""
        rule = NamingConventionRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="user_id"),
                    MockColumn(name="first_name"),
                ],
            )
        ]

        violations = rule.lint(tables, {"style": "snake_case"})

        assert len(violations) == 0

    def test_naming_rule_suggests_fix(self):
        """Should suggest corrected name."""
        rule = NamingConventionRule()
        tables = [MockTable(name="UserTable")]

        violations = rule.lint(tables, {"style": "snake_case"})

        assert any("user_table" in v.suggested_fix for v in violations)


class TestPrimaryKeyRule:
    """Tests for PrimaryKeyRule."""

    def test_primary_key_rule_detects_missing_pk(self):
        """Should detect tables without PRIMARY KEY."""
        rule = PrimaryKeyRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id", is_primary_key=False),
                    MockColumn(name="name"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 1
        assert "PRIMARY KEY" in violations[0].message
        assert violations[0].severity == LintSeverity.ERROR

    def test_primary_key_rule_accepts_tables_with_pk(self):
        """Should not report for tables with PRIMARY KEY."""
        rule = PrimaryKeyRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id", is_primary_key=True),
                    MockColumn(name="name"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0

    def test_primary_key_rule_skips_system_tables(self):
        """Should skip pg_* system tables."""
        rule = PrimaryKeyRule()
        tables = [
            MockTable(
                name="pg_class",
                columns=[MockColumn(name="name")],  # No PK
            )
        ]

        violations = rule.lint(tables, {})

        # Should not report violation for system table
        assert len(violations) == 0


class TestDocumentationRule:
    """Tests for DocumentationRule."""

    def test_documentation_rule_detects_missing_comment(self):
        """Should detect tables without COMMENT."""
        rule = DocumentationRule()
        tables = [
            MockTable(
                name="users",
                columns=[MockColumn(name="id")],
                comment=None,
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 1
        assert "documentation" in violations[0].message.lower()
        assert violations[0].severity == LintSeverity.WARNING

    def test_documentation_rule_accepts_commented_tables(self):
        """Should not report for tables with COMMENT."""
        rule = DocumentationRule()
        tables = [
            MockTable(
                name="users",
                columns=[MockColumn(name="id")],
                comment="User accounts",
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0

    def test_documentation_rule_rejects_empty_comment(self):
        """Should reject empty or whitespace-only comments."""
        rule = DocumentationRule()
        tables = [
            MockTable(
                name="users",
                columns=[MockColumn(name="id")],
                comment="   ",
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 1

    def test_documentation_rule_suggests_fix(self):
        """Should suggest COMMENT statement."""
        rule = DocumentationRule()
        tables = [MockTable(name="users", comment=None)]

        violations = rule.lint(tables, {})

        assert any("COMMENT ON TABLE" in v.suggested_fix for v in violations)


class TestMultiTenantRule:
    """Tests for MultiTenantRule."""

    def test_multi_tenant_rule_detects_missing_tenant_id(self):
        """Should detect multi-tenant tables missing tenant_id."""
        rule = MultiTenantRule()
        tables = [
            MockTable(
                name="customers",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="name"),
                ],
            )
        ]

        violations = rule.lint(tables, {"identifier": "tenant_id"})

        assert len(violations) == 1
        assert "tenant_id" in violations[0].message
        assert violations[0].severity == LintSeverity.ERROR

    def test_multi_tenant_rule_accepts_with_tenant_id(self):
        """Should not report for tables with tenant_id."""
        rule = MultiTenantRule()
        tables = [
            MockTable(
                name="customers",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="tenant_id"),
                    MockColumn(name="name"),
                ],
            )
        ]

        violations = rule.lint(tables, {"identifier": "tenant_id"})

        assert len(violations) == 0

    def test_multi_tenant_rule_custom_identifier(self):
        """Should support custom tenant identifier name."""
        rule = MultiTenantRule()
        tables = [
            MockTable(
                name="customers",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="org_id"),
                ],
            )
        ]

        violations = rule.lint(tables, {"identifier": "org_id"})

        assert len(violations) == 0

    def test_multi_tenant_rule_skips_non_multi_tenant_tables(self):
        """Should not check tables that don't look multi-tenant."""
        rule = MultiTenantRule()
        tables = [
            MockTable(
                name="users",
                columns=[MockColumn(name="id")],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0


class TestMissingIndexRule:
    """Tests for MissingIndexRule."""

    def test_missing_index_rule_detects_unindexed_fk(self):
        """Should warn about unindexed foreign key columns."""
        rule = MissingIndexRule()
        tables = [
            MockTable(
                name="orders",
                columns=[
                    MockColumn(name="id", is_primary_key=True),
                    MockColumn(name="customer_id", is_foreign_key=True),
                ],
                indexes=[],  # No index on customer_id
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 1
        assert "customer_id" in violations[0].message
        assert violations[0].severity == LintSeverity.WARNING

    def test_missing_index_rule_accepts_indexed_fk(self):
        """Should not report for indexed foreign keys."""
        rule = MissingIndexRule()
        tables = [
            MockTable(
                name="orders",
                columns=[
                    MockColumn(name="id", is_primary_key=True),
                    MockColumn(name="customer_id", is_foreign_key=True),
                ],
                indexes=[MockIndex(name="idx_customer", columns=["customer_id"])],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0

    def test_missing_index_rule_ignores_non_fk_columns(self):
        """Should not check non-foreign-key columns."""
        rule = MissingIndexRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id", is_primary_key=True),
                    MockColumn(name="name", is_foreign_key=False),
                ],
                indexes=[],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0


class TestSecurityRule:
    """Tests for SecurityRule."""

    def test_security_rule_detects_password_column(self):
        """Should warn about password columns."""
        rule = SecurityRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="password", column_type="VARCHAR"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert any("password" in v.message.lower() for v in violations)
        assert any(v.severity == LintSeverity.WARNING for v in violations)

    def test_security_rule_detects_token_column(self):
        """Should warn about token columns."""
        rule = SecurityRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="api_token", column_type="VARCHAR"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert any("token" in v.message.lower() for v in violations)

    def test_security_rule_detects_secret_column(self):
        """Should warn about secret columns."""
        rule = SecurityRule()
        tables = [
            MockTable(
                name="config",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="secret_key", column_type="TEXT"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert any("secret" in v.message.lower() for v in violations)

    def test_security_rule_ignores_non_sensitive_columns(self):
        """Should not warn about non-sensitive columns."""
        rule = SecurityRule()
        tables = [
            MockTable(
                name="users",
                columns=[
                    MockColumn(name="id"),
                    MockColumn(name="name", column_type="VARCHAR"),
                    MockColumn(name="email", column_type="VARCHAR"),
                ],
            )
        ]

        violations = rule.lint(tables, {})

        assert len(violations) == 0

    def test_security_rule_suggests_hashing_for_passwords(self):
        """Should suggest bcrypt/argon2 for passwords."""
        rule = SecurityRule()
        tables = [
            MockTable(
                name="users",
                columns=[MockColumn(name="password", column_type="VARCHAR")],
            )
        ]

        violations = rule.lint(tables, {})

        assert any(
            ("bcrypt" in v.suggested_fix.lower() or "hashing" in v.suggested_fix.lower())
            for v in violations
        )
