"""Level 3: Resolution function validation.

Cycle 3-6: Validates that resolution functions correctly transform UUIDs to BIGINTs.

This is the CRITICAL level that detects:
- Schema drift (functions referencing wrong schema)
- Missing FK transformations (JOINs missing from resolution)
"""

from __future__ import annotations

import re
from collections.abc import Callable

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)


class Level3ResolutionValidator:
    """Validates resolution functions for schema drift and FK transformations.

    Example:
        >>> validator = Level3ResolutionValidator()
        >>> violations = validator.validate_function(
        ...     func_name="fn_resolve_tb_manufacturer",
        ...     func_body="INSERT INTO tenant.tb_manufacturer ...",
        ...     expected_table="tb_manufacturer"
        ... )
        >>> if violations:
        ...     print(f"Found {len(violations)} issues")
    """

    def __init__(
        self,
        get_table_schema: Callable[[str], str] | None = None,
    ) -> None:
        """Initialize the validator.

        Args:
            get_table_schema: Optional function to look up which schema a table is in.
                If provided, used to detect schema drift.
        """
        self.get_table_schema = get_table_schema

    def validate_function(
        self,
        func_name: str,
        func_body: str,
        expected_table: str = "",  # noqa: ARG002
        fk_columns: list[str] | None = None,
    ) -> list[PrepSeedViolation]:
        """Validate a resolution function.

        Args:
            func_name: Name of the resolution function
            func_body: SQL body of the function
            expected_table: Name of the table this function resolves (e.g., "tb_manufacturer")
            fk_columns: Optional list of FK columns in prep_seed (e.g., ["fk_manufacturer_id"])

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Extract INSERT target schema and table
        insert_match = re.search(
            r"INSERT\s+INTO\s+(\w+)\.(\w+)",
            func_body,
            re.IGNORECASE,
        )

        if insert_match:
            target_schema = insert_match.group(1)
            target_table = insert_match.group(2)

            # Check for schema drift
            if self.get_table_schema:
                actual_schema = self.get_table_schema(target_table)
                if actual_schema != target_schema:
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
                            severity=ViolationSeverity.CRITICAL,
                            message=(
                                f"Function references {target_schema}.{target_table} "
                                f"but table is in {actual_schema}.{target_table}"
                            ),
                            file_path=f"db/schema/functions/{func_name}.sql",
                            line_number=insert_match.start(),
                            impact="Will cause NULL foreign keys in dependent tables",
                            fix_available=True,
                            suggestion=(f"Change INSERT target to {actual_schema}.{target_table}"),
                        )
                    )

        # Check for missing FK transformations
        if fk_columns:
            for fk_col in fk_columns:
                # Extract entity name from fk_manufacturer_id -> manufacturer
                entity = fk_col[3:-3]  # Remove "fk_" prefix and "_id" suffix

                # Look for JOIN for this FK transformation
                # Pattern: JOIN ... tb_entity ... ON ... .id = ... .fk_*_id
                join_pattern = (
                    f"JOIN\\s+(?:catalog\\.|prep_seed\\.)?tb_{entity}\\s+"
                    f".*ON.*\\.id\\s*=.*\\.{fk_col}"
                )

                if not re.search(join_pattern, func_body, re.IGNORECASE | re.DOTALL):
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                            severity=ViolationSeverity.ERROR,
                            message=(f"Missing JOIN for FK transformation: {fk_col} → fk_{entity}"),
                            file_path=f"db/schema/functions/{func_name}.sql",
                            line_number=1,  # Line number would need more parsing
                            impact="This FK will have NULL values after resolution",
                            fix_available=True,
                            suggestion=(f"Add: LEFT JOIN catalog.tb_{entity} ON .id = .{fk_col}"),
                        )
                    )

        return violations
