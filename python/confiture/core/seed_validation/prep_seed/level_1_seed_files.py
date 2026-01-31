"""Level 1: Seed file validation.

Cycles 1-3: Validates seed files for:
- Correct schema target (prep_seed, not final tables)
- FK column naming (_id suffix required)
- UUID format validation
"""

from __future__ import annotations

import re

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)


class Level1SeedValidator:
    """Validates seed files for correct prep_seed patterns.

    Checks:
    - Seeds target prep_seed schema, not final tables
    - FK columns use _id suffix
    - UUID format in seed data

    Example:
        >>> validator = Level1SeedValidator()
        >>> violations = validator.validate_seed_file(
        ...     sql="INSERT INTO catalog.tb_x VALUES (...)",
        ...     file_path="db/seeds/prep/test.sql"
        ... )
    """

    # UUID v4 format regex
    UUID_PATTERN = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    # Valid UUID format (any version, for acceptance)
    VALID_UUID_PATTERN = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    def validate_seed_file(
        self,
        sql: str,
        file_path: str,
    ) -> list[PrepSeedViolation]:
        """Validate a seed file.

        Args:
            sql: SQL content of the seed file
            file_path: Path to the seed file

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Check INSERT schema target
        violations.extend(self._validate_schema_target(sql, file_path))

        # Check FK naming conventions
        violations.extend(self._validate_fk_naming(sql, file_path))

        # Check UUID format
        violations.extend(self._validate_uuid_format(sql, file_path))

        return violations

    def _validate_schema_target(self, sql: str, file_path: str) -> list[PrepSeedViolation]:
        """Check that INSERTs target prep_seed schema."""
        violations: list[PrepSeedViolation] = []

        # Find all INSERT INTO schema.table statements
        insert_pattern = r"INSERT\s+INTO\s+(\w+)\.(\w+)"
        for match in re.finditer(insert_pattern, sql, re.IGNORECASE):
            schema = match.group(1)
            line_number = sql[: match.start()].count("\n") + 1

            # Check if schema is NOT prep_seed
            if schema.lower() != "prep_seed":
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                        severity=ViolationSeverity.ERROR,
                        message=(
                            f"Seed INSERT targets {schema} schema but should target prep_seed"
                        ),
                        file_path=file_path,
                        line_number=line_number,
                        impact="Will not load data into prep_seed tables",
                        fix_available=True,
                        suggestion=f"Change INSERT INTO {schema}. to INSERT INTO prep_seed.",
                    )
                )

        return violations

    def _validate_fk_naming(self, sql: str, file_path: str) -> list[PrepSeedViolation]:
        """Check that FK columns use _id suffix."""
        violations: list[PrepSeedViolation] = []

        # Find INSERT INTO prep_seed.table with column list
        insert_pattern = r"INSERT\s+INTO\s+prep_seed\.\w+\s*\((.*?)\)\s*VALUES"
        for match in re.finditer(insert_pattern, sql, re.IGNORECASE | re.DOTALL):
            columns_str = match.group(1)
            line_number = sql[: match.start()].count("\n") + 1

            # Parse column names
            columns = [col.strip() for col in columns_str.split(",")]

            # Check each FK column
            for col in columns:
                # FK columns should be named fk_*_id
                if col.lower().startswith("fk_") and not col.lower().endswith("_id"):
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.INVALID_FK_NAMING,
                            severity=ViolationSeverity.WARNING,
                            message=(
                                f"FK column '{col}' missing _id suffix (should be '{col}_id')"
                            ),
                            file_path=file_path,
                            line_number=line_number,
                            impact=("FK column naming convention not followed for prep_seed"),
                            fix_available=True,
                            suggestion=f"Rename column to '{col}_id'",
                        )
                    )

        return violations

    def _validate_uuid_format(self, sql: str, file_path: str) -> list[PrepSeedViolation]:
        """Check UUID format in seed data."""
        violations: list[PrepSeedViolation] = []

        # Find all quoted strings that look like they should be UUIDs
        # Pattern: single-quoted strings in VALUES clauses
        values_pattern = r"VALUES\s*\((.*?)\)"
        for match in re.finditer(values_pattern, sql, re.IGNORECASE | re.DOTALL):
            values_str = match.group(1)
            line_number = sql[: match.start()].count("\n") + 1

            # Find all quoted strings
            quoted_pattern = r"'([^']*?)'"
            for quoted_match in re.finditer(quoted_pattern, values_str):
                value = quoted_match.group(1)

                # Check if it looks like it should be a UUID
                # Either: has hyphens (indicates UUID attempt), or looks like hex
                looks_like_uuid = "-" in value or (
                    len(value) >= 32 and all(c in "0123456789abcdefABCDEF-" for c in value)
                )

                if looks_like_uuid and not self.VALID_UUID_PATTERN.match(value):
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.INVALID_UUID_FORMAT,
                            severity=ViolationSeverity.ERROR,
                            message=(
                                f"Invalid UUID format: '{value}' (expected: 8-4-4-4-12 hex digits)"
                            ),
                            file_path=file_path,
                            line_number=line_number,
                            impact="UUID values must be valid for data integrity",
                            fix_available=False,
                            suggestion="Use valid UUID format (see RFC 4122)",
                        )
                    )

        return violations
