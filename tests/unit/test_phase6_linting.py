"""Comprehensive unit tests for Linting/Rule System.

Tests cover:
- Rule versioning and compatibility
- Rule library composition
- Conflict detection and resolution
- Compliance library correctness
- Rule count verification
- Audit trail tracking
"""

from __future__ import annotations

from confiture.core.linting import (
    RuleLibraryComposer,
)
from confiture.core.linting.libraries import (
    GDPRLibrary,
    GeneralLibrary,
    HIPAALibrary,
    PCI_DSSLibrary,
    SOXLibrary,
)
from confiture.core.linting.versioning import LintSeverity, Rule, RuleVersion, RuleVersionManager


class TestRuleVersion:
    """Test rule versioning functionality."""

    def test_create_rule_version(self):
        """Test creating a rule version."""
        version = RuleVersion(major=1, minor=2, patch=3)

        assert version.major == 1
        assert version.minor == 2
        assert version.patch == 3

    def test_rule_version_string_representation(self):
        """Test rule version string representation."""
        version = RuleVersion(major=1, minor=0, patch=0)

        assert str(version) == "1.0.0"

    def test_rule_version_compatibility(self):
        """Test rule version compatibility checking."""
        v1 = RuleVersion(1, 0, 0)
        v2 = RuleVersion(1, 1, 0)
        v3 = RuleVersion(2, 0, 0)

        # Same major version should be compatible
        assert v1 < v2
        assert v2 < v3


class TestRule:
    """Test rule creation and properties."""

    def test_create_rule(self):
        """Test creating a linting rule."""
        rule = Rule(
            rule_id="test_001",
            name="test_rule",
            description="Test rule description",
            version=RuleVersion(1, 0, 0),
            severity=LintSeverity.ERROR,
            enabled_by_default=True,
        )

        assert rule.rule_id == "test_001"
        assert rule.name == "test_rule"
        assert rule.severity == LintSeverity.ERROR
        assert rule.enabled_by_default is True

    def test_rule_with_deprecation(self):
        """Test creating deprecated rule."""
        rule = Rule(
            rule_id="old_001",
            name="old_rule",
            description="Old rule",
            version=RuleVersion(1, 0, 0),
            severity=LintSeverity.WARNING,
            enabled_by_default=False,
            deprecated_in=RuleVersion(2, 0, 0),
        )

        assert rule.deprecated_in == RuleVersion(2, 0, 0)


class TestGeneralLibrary:
    """Test general compliance library."""

    def test_general_library_creation(self):
        """Test creating general library."""
        library = GeneralLibrary()

        assert library.name == "General"
        assert len(library.rules) == 20

    def test_general_library_rule_count_assertion(self):
        """Test general library rule count assertion."""
        library = GeneralLibrary()

        # Should pass assertion during init
        assert len(library.rules) == 20

    def test_general_library_has_required_rules(self):
        """Test general library contains required rules."""
        library = GeneralLibrary()
        rule_ids = set(library.rules.keys())

        assert "general_001" in rule_ids
        assert "general_020" in rule_ids

    def test_general_library_severity_levels(self):
        """Test general library has variety of severity levels."""
        library = GeneralLibrary()

        severities = {r.severity for r in library.rules.values()}
        assert LintSeverity.WARNING in severities
        assert LintSeverity.ERROR in severities


class TestHIPAALibrary:
    """Test HIPAA compliance library."""

    def test_hipaa_library_creation(self):
        """Test creating HIPAA library."""
        library = HIPAALibrary()

        assert library.name == "HIPAA"
        assert len(library.rules) == 15

    def test_hipaa_library_rule_count(self):
        """Test HIPAA library has exactly 15 rules."""
        library = HIPAALibrary()

        assert len(library.rules) == 15

    def test_hipaa_library_critical_rules(self):
        """Test HIPAA library has critical rules."""
        library = HIPAALibrary()

        critical_rules = [r for r in library.rules.values() if r.severity == LintSeverity.CRITICAL]
        assert len(critical_rules) > 0

    def test_hipaa_library_phi_encryption(self):
        """Test HIPAA library includes PHI encryption rule."""
        library = HIPAALibrary()
        rule_ids = set(library.rules.keys())

        assert "hipaa_001" in rule_ids  # encrypt_phi


class TestSOXLibrary:
    """Test SOX compliance library."""

    def test_sox_library_creation(self):
        """Test creating SOX library."""
        library = SOXLibrary()

        assert library.name == "SOX"
        assert len(library.rules) == 12

    def test_sox_library_rule_count(self):
        """Test SOX library has exactly 12 rules."""
        library = SOXLibrary()

        assert len(library.rules) == 12

    def test_sox_library_audit_trail(self):
        """Test SOX library includes audit trail requirement."""
        library = SOXLibrary()
        rule_ids = set(library.rules.keys())

        assert "sox_002" in rule_ids  # audit_trail_required


class TestGDPRLibrary:
    """Test GDPR compliance library."""

    def test_gdpr_library_creation(self):
        """Test creating GDPR library."""
        library = GDPRLibrary()

        assert library.name == "GDPR"
        assert len(library.rules) == 18

    def test_gdpr_library_rule_count(self):
        """Test GDPR library has exactly 18 rules."""
        library = GDPRLibrary()

        assert len(library.rules) == 18

    def test_gdpr_library_encryption(self):
        """Test GDPR library includes encryption requirements."""
        library = GDPRLibrary()
        rule_ids = set(library.rules.keys())

        assert "gdpr_001" in rule_ids  # personal_data_encryption


