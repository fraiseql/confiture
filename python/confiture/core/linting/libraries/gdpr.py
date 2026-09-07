"""GDPR compliance rule library."""

from __future__ import annotations

from ..composer import RuleLibrary
from ..versioning import LintSeverity, Rule, RuleVersion

# One row per rule: id, name, description, severity, enabled by default. Every rule is at 1.0.0.
_RULES: tuple[tuple[str, str, str, LintSeverity, bool], ...] = (
    (
        "gdpr_001",
        "personal_data_encryption",
        "Personal data must be encrypted at rest and in transit",
        LintSeverity.CRITICAL,
        True,
    ),
    (
        "gdpr_002",
        "consent_tracking",
        "Track consent for each piece of personal data",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_003",
        "data_minimization",
        "Only collect necessary personal data",
        LintSeverity.WARNING,
        True,
    ),
    (
        "gdpr_004",
        "purpose_limitation",
        "Data use must be limited to stated purposes",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_005",
        "right_to_deletion",
        "Implement right to be forgotten capability",
        LintSeverity.CRITICAL,
        True,
    ),
    (
        "gdpr_006",
        "data_portability",
        "Enable data portability (export in machine-readable format)",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_007",
        "access_request_tracking",
        "Track and respond to data access requests",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_008",
        "breach_notification",
        "Implement breach notification within 72 hours",
        LintSeverity.CRITICAL,
        True,
    ),
    (
        "gdpr_009",
        "dpa_impact_assessment",
        "Conduct data protection impact assessment",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_010",
        "dpo_designation",
        "Data Protection Officer must be designated",
        LintSeverity.WARNING,
        True,
    ),
    (
        "gdpr_011",
        "data_processing_agreement",
        "Document data processing agreements",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_012",
        "third_party_transfer",
        "Document third-party data transfers",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_013",
        "international_transfer",
        "Manage international data transfers properly",
        LintSeverity.CRITICAL,
        True,
    ),
    ("gdpr_014", "consent_withdrawal", "Allow easy consent withdrawal", LintSeverity.ERROR, True),
    (
        "gdpr_015",
        "legitimate_interest",
        "Document legitimate interests assessment",
        LintSeverity.WARNING,
        True,
    ),
    (
        "gdpr_016",
        "child_protection",
        "Implement special protection for children's data",
        LintSeverity.ERROR,
        True,
    ),
    (
        "gdpr_017",
        "audit_logging",
        "Maintain audit logs of all data access",
        LintSeverity.CRITICAL,
        True,
    ),
    (
        "gdpr_018",
        "privacy_by_design",
        "Privacy must be built into system design",
        LintSeverity.ERROR,
        True,
    ),
)


class GDPRLibrary(RuleLibrary):
    """GDPR compliance rule library (18 rules)."""

    def __init__(self):
        rules = [
            Rule(
                rule_id=rule_id,
                name=name,
                description=description,
                version=RuleVersion(1, 0, 0),
                severity=severity,
                enabled_by_default=enabled_by_default,
            )
            for rule_id, name, description, severity, enabled_by_default in _RULES
        ]

        # Verify rule count matches docstring
        assert len(rules) == 18, f"Expected 18 rules in GDPRLibrary, got {len(rules)}"

        super().__init__(
            name="GDPR",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["privacy", "compliance", "gdpr", "eu"],
        )
