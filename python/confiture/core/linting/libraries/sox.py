"""SOX (Sarbanes-Oxley) compliance rule library - Phase 6."""
from __future__ import annotations


from ..composer import RuleLibrary
from ..versioning import LintSeverity, Rule, RuleVersion


class SOXLibrary(RuleLibrary):
    """SOX compliance rule library (12 rules)."""

    def __init__(self):
        rules = [
                Rule(
                    rule_id="sox_001",
                    name="financial_data_integrity",
                    description="Financial data integrity must be maintained",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_002",
                    name="audit_trail_required",
                    description="Complete audit trail of all changes required",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_003",
                    name="change_authorization",
                    description="All database changes must be authorized",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_004",
                    name="segregation_of_duties",
                    description="Segregation of duties must be enforced",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_005",
                    name="access_logging",
                    description="All database access must be logged",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.CRITICAL,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_006",
                    name="retention_policy",
                    description="Data retention policy must be documented",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_007",
                    name="backup_integrity",
                    description="Backups must maintain data integrity",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_008",
                    name="disaster_recovery_testing",
                    description="Disaster recovery must be tested regularly",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_009",
                    name="change_tracking",
                    description="Track who made what changes and when",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_010",
                    name="reconciliation",
                    description="Regular reconciliation of accounts required",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_011",
                    name="control_testing",
                    description="Controls must be tested regularly",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.WARNING,
                    enabled_by_default=True,
                ),
                Rule(
                    rule_id="sox_012",
                    name="documentation_requirement",
                    description="All migrations must be thoroughly documented",
                    version=RuleVersion(1, 0, 0),
                    severity=LintSeverity.ERROR,
                    enabled_by_default=True,
                ),
        ]

        # Verify rule count matches docstring
        assert len(rules) == 12, f"Expected 12 rules in SOXLibrary, got {len(rules)}"

        super().__init__(
            name="SOX",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["finance", "compliance", "sox", "auditing"],
        )
