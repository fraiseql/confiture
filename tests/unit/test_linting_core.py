"""Tests for SchemaLinter orchestrator and LintRule base class."""

import pytest
from abc import ABC

from confiture.core.linting import SchemaLinter, LintRule
from confiture.models.lint import LintConfig, LintReport, Violation, LintSeverity


class TestLintRuleBase:
    """Tests for LintRule abstract base class."""

    def test_lint_rule_is_abstract(self):
        """LintRule should be abstract and not instantiable."""
        with pytest.raises(TypeError):
            LintRule()

    def test_lint_rule_subclass_requires_lint_method(self):
        """LintRule subclass must implement lint() method."""

        class IncompleteRule(LintRule):
            name = "IncompleteRule"
            description = "Test rule"

        # Should not be instantiable without lint() implementation
        with pytest.raises(TypeError):
            IncompleteRule()

    def test_lint_rule_subclass_can_be_created(self):
        """LintRule subclass with lint() implementation should work."""

        class CompleteRule(LintRule):
            name = "CompleteRule"
            description = "Test rule"

            def lint(self, tables, config):
                return []

        rule = CompleteRule()
        assert rule.name == "CompleteRule"
        assert rule.description == "Test rule"


class TestSchemaLinter:
    """Tests for SchemaLinter orchestrator."""

    def test_schema_linter_initialization_with_default_config(self):
        """SchemaLinter should initialize with test environment."""
        linter = SchemaLinter(env="test")

        assert linter.env == "test"
        assert linter.config is not None
        assert linter.config.enabled is True

    def test_schema_linter_initialization_with_custom_config(self):
        """SchemaLinter should accept custom config."""
        config = LintConfig(
            enabled=True,
            rules={"naming_convention": {"style": "PascalCase"}},
        )

        linter = SchemaLinter(env="test", config=config)

        assert linter.config == config
        assert linter.config.rules["naming_convention"]["style"] == "PascalCase"

    def test_schema_linter_registers_all_rules(self):
        """SchemaLinter should register all 6 built-in rules."""
        linter = SchemaLinter(env="test")

        assert len(linter.rules) == 6
        assert "naming_convention" in linter.rules
        assert "primary_key" in linter.rules
        assert "documentation" in linter.rules
        assert "multi_tenant" in linter.rules
        assert "missing_index" in linter.rules
        assert "security" in linter.rules

    def test_schema_linter_all_rules_are_lint_rule_instances(self):
        """All registered rules should be LintRule instances."""
        linter = SchemaLinter(env="test")

        for rule_name, rule in linter.rules.items():
            assert isinstance(rule, LintRule)
            assert hasattr(rule, "lint")
            assert hasattr(rule, "name")
            assert hasattr(rule, "description")

    def test_schema_linter_lint_returns_lint_report(self):
        """SchemaLinter.lint() should return LintReport."""
        linter = SchemaLinter(env="test")

        report = linter.lint()

        assert isinstance(report, LintReport)
        assert isinstance(report.violations, list)
        assert isinstance(report.schema_name, str)
        assert report.tables_checked >= 0
        assert report.columns_checked >= 0
        assert report.execution_time_ms > 0

    def test_schema_linter_report_has_violation_counts(self):
        """LintReport should have correct violation counts."""
        linter = SchemaLinter(env="test")

        report = linter.lint()

        assert report.errors_count >= 0
        assert report.warnings_count >= 0
        assert report.info_count >= 0
        assert len(report.violations) == (
            report.errors_count
            + report.warnings_count
            + report.info_count
        )

    def test_schema_linter_respects_excluded_tables(self):
        """SchemaLinter should skip excluded tables."""
        config = LintConfig.default()
        config.exclude_tables = ["nonexistent_table_*"]

        linter = SchemaLinter(env="test", config=config)

        report = linter.lint()

        # Should not crash and should return valid report
        assert isinstance(report, LintReport)

    def test_schema_linter_disabled_linting(self):
        """SchemaLinter with disabled config should still work."""
        config = LintConfig(enabled=False)

        linter = SchemaLinter(env="test", config=config)

        # Should still be able to create linter and run lint
        # (even if config says disabled)
        assert linter.config.enabled is False
