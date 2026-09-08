"""General best practices rule library."""

from __future__ import annotations

from ..composer import RuleLibrary
from ..versioning import ComplianceSeverity, Rule, RuleVersion

# One row per rule: id, name, description, severity, enabled by default. Every rule is at 1.0.0.
_RULES: tuple[tuple[str, str, str, ComplianceSeverity, bool], ...] = (
    (
        "general_001",
        "no_implicit_casts",
        "Avoid implicit type casts in migrations",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_002",
        "explicit_column_types",
        "All columns must have explicit types",
        ComplianceSeverity.ERROR,
        True,
    ),
    (
        "general_003",
        "no_null_without_default",
        "NULLABLE columns should have explicit default",
        ComplianceSeverity.WARNING,
        False,
    ),
    (
        "general_004",
        "index_naming_convention",
        "Indexes must follow naming convention",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_005",
        "constraint_naming_convention",
        "Constraints must follow naming convention",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_006",
        "table_naming_convention",
        "Tables must follow naming convention",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_007",
        "column_naming_convention",
        "Columns must follow naming convention",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_008",
        "primary_key_required",
        "All tables should have a primary key",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_009",
        "no_reserved_keywords",
        "Identifiers must not use reserved keywords",
        ComplianceSeverity.ERROR,
        True,
    ),
    (
        "general_010",
        "charset_specified",
        "Character set must be explicitly specified",
        ComplianceSeverity.WARNING,
        False,
    ),
    (
        "general_011",
        "no_large_transactions",
        "Avoid migrations that take >30 seconds",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_012",
        "no_concurrent_index_creation",
        "Avoid creating indexes during peak hours",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_013",
        "foreign_key_naming",
        "Foreign keys must follow naming convention",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_014",
        "no_duplicate_indexes",
        "Avoid creating duplicate indexes",
        ComplianceSeverity.ERROR,
        True,
    ),
    (
        "general_015",
        "data_type_precision",
        "Numeric types should specify precision",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_016",
        "no_text_in_indexes",
        "Avoid indexing TEXT columns directly",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_017",
        "rollback_strategy_defined",
        "Rollback strategy should be documented",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_018",
        "no_data_loss_without_warning",
        "Destructive operations must be explicit",
        ComplianceSeverity.ERROR,
        True,
    ),
    (
        "general_019",
        "constraint_validation",
        "All constraints should be validated",
        ComplianceSeverity.WARNING,
        True,
    ),
    (
        "general_020",
        "migration_reversibility",
        "Migrations should be reversible when possible",
        ComplianceSeverity.WARNING,
        True,
    ),
)


class GeneralLibrary(RuleLibrary):
    """General best practices rule library (20 rules)."""

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
        assert len(rules) == 20, f"Expected 20 rules in GeneralLibrary, got {len(rules)}"

        super().__init__(
            name="General",
            version=RuleVersion(major=1, minor=0, patch=0),
            rules=rules,
            tags=["general", "best-practices", "performance", "naming"],
        )
