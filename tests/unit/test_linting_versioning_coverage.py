"""Comprehensive tests for linting rule versioning and compatibility.

Tests the rule versioning system including semantic versioning,
deprecation tracking, and compatibility management.
"""

import logging

import pytest

from confiture.core.linting.versioning import (
    LintSeverity,
    Rule,
    RuleRemovedError,
    RuleVersion,
    RuleVersionManager,
)


class TestLintSeverity:
    """Test LintSeverity enum."""

    def test_severity_info(self):
        """Test INFO severity level."""
        assert LintSeverity.INFO.value == "info"

    def test_severity_warning(self):
        """Test WARNING severity level."""
        assert LintSeverity.WARNING.value == "warning"

    def test_severity_error(self):
        """Test ERROR severity level."""
        assert LintSeverity.ERROR.value == "error"

    def test_severity_critical(self):
        """Test CRITICAL severity level."""
        assert LintSeverity.CRITICAL.value == "critical"

    def test_all_severities_defined(self):
        """Test all severity levels are defined."""
        severities = list(LintSeverity)
        assert len(severities) == 4

    def test_severity_comparison(self):
        """Test severity enum members."""
        assert LintSeverity.INFO != LintSeverity.WARNING
        assert LintSeverity.ERROR != LintSeverity.CRITICAL