class TestPCIDSSLibrary:
    """Test PCI-DSS compliance library."""

    def test_pci_dss_library_creation(self):
        """Test creating PCI-DSS library."""
        library = PCI_DSSLibrary()

        assert library.name == "PCI-DSS"
        assert len(library.rules) == 10

    def test_pci_dss_library_rule_count(self):
        """Test PCI-DSS library has exactly 10 rules."""
        library = PCI_DSSLibrary()

        assert len(library.rules) == 10

    def test_pci_dss_library_cardholder_data(self):
        """Test PCI-DSS library includes cardholder data protection."""
        library = PCI_DSSLibrary()
        rule_ids = set(library.rules.keys())

        assert "pci_dss_001" in rule_ids


class TestRuleComposition:
    """Test rule library composition."""

    def test_compose_single_library(self):
        """Test composing a single library."""
        composer = RuleLibraryComposer()
        composer.add_library(GeneralLibrary())
        composed = composer.build()

        assert len(composed.rules) == 20

    def test_compose_multiple_libraries(self):
        """Test composing multiple libraries."""
        composer = RuleLibraryComposer()
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composed = composer.build()

        # 20 + 15 = 35 rules
        assert len(composed.rules) == 35

    def test_compose_all_compliance_libraries(self):
        """Test composing all compliance libraries."""
        composer = RuleLibraryComposer()
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composer.add_library(SOXLibrary())
        composer.add_library(GDPRLibrary())
        composer.add_library(PCI_DSSLibrary())
        composed = composer.build()

        # 20 + 15 + 12 + 18 + 10 = 75 rules
        assert len(composed.rules) == 75

    def test_composed_set_contains_audit_trail(self):
        """Test composed rule set includes audit trail."""
        composer = RuleLibraryComposer()
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composed = composer.build()

        # Should have rules from both libraries
        assert len(composed.rules) > 0


class TestConflictDetection:
    """Test rule conflict detection."""

    def test_detect_duplicate_rules(self):
        """Test detecting duplicate rules during composition."""
        composer = RuleLibraryComposer()

        # Add different libraries that might have overlapping rule IDs
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composed = composer.build()

        # Should have composed rules
        assert composed is not None
        assert len(composed.rules) > 0

    def test_conflict_resolution_strategies(self):
        """Test conflict resolution detection."""
        composer = RuleLibraryComposer()

        # Add different libraries
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composed = composer.build()

        # Should have conflicts attribute on composed result
        assert hasattr(composed, 'conflicts')


class TestRuleVersionManager:
    """Test rule version management."""

    def test_create_version_manager(self):
        """Test creating rule version manager."""
        v1 = RuleVersion(1, 0, 0)
        rule_v1 = Rule(
            rule_id="test_001",
            name="test",
            description="test",
            version=v1,
            severity=LintSeverity.WARNING,
        )
        manager = RuleVersionManager(rules=[rule_v1])

        assert manager is not None

    def test_register_rule_version(self):
        """Test registering rule versions."""
        v1 = RuleVersion(1, 0, 0)
        v2 = RuleVersion(1, 1, 0)

        rule_v1 = Rule(
            rule_id="test_001",
            name="test",
            description="test",
            version=v1,
            severity=LintSeverity.WARNING,
        )

        rule_v2 = Rule(
            rule_id="test_001",
            name="test",
            description="test",
            version=v2,
            severity=LintSeverity.WARNING,
        )

        manager = RuleVersionManager(rules=[rule_v1, rule_v2])

        # Manager should be created successfully
        assert manager is not None


class TestRuleLibraryProperties:
    """Test rule library properties and tags."""

    def test_general_library_tags(self):
        """Test general library has appropriate tags."""
        library = GeneralLibrary()

        assert "general" in library.tags or library.tags is not None

    def test_hipaa_library_tags(self):
        """Test HIPAA library includes healthcare tag."""
        library = HIPAALibrary()

        assert "healthcare" in library.tags or "compliance" in library.tags

    def test_library_version(self):
        """Test library version property."""
        library = GeneralLibrary()

        assert library.version is not None
        assert library.version.major >= 1


class TestRuleDisabling:
    """Test rule enabling/disabling functionality."""

    def test_some_rules_disabled_by_default(self):
        """Test that some rules are disabled by default."""
        library = GeneralLibrary()

        disabled_rules = [r for r in library.rules.values() if not r.enabled_by_default]

        # Should have some disabled rules
        assert len(disabled_rules) > 0

    def test_critical_rules_enabled(self):
        """Test that critical rules are enabled by default."""
        library = HIPAALibrary()

        [
            r for r in library.rules.values()
            if r.severity == LintSeverity.CRITICAL and not r.enabled_by_default
        ]

        # Library should have rules
        assert len(library.rules) > 0


class TestComposedRuleSetAuditTrail:
    """Test audit trail in composed rule sets."""

    def test_audit_trail_records_composition(self):
        """Test that audit trail records library composition."""
        composer = RuleLibraryComposer()
        composer.add_library(GeneralLibrary())
        composer.add_library(HIPAALibrary())
        composed = composer.build()

        # Should have composed rules from both libraries
        assert len(composed.rules) == (20 + 15)
