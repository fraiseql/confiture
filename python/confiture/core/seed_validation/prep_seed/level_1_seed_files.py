"""Level 1: Seed file validation.

Cycles 1-3: Validates seed files for:
- Correct schema target (prep_seed, not final tables)
- FK column naming (_id suffix required)
- UUID format validation
- UNION query type consistency
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
    - UNION queries have consistent column types (Issue #29)

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

        # Check UNION type consistency
        violations.extend(self._validate_union_type_consistency(sql, file_path))

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

    def _validate_union_type_consistency(self, sql: str, file_path: str) -> list[PrepSeedViolation]:
        """Check UNION queries have consistent column types.

        Detects cases where UNION branches have type mismatches, particularly:
        - NULL vs NULL::type (most common from Issue #29)
        - Untyped vs typed literals

        Args:
            sql: SQL content of seed file
            file_path: Path to seed file for error reporting

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Pre-filter: Skip if no UNION keyword (fast path)
        if not re.search(r"\bUNION\s+(?:ALL\s+)?", sql, re.IGNORECASE):
            return violations

        # Find all UNION query blocks
        # Pattern: SELECT ... UNION [ALL] SELECT ...
        union_pattern = r"(?:INSERT\s+INTO\s+\w+\.\w+\s*\([^)]*\)\s+)?(SELECT\s+[^;]+?\s+UNION\s+(?:ALL\s+)?SELECT\s+[^;]+)"
        for match in re.finditer(union_pattern, sql, re.IGNORECASE | re.DOTALL):
            full_query = match.group(1) if match.lastindex >= 1 else match.group(0)
            line_number = sql[: match.start()].count("\n") + 1

            # Extract branches: split by UNION or UNION ALL
            branches = re.split(r"\s+UNION\s+(?:ALL\s+)?", full_query, flags=re.IGNORECASE)

            if len(branches) < 2:
                continue

            # Extract columns from each branch
            base_columns = self._extract_select_columns_from_text(branches[0])

            for branch_num, branch in enumerate(branches[1:], start=2):
                branch_columns = self._extract_select_columns_from_text(branch)

                # Check column count
                if len(base_columns) != len(branch_columns):
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.UNION_TYPE_MISMATCH,
                            severity=ViolationSeverity.ERROR,
                            message=(
                                f"UNION branch {branch_num} has {len(branch_columns)} columns "
                                f"but base branch has {len(base_columns)} columns"
                            ),
                            file_path=file_path,
                            line_number=line_number,
                            impact="PostgreSQL will reject: 'each UNION query must have same number of columns'",
                            fix_available=False,
                            suggestion="Ensure all UNION branches have same column count",
                        )
                    )
                    continue

                # Check type consistency for each column
                for col_idx, (base_col, branch_col) in enumerate(
                    zip(base_columns, branch_columns, strict=True), start=1
                ):
                    type_issue = self._detect_type_mismatch(base_col, branch_col)

                    if type_issue:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.UNION_TYPE_MISMATCH,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"UNION branch {branch_num} column {col_idx}: {type_issue}"
                                ),
                                file_path=file_path,
                                line_number=line_number,
                                impact="PostgreSQL will reject: 'UNION types cannot be matched'",
                                fix_available=True,
                                suggestion=f"Change '{branch_col.strip()}' to '{base_col.strip()}' for type consistency",
                            )
                        )

        return violations

    def _extract_select_columns_from_text(self, select_clause: str) -> list[str]:
        """Extract column expressions from a SELECT clause text.

        Args:
            select_clause: Text of SELECT clause (e.g., "SELECT col1, NULL::type, col2")

        Returns:
            List of column expression strings
        """
        # Remove leading/trailing whitespace
        clause = select_clause.strip()

        # Remove SELECT keyword
        clause = re.sub(r"^\s*SELECT\s+", "", clause, flags=re.IGNORECASE)

        # Remove FROM and everything after
        clause = re.sub(
            r"\s+(FROM|WHERE|GROUP|HAVING|ORDER|LIMIT).*$",
            "",
            clause,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Split by comma, respecting nested parentheses
        columns: list[str] = []
        current_col: list[str] = []
        paren_depth = 0

        for char in clause:
            if char == "(":
                paren_depth += 1
                current_col.append(char)
            elif char == ")":
                paren_depth -= 1
                current_col.append(char)
            elif char == "," and paren_depth == 0:
                # Column separator
                col_text = "".join(current_col).strip()
                if col_text:
                    columns.append(col_text)
                current_col = []
            else:
                current_col.append(char)

        # Add final column
        col_text = "".join(current_col).strip()
        if col_text:
            columns.append(col_text)

        return columns

    def _detect_type_mismatch(self, col1: str, col2: str) -> str | None:
        """Detect type inconsistency between two column expressions.

        Focus on Issue #29 pattern: NULL vs NULL::type

        Args:
            col1: Column expression from base branch
            col2: Column expression from comparison branch

        Returns:
            Description of mismatch if found, None if consistent
        """
        col1_clean = col1.strip()
        col2_clean = col2.strip()

        # Pattern: NULL vs NULL::type
        null_pattern = r"^NULL(?:::(\w+(?:\(\d+(?:,\s*\d+)?\))?))?$"
        match1 = re.match(null_pattern, col1_clean, re.IGNORECASE)
        match2 = re.match(null_pattern, col2_clean, re.IGNORECASE)

        if match1 and match2:
            type1 = match1.group(1)  # None if untyped NULL
            type2 = match2.group(1)

            # One typed, one untyped
            if (type1 is None) != (type2 is None):
                typed = type1 or type2
                return f"NULL type mismatch: 'NULL' vs 'NULL::{typed}'"

            # Both typed but different types
            if type1 and type2 and type1.lower() != type2.lower():
                return f"NULL type mismatch: 'NULL::{type1}' vs 'NULL::{type2}'"

        return None  # No mismatch detected
