"""Orchestrate all seed data consistency validators.

This module provides the ConsistencyValidator class that runs all individual
validators (FK, UNIQUE, NOT NULL, Completeness, EnvironmentComparison) and
aggregates results into a single report.
"""

from dataclasses import dataclass, field
from typing import Any

from .completeness_validator import CompletenessValidator
from .environment_comparator import EnvironmentComparator
from .foreign_key_validator import ForeignKeyDepthValidator
from .not_null_validator import NotNullValidator
from .unique_constraint_validator import UniqueConstraintValidator


@dataclass
class ConsistencyReport:
    """Report of all consistency validation results.

    Attributes:
        has_violations: True if any violations were found
        violations: List of all violations found (mixed types)
        violation_count: Total count of violations
        validators_run: Names of validators that were run
    """

    has_violations: bool = False
    violations: list[Any] = field(default_factory=list)
    violation_count: int = 0
    validators_run: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization.

        Returns:
            Dictionary representation of the report
        """
        return {
            "has_violations": self.has_violations,
            "violation_count": self.violation_count,
            "validators_run": self.validators_run,
            "violations": [
                {
                    "table": getattr(v, "table", None),
                    "type": getattr(v, "violation_type", type(v).__name__),
                    "message": getattr(v, "message", str(v)),
                }
                for v in self.violations
            ],
        }


class ConsistencyValidator:
    """Orchestrate all seed data consistency validators.

    Runs the following validators in sequence:
    1. DataExtractor - Parse seed data into structured format
    2. ForeignKeyDepthValidator - Verify all FK references exist
    3. UniqueConstraintValidator - Detect duplicate values in UNIQUE columns
    4. NotNullValidator - Verify required columns have values
    5. CompletenessValidator - Check all required tables are seeded
    6. EnvironmentComparator - Compare seed data across environments (optional)

    Example:
        >>> validator = ConsistencyValidator()
        >>> seed_data = {
        ...     "users": [{"id": "1", "email": "alice@example.com"}],
        ...     "orders": [{"id": "1", "customer_id": "999"}],
        ... }
        >>> schema_context = {
        ...     "users": {"required": True},
        ...     "orders": {
        ...         "columns": {
        ...             "customer_id": {"foreign_key": ("users", "id")}
        ...         }
        ...     }
        ... }
        >>> report = validator.validate(seed_data, schema_context)
        >>> if report.has_violations:
        ...     for v in report.violations:
        ...         print(f"ERROR: {v.message}")
    """

    def __init__(
        self,
        stop_on_first_violation: bool = False,
        compare_with_env2: bool = False,
    ) -> None:
        """Initialize the consistency validator.

        Args:
            stop_on_first_violation: If True, stop validation at first violation
            compare_with_env2: If True, also run environment comparison validator
        """
        self.stop_on_first_violation = stop_on_first_violation
        self.compare_with_env2 = compare_with_env2

        # Initialize individual validators
        self.fk_validator = ForeignKeyDepthValidator()
        self.unique_validator = UniqueConstraintValidator()
        self.not_null_validator = NotNullValidator()
        self.completeness_validator = CompletenessValidator()
        self.environment_comparator = EnvironmentComparator()

    def validate(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
        schema_context: dict[str, Any],
        env2_data: dict[str, list[dict[str, Any]]] | None = None,
    ) -> ConsistencyReport:
        """Validate seed data consistency using all validators.

        Args:
            seed_data: Dictionary mapping table names to lists of row dicts
            schema_context: Schema metadata including all constraint definitions
            env2_data: Optional second environment data for comparison

        Returns:
            ConsistencyReport with aggregated violations
        """
        report = ConsistencyReport()
        report.validators_run = []

        # Run foreign key validation
        if not self.stop_on_first_violation or not report.violations:
            report.validators_run.append("ForeignKeyDepthValidator")
            fk_violations = self.fk_validator.validate(seed_data, schema_context)
            report.violations.extend(fk_violations)

        # Run unique constraint validation
        if not self.stop_on_first_violation or not report.violations:
            report.validators_run.append("UniqueConstraintValidator")
            unique_violations = self.unique_validator.validate(seed_data, schema_context)
            report.violations.extend(unique_violations)

        # Run NOT NULL validation
        if not self.stop_on_first_violation or not report.violations:
            report.validators_run.append("NotNullValidator")
            not_null_violations = self.not_null_validator.validate(seed_data, schema_context)
            report.violations.extend(not_null_violations)

        # Run completeness validation
        if not self.stop_on_first_violation or not report.violations:
            report.validators_run.append("CompletenessValidator")
            completeness_violations = self.completeness_validator.validate(
                seed_data, schema_context
            )
            report.violations.extend(completeness_violations)

        # Run environment comparison if requested
        if (
            self.compare_with_env2
            and env2_data is not None
            and (not self.stop_on_first_violation or not report.violations)
        ):
            report.validators_run.append("EnvironmentComparator")
            differences = self.environment_comparator.compare(seed_data, env2_data)
            report.violations.extend(differences)

        # Update report metadata
        report.violation_count = len(report.violations)
        report.has_violations = report.violation_count > 0

        return report