class TestRuleVersion:
    """Test RuleVersion dataclass."""

    def test_create_version_minimal(self):
        """Test creating version with minimal fields."""
        version = RuleVersion(major=1, minor=0, patch=0)
        assert version.major == 1
        assert version.minor == 0
        assert version.patch == 0

    def test_version_string_representation(self):
        """Test version string formatting."""
        version = RuleVersion(major=2, minor=3, patch=4)
        assert str(version) == "2.3.4"

    def test_version_string_with_zeros(self):
        """Test version string with zero components."""
        version = RuleVersion(major=1, minor=0, patch=0)
        assert str(version) == "1.0.0"

    def test_version_compatibility_same_major(self):
        """Test compatibility check with same major version."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=5, patch=3)
        assert v1.is_compatible_with(v2)

    def test_version_compatibility_different_major(self):
        """Test compatibility check with different major version."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        assert not v1.is_compatible_with(v2)

    def test_version_compatibility_reflexive(self):
        """Test version is compatible with itself."""
        v = RuleVersion(major=1, minor=2, patch=3)
        assert v.is_compatible_with(v)

    def test_version_less_than_or_equal_true(self):
        """Test less than or equal operator (true case)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=1, patch=0)
        assert v1 <= v2

    def test_version_less_than_or_equal_equal(self):
        """Test less than or equal operator (equal case)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert v1 <= v2

    def test_version_less_than_or_equal_false(self):
        """Test less than or equal operator (false case)."""
        v1 = RuleVersion(major=2, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=1, patch=0)
        assert not v1 <= v2

    def test_version_greater_than_or_equal_true(self):
        """Test greater than or equal operator (true case)."""
        v1 = RuleVersion(major=2, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=1, patch=0)
        assert v1 >= v2

    def test_version_greater_than_or_equal_equal(self):
        """Test greater than or equal operator (equal case)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert v1 >= v2

    def test_version_greater_than_or_equal_false(self):
        """Test greater than or equal operator (false case)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=1, patch=0)
        assert not v1 >= v2

    def test_version_less_than_true(self):
        """Test less than operator (true case)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=1, patch=0)
        assert v1 < v2

    def test_version_less_than_false(self):
        """Test less than operator (false case - equal)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert not v1 < v2

    def test_version_less_than_false_greater(self):
        """Test less than operator (false - greater)."""
        v1 = RuleVersion(major=2, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert not v1 < v2

    def test_version_greater_than_true(self):
        """Test greater than operator (true case)."""
        v1 = RuleVersion(major=2, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert v1 > v2

    def test_version_greater_than_false(self):
        """Test greater than operator (false case - equal)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=0, patch=0)
        assert not v1 > v2

    def test_version_greater_than_false_less(self):
        """Test greater than operator (false - less)."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        assert not v1 > v2

    def test_version_equality_true(self):
        """Test equality operator (true case)."""
        v1 = RuleVersion(major=1, minor=2, patch=3)
        v2 = RuleVersion(major=1, minor=2, patch=3)
        assert v1 == v2

    def test_version_equality_false_major(self):
        """Test equality operator (false - major different)."""
        v1 = RuleVersion(major=1, minor=2, patch=3)
        v2 = RuleVersion(major=2, minor=2, patch=3)
        assert v1 != v2

    def test_version_equality_false_minor(self):
        """Test equality operator (false - minor different)."""
        v1 = RuleVersion(major=1, minor=2, patch=3)
        v2 = RuleVersion(major=1, minor=3, patch=3)
        assert v1 != v2

    def test_version_equality_false_patch(self):
        """Test equality operator (false - patch different)."""
        v1 = RuleVersion(major=1, minor=2, patch=3)
        v2 = RuleVersion(major=1, minor=2, patch=4)
        assert v1 != v2

    def test_version_ordering_major(self):
        """Test version ordering by major version."""
        versions = [
            RuleVersion(major=3, minor=0, patch=0),
            RuleVersion(major=1, minor=0, patch=0),
            RuleVersion(major=2, minor=0, patch=0),
        ]
        sorted_versions = sorted(versions)
        assert sorted_versions[0].major == 1
        assert sorted_versions[1].major == 2
        assert sorted_versions[2].major == 3

    def test_version_ordering_minor(self):
        """Test version ordering by minor version."""
        versions = [
            RuleVersion(major=1, minor=3, patch=0),
            RuleVersion(major=1, minor=1, patch=0),
            RuleVersion(major=1, minor=2, patch=0),
        ]
        sorted_versions = sorted(versions)
        assert sorted_versions[0].minor == 1
        assert sorted_versions[1].minor == 2
        assert sorted_versions[2].minor == 3

    def test_version_ordering_patch(self):
        """Test version ordering by patch version."""
        versions = [
            RuleVersion(major=1, minor=0, patch=3),
            RuleVersion(major=1, minor=0, patch=1),
            RuleVersion(major=1, minor=0, patch=2),
        ]
        sorted_versions = sorted(versions)
        assert sorted_versions[0].patch == 1
        assert sorted_versions[1].patch == 2
        assert sorted_versions[2].patch == 3


class TestRule:
    """Test Rule dataclass."""

    def test_create_rule_minimal(self):
        """Test creating rule with minimal fields."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="test_rule",
            description="Test rule",
            version=version,
        )
        assert rule.rule_id == "RULE-001"
        assert rule.name == "test_rule"
        assert rule.description == "Test rule"
        assert rule.version == version
        assert rule.deprecated_in is None
        assert rule.removed_in is None
        assert rule.migration_path is None
        assert rule.severity == LintSeverity.WARNING
        assert rule.enabled_by_default is True

    def test_create_rule_with_deprecation(self):
        """Test creating rule with deprecation info."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        assert rule.deprecated_in == v2

    def test_create_rule_with_removal(self):
        """Test creating rule with removal info."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=3, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
        )
        assert rule.removed_in == v2

    def test_create_rule_with_severity(self):
        """Test creating rule with custom severity."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="critical_rule",
            description="Critical rule",
            version=version,
            severity=LintSeverity.CRITICAL,
        )
        assert rule.severity == LintSeverity.CRITICAL

    def test_create_rule_disabled_by_default(self):
        """Test creating rule disabled by default."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="optional_rule",
            description="Optional rule",
            version=version,
            enabled_by_default=False,
        )
        assert rule.enabled_by_default is False

    def test_rule_is_deprecated_no_deprecation(self):
        """Test is_deprecated when rule not deprecated."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="active_rule",
            description="Active rule",
            version=version,
        )
        assert rule.is_deprecated() is False

    def test_rule_is_deprecated_with_deprecation(self):
        """Test is_deprecated when rule is deprecated."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        assert rule.is_deprecated() is True

    def test_rule_is_deprecated_target_before_deprecation(self):
        """Test is_deprecated with target version before deprecation."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v_target = RuleVersion(major=1, minor=5, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        assert rule.is_deprecated(v_target) is False

    def test_rule_is_deprecated_target_at_deprecation(self):
        """Test is_deprecated with target version at deprecation."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        assert rule.is_deprecated(v2) is True

    def test_rule_is_deprecated_target_after_deprecation(self):
        """Test is_deprecated with target version after deprecation."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v_target = RuleVersion(major=3, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        assert rule.is_deprecated(v_target) is True

    def test_rule_is_removed_no_removal(self):
        """Test is_removed when rule not removed."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="active_rule",
            description="Active rule",
            version=version,
        )
        assert rule.is_removed() is False

    def test_rule_is_removed_with_removal(self):
        """Test is_removed when rule is removed."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=3, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
        )
        assert rule.is_removed() is True

    def test_rule_is_removed_target_before_removal(self):
        """Test is_removed with target version before removal."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=3, minor=0, patch=0)
        v_target = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
        )
        assert rule.is_removed(v_target) is False

    def test_rule_is_removed_target_at_removal(self):
        """Test is_removed with target version at removal."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=3, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
        )
        assert rule.is_removed(v2) is True

    def test_rule_is_removed_target_after_removal(self):
        """Test is_removed with target version after removal."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=3, minor=0, patch=0)
        v_target = RuleVersion(major=4, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
        )
        assert rule.is_removed(v_target) is True

    def test_rule_with_migration_path(self):
        """Test rule with migration path."""
        version = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=version,
            migration_path="https://docs.example.com/migrate-rule-001",
        )
        assert rule.migration_path == "https://docs.example.com/migrate-rule-001"


class TestRuleRemovedError:
    """Test RuleRemovedError exception."""

    def test_rule_removed_error_is_exception(self):
        """Test RuleRemovedError is proper Exception."""
        error = RuleRemovedError("Rule removed")
        assert isinstance(error, Exception)

    def test_rule_removed_error_message(self):
        """Test RuleRemovedError message."""
        error = RuleRemovedError("Rule RULE-001 was removed")
        assert "RULE-001" in str(error)

    def test_rule_removed_error_can_be_raised(self):
        """Test RuleRemovedError can be raised and caught."""
        with pytest.raises(RuleRemovedError) as exc_info:
            raise RuleRemovedError("Test error")
        assert "Test error" in str(exc_info.value)


class TestRuleVersionManager:
    """Test RuleVersionManager class."""

    def test_manager_initialization_empty(self):
        """Test manager initialization with empty rules."""
        manager = RuleVersionManager([])
        assert len(manager.rules) == 0

    def test_manager_initialization_with_rules(self):
        """Test manager initialization with rules."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        rules = [
            Rule(rule_id="R1", name="rule1", description="Rule 1", version=v1),
            Rule(rule_id="R2", name="rule2", description="Rule 2", version=v1),
        ]
        manager = RuleVersionManager(rules)
        assert len(manager.rules) == 2
        assert "R1" in manager.rules
        assert "R2" in manager.rules

    def test_get_rule_existing(self):
        """Test getting existing rule."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        rule = Rule(rule_id="RULE-001", name="test_rule", description="Test", version=v1)
        manager = RuleVersionManager([rule])

        retrieved = manager.get_rule("RULE-001")

        assert retrieved == rule
        assert retrieved.rule_id == "RULE-001"

    def test_get_rule_nonexistent(self):
        """Test getting nonexistent rule."""
        manager = RuleVersionManager([])

        result = manager.get_rule("NONEXISTENT")

        assert result is None

    def test_get_rule_removed_raises_error(self):
        """Test getting removed rule raises RuleRemovedError."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="removed_rule",
            description="Removed rule",
            version=v1,
            removed_in=v2,
            migration_path="Use RULE-002 instead",
        )
        manager = RuleVersionManager([rule])

        with pytest.raises(RuleRemovedError) as exc_info:
            manager.get_rule("RULE-001", target_version=v2)

        assert "RULE-001" in str(exc_info.value)
        assert "RULE-002" in str(exc_info.value)

    def test_get_rule_deprecated_logs_warning(self, caplog):
        """Test getting deprecated rule logs warning."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
            migration_path="Use new format",
        )
        manager = RuleVersionManager([rule])

        with caplog.at_level(logging.WARNING):
            retrieved = manager.get_rule("RULE-001", target_version=v2)

        assert retrieved == rule
        assert "RULE-001" in caplog.text
        assert "deprecated" in caplog.text.lower()

    def test_get_rule_deprecated_before_version(self, caplog):
        """Test getting deprecated rule before deprecation version."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v_target = RuleVersion(major=1, minor=5, patch=0)
        rule = Rule(
            rule_id="RULE-001",
            name="deprecated_rule",
            description="Deprecated rule",
            version=v1,
            deprecated_in=v2,
        )
        manager = RuleVersionManager([rule])

        with caplog.at_level(logging.WARNING):
            retrieved = manager.get_rule("RULE-001", target_version=v_target)

        assert retrieved == rule
        # Should not log warning for version before deprecation
        assert "deprecated" not in caplog.text.lower()

    def test_validate_compatibility_all_compatible(self):
        """Test validate_compatibility when all rules are compatible."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=1, minor=5, patch=0)
        rules = [
            Rule(rule_id="R1", name="rule1", description="Rule 1", version=v1),
            Rule(rule_id="R2", name="rule2", description="Rule 2", version=v1),
        ]
        manager = RuleVersionManager(rules)

        incompatible = manager.validate_compatibility(v2, v1)

        assert incompatible == []

    def test_validate_compatibility_some_incompatible(self):
        """Test validate_compatibility with incompatible rules."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v_check = RuleVersion(major=1, minor=0, patch=0)
        rules = [
            Rule(rule_id="R1", name="rule1", description="Rule 1", version=v1),
            Rule(rule_id="R2", name="rule2", description="Rule 2", version=v2),
        ]
        manager = RuleVersionManager(rules)

        incompatible = manager.validate_compatibility(v_check, v_check)

        assert len(incompatible) == 1
        assert "R2" in incompatible

    def test_validate_compatibility_all_incompatible(self):
        """Test validate_compatibility when all rules incompatible."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        rules = [
            Rule(rule_id="R1", name="rule1", description="Rule 1", version=v1),
            Rule(rule_id="R2", name="rule2", description="Rule 2", version=v1),
        ]
        manager = RuleVersionManager(rules)

        incompatible = manager.validate_compatibility(v2, v2)

        assert len(incompatible) == 2
        assert "R1" in incompatible
        assert "R2" in incompatible

    def test_validate_compatibility_empty_rules(self):
        """Test validate_compatibility with no rules."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        manager = RuleVersionManager([])

        incompatible = manager.validate_compatibility(v1, v1)

        assert incompatible == []


