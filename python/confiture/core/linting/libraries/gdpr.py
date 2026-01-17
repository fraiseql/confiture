"""GDPR compliance rule library."""
from __future__ import annotations

from ..composer import RuleLibrary
from ..versioning import LintSeverity, Rule, RuleVersion


class GDPRLibrary(RuleLibrary):
    """GDPR compliance rule library (18 rules)."""

    def __init__(self):
        rules = [
                Rule(
                    rule_id="gdpr_001",
                    name="personal_data_encryption",
                    description="Personal data must be encrypted at rest and in transit",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_002",
                    name="consent_tracking",
                    description="Track consent for each piece of personal data",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_003",
                    name="data_minimization",
                    description="Only collect necessary personal data",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_004",
                    name="purpose_limitation",
                    description="Data use must be limited to stated purposes",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_005",
                    name="right_to_deletion",
                    description="Implement right to be forgotten capability",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_006",
                    name="data_portability",
                    description="Enable data portability (export in machine-readable format)",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_007",
                    name="access_request_tracking",
                    description="Track and respond to data access requests",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_008",
                    name="breach_notification",
                    description="Implement breach notification within 72 hours",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_009",
                    name="dpa_impact_assessment",
                    description="Conduct data protection impact assessment",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_010",
                    name="dpo_designation",
                    description="Data Protection Officer must be designated",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_011",
                    name="data_processing_agreement",
                    description="Document data processing agreements",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_012",
                    name="third_party_transfer",
                    description="Document third-party data transfers",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_013",
                    name="international_transfer",
                    description="Manage international data transfers properly",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_014",
                    name="consent_withdrawal",
                    description="Allow easy consent withdrawal",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_015",
                    name="legitimate_interest",
                    description="Document legitimate interests assessment",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_016",
                    name="child_protection",
                    description="Implement special protection for children's data",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_017",
                    name="audit_logging",
                    description="Maintain audit logs of all data access",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="gdpr_018",
                    name="privacy_by_design",
                    description="Privacy must be built into system design",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
        ]

        # Verify rule count matches docstring
        assert len(rules) == 18, f"Expected 18 rules in GDPRLibrary, got {len(rules)}"

        super().__init__(
            name="GDPR",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["privacy", "compliance", "gdpr", "eu"],
        )
