"""PCI-DSS compliance rule library - Phase 6."""
from __future__ import annotations


from ..composer import RuleLibrary
from ..versioning import LintSeverity, Rule, RuleVersion


class PCI_DSSLibrary(RuleLibrary):
    """PCI-DSS compliance rule library (10 rules)."""

    def __init__(self):
        rules = [
                Rule(
                    rule_id="pci_dss_001",
                    name="cardholder_data_encryption",
                    description="Cardholder data must be encrypted at rest and in transit",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_002",
                    name="no_default_credentials",
                    description="No default credentials allowed in database",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_003",
                    name="no_plaintext_cardholder_data",
                    description="Cardholder data must never be stored in plaintext",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_004",
                    name="access_control",
                    description="Implement strong access control (need-to-know basis)",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_005",
                    name="vulnerability_scanning",
                    description="Regular vulnerability scanning required",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_006",
                    name="firewall_configuration",
                    description="Maintain firewall configuration standards",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_007",
                    name="audit_trail",
                    description="Maintain audit trail of all access to cardholder data",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_008",
                    name="secure_deletion",
                    description="Implement secure deletion for sensitive data",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_009",
                    name="key_management",
                    description="Implement encryption key management procedures",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="pci_dss_010",
                    name="security_testing",
                    description="Regular security testing and assessment required",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
        ]

        # Verify rule count matches docstring
        assert len(rules) == 10, f"Expected 10 rules in PCI_DSSLibrary, got {len(rules)}"

        super().__init__(
            name="PCI-DSS",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["payment", "compliance", "pci-dss", "security"],
        )