class TestRuleVersioningIntegration:
    """Integration tests for rule versioning system."""

    def test_complete_rule_lifecycle(self):
        """Test complete rule lifecycle."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v3 = RuleVersion(major=3, minor=0, patch=0)

        rule = Rule(
            rule_id="RULE-001",
            name="evolving_rule",
            description="Rule that evolves",
            version=v1,
            deprecated_in=v2,
            removed_in=v3,
            migration_path="https://docs.example.com",
            severity=LintSeverity.ERROR,
        )

        manager = RuleVersionManager([rule])

        # At v1, rule is active
        assert manager.get_rule("RULE-001", v1).rule_id == "RULE-001"

        # At v2, rule is deprecated but still available
        result = manager.get_rule("RULE-001", v2)
        assert result.rule_id == "RULE-001"
        assert result.is_deprecated(v2)

        # At v3, rule is removed
        with pytest.raises(RuleRemovedError):
            manager.get_rule("RULE-001", v3)

    def test_multi_rule_versioning_scenario(self):
        """Test versioning with multiple rules at different stages."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        v3 = RuleVersion(major=3, minor=0, patch=0)

        rules = [
            Rule(rule_id="RULE-001", name="active", description="Active", version=v1),
            Rule(
                rule_id="RULE-002",
                name="deprecated",
                description="Deprecated",
                version=v1,
                deprecated_in=v2,
            ),
            Rule(
                rule_id="RULE-003",
                name="removed",
                description="Removed",
                version=v1,
                removed_in=v3,
            ),
        ]

        manager = RuleVersionManager(rules)

        # Get active rule
        assert manager.get_rule("RULE-001") is not None

        # Get deprecated rule
        assert manager.get_rule("RULE-002", v2) is not None

        # Get removed rule should fail
        with pytest.raises(RuleRemovedError):
            manager.get_rule("RULE-003", v3)

    def test_rule_compatibility_across_versions(self):
        """Test rule compatibility checking across versions."""
        v1 = RuleVersion(major=1, minor=0, patch=0)
        v2 = RuleVersion(major=2, minor=0, patch=0)
        RuleVersion(major=3, minor=0, patch=0)

        rules = [
            Rule(rule_id="R-V1", name="rule_v1", description="V1 Rule", version=v1),
            Rule(rule_id="R-V2", name="rule_v2", description="V2 Rule", version=v2),
        ]

        manager = RuleVersionManager(rules)

        # Check compatibility with v1
        incompatible_v1 = manager.validate_compatibility(v1, v1)
        assert "R-V2" in incompatible_v1  # v2 rules not compatible with v1

        # Check compatibility with v2
        incompatible_v2 = manager.validate_compatibility(v2, v2)
        assert "R-V1" in incompatible_v2  # v1 rules not compatible with v2 system
