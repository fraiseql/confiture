"""HIPAA compliance rule library - Phase 6."""
from __future__ import annotations


from ..composer import RuleLibrary
from ..versioning import LintSeverity, Rule, RuleVersion


class HIPAALibrary(RuleLibrary):
    """HIPAA compliance rule library (15 rules)."""

    def __init__(self):
        rules = [
                Rule(
                    rule_id="hipaa_001",
                    name="encrypt_phi",
                    description="All PII/PHI columns must be encrypted at rest",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_002",
                    name="audit_log_retention",
                    description="Maintain audit logs for minimum 6 years",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_003",
                    name="access_control_logs",
                    description="Log all database access and modifications",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_004",
                    name="no_plaintext_phi",
                    description="PHI must never be stored in plaintext",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_005",
                    name="encryption_key_rotation",
                    description="Encryption keys must be rotated regularly",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_006",
                    name="breach_notification",
                    description="Implement breach notification protocol",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_007",
                    name="user_authentication",
                    description="Multi-factor authentication required for access",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_008",
                    name="session_timeout",
                    description="Sessions must timeout after inactivity period",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_009",
                    name="data_segregation",
                    description="Patient data must be properly segregated",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_010",
                    name="backup_encryption",
                    description="All backups must be encrypted",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_011",
                    name="disaster_recovery",
                    description="Disaster recovery plan must be documented",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_012",
                    name="integrity_verification",
                    description="Implement data integrity verification",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_013",
                    name="transmission_encryption",
                    description="All data transmission must be encrypted",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_014",
                    name="authorization_control",
                    description="Implement role-based access control",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="hipaa_015",
                    name="audit_controls",
                    description="Implement comprehensive audit controls",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
        ]

        # Verify rule count matches docstring
        assert len(rules) == 15, f"Expected 15 rules in HIPAALibrary, got {len(rules)}"

        super().__init__(
            name="HIPAA",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["healthcare", "compliance", "phi", "hipaa"],
        )
