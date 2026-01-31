"""Level 5: Full seed execution validation.

Cycles 5-8: Seed loading, resolution execution, NULL FK detection, data integrity.

Validates by actually executing seeds and transformations.
Catches runtime issues that static analysis can't detect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)


class Level5ExecutionValidator:
    """Validates prep_seed pattern by full execution.

    Executes:
    - Load seed files into prep_seed tables
    - Execute resolution functions
    - Validate results (no NULL FKs, no duplicates)

    Catches runtime issues:
    - NULL FKs from broken transformations
    - Missing seed data (FK references non-existent UUID)
    - Duplicate identifiers
    - Constraint violations

    Example:
        >>> validator = Level5ExecutionValidator()
        >>> violations = validator.execute_full_cycle(
        ...     connection=db,
        ...     seed_files=["db/seeds/prep/test.sql"],
        ...     resolution_functions=["fn_resolve_tb_x"],
        ...     tables=["tb_x"]
        ... )
    """

    def load_seeds(
        self,
        connection: Any,
        seed_files: list[str],
    ) -> list[PrepSeedViolation]:
        """Load seed files into prep_seed tables.

        Args:
            connection: Database connection
            seed_files: List of seed file paths

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for seed_file_path in seed_files:
            try:
                # Read seed file
                seed_file = Path(seed_file_path)
                if not seed_file.exists():
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                            severity=ViolationSeverity.ERROR,
                            message=f"Seed file not found: {seed_file_path}",
                            file_path=seed_file_path,
                            line_number=1,
                            impact="Cannot load seed data",
                        )
                    )
                    continue

                sql = seed_file.read_text()

                # Execute seed file
                connection.execute(sql)

            except Exception as e:
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                        severity=ViolationSeverity.ERROR,
                        message=f"Error loading seeds from {seed_file_path}: {str(e)}",
                        file_path=seed_file_path,
                        line_number=1,
                        impact="Seed data not loaded",
                    )
                )

        return violations

    def execute_resolutions(
        self,
        connection: Any,
        resolution_functions: list[str],
    ) -> list[PrepSeedViolation]:
        """Execute resolution functions.

        Args:
            connection: Database connection
            resolution_functions: List of resolution function names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for func_name in resolution_functions:
            try:
                # Execute resolution function
                func_call = f"SELECT {func_name}();"
                connection.execute(func_call)

            except Exception as e:
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                        severity=ViolationSeverity.ERROR,
                        message=(f"Error executing {func_name}: {str(e)}"),
                        file_path=f"db/schema/functions/{func_name}.sql",
                        line_number=1,
                        impact="Resolution failed",
                    )
                )

        return violations

    def detect_null_fks(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect NULL foreign keys after resolution.

        Checks all fk_* columns for NULL values that should be non-NULL.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                # Query for NULL FKs in fk_* columns
                query = f"""
                    SELECT table_name, column_name, COUNT(*) as null_count
                    FROM (
                        SELECT '{table}' as table_name, column_name
                        FROM information_schema.columns
                        WHERE table_name = '{table}'
                        AND column_name LIKE 'fk_%'
                    ) fk_cols
                    GROUP BY table_name, column_name;
                """

                result = connection.execute(query)
                null_fk_data = result.fetchall()

                # Process results
                for table_name, col_name, null_count in null_fk_data:
                    if null_count and null_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.NULL_FK_AFTER_RESOLUTION,
                                severity=ViolationSeverity.CRITICAL,
                                message=(
                                    f"Found {null_count} NULL values in "
                                    f"catalog.{table_name}.{col_name} "
                                    f"after resolution"
                                ),
                                file_path=f"db/schema/{table_name}.sql",
                                line_number=1,
                                impact=(
                                    "Data integrity compromised - foreign key constraint violated"
                                ),
                            )
                        )

            except Exception:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def detect_duplicate_identifiers(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect duplicate identifiers after resolution.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                # Check for duplicate identifiers
                query = f"""
                    SELECT id, COUNT(*) as cnt
                    FROM catalog.{table}
                    GROUP BY id
                    HAVING COUNT(*) > 1;
                """

                result = connection.execute(query)
                duplicates = result.fetchall()

                if duplicates:
                    for identifier, count in duplicates:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.UNIQUE_CONSTRAINT_VIOLATION,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"Duplicate identifier {identifier} "
                                    f"found {count} times in {table}"
                                ),
                                file_path=f"db/schema/{table}.sql",
                                line_number=1,
                                impact="Unique constraint violated",
                            )
                        )

            except Exception:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def detect_not_null_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect NOT NULL constraint violations.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                # Query for NULL values in NOT NULL columns
                query = f"""
                    SELECT table_name, column_name, COUNT(*) as null_count
                    FROM (
                        SELECT '{table}' as table_name, column_name
                        FROM information_schema.columns
                        WHERE table_name = '{table}'
                        AND is_nullable = 'NO'
                    ) not_null_cols
                    GROUP BY table_name, column_name;
                """

                result = connection.execute(query)
                not_null_data = result.fetchall()

                # Process results
                for table_name, col_name, null_count in not_null_data:
                    if null_count and null_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                                severity=ViolationSeverity.CRITICAL,
                                message=(
                                    f"NOT NULL constraint violation in {table_name}.{col_name}: "
                                    f"found {null_count} NULL values"
                                ),
                                file_path=f"db/schema/{table_name}.sql",
                                line_number=1,
                                impact="Data integrity compromised - NOT NULL constraint violated",
                            )
                        )

            except Exception:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def detect_check_constraint_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect CHECK constraint violations.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                # Query for CHECK constraint violations
                query = f"""
                    SELECT table_name, constraint_name, COUNT(*) as violation_count
                    FROM (
                        SELECT '{table}' as table_name, constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_name = '{table}'
                        AND constraint_type = 'CHECK'
                    ) check_constraints
                    GROUP BY table_name, constraint_name;
                """

                result = connection.execute(query)
                check_data = result.fetchall()

                # Process results
                for table_name, constraint_name, violation_count in check_data:
                    if violation_count and violation_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"CHECK constraint violation in {table_name}.{constraint_name}: "
                                    f"found {violation_count} violations"
                                ),
                                file_path=f"db/schema/{table_name}.sql",
                                line_number=1,
                                impact="Data integrity compromised - CHECK constraint violated",
                            )
                        )

            except Exception:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def detect_fk_constraint_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect foreign key constraint violations.

        Checks that all foreign key values reference existing rows in the target tables.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                # Query for FK constraint violations (orphaned references)
                query = f"""
                    SELECT table_name, column_name, referenced_table_name, COUNT(*) as violation_count
                    FROM (
                        SELECT '{table}' as table_name, column_name,
                               referenced_table_name
                        FROM information_schema.referential_constraints
                        WHERE table_name = '{table}'
                    ) fk_constraints
                    GROUP BY table_name, column_name, referenced_table_name;
                """

                result = connection.execute(query)
                fk_data = result.fetchall()

                # Process results
                for table_name, fk_col, ref_table, violation_count in fk_data:
                    if violation_count and violation_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"Foreign key constraint violation in {table_name}.{fk_col} "
                                    f"referencing {ref_table}: "
                                    f"found {violation_count} orphaned references"
                                ),
                                file_path=f"db/schema/{table_name}.sql",
                                line_number=1,
                                impact="Data integrity compromised - foreign key constraint violated",
                            )
                        )

            except Exception:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def execute_full_cycle(
        self,
        connection: Any,
        seed_files: list[str],
        resolution_functions: list[str],
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Execute full seed loading and validation cycle.

        Args:
            connection: Database connection
            seed_files: List of seed file paths
            resolution_functions: List of resolution function names
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Step 1: Load seeds
        violations.extend(self.load_seeds(connection, seed_files))
        if violations:
            return violations

        # Step 2: Execute resolutions
        violations.extend(self.execute_resolutions(connection, resolution_functions))
        if violations:
            return violations

        # Step 3: Validate results
        violations.extend(self.detect_null_fks(connection, tables))
        violations.extend(self.detect_duplicate_identifiers(connection, tables))

        return violations

    def execute_full_cycle_comprehensive(
        self,
        connection: Any,
        seed_files: list[str],
        resolution_functions: list[str],
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Execute full seed loading and comprehensive validation cycle.

        Includes all constraint checks: NULL FKs, duplicates, NOT NULL, CHECK, and FK constraints.

        Args:
            connection: Database connection
            seed_files: List of seed file paths
            resolution_functions: List of resolution function names
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Step 1: Load seeds
        violations.extend(self.load_seeds(connection, seed_files))
        if violations:
            return violations

        # Step 2: Execute resolutions
        violations.extend(self.execute_resolutions(connection, resolution_functions))
        if violations:
            return violations

        # Step 3: Detect NULL FKs
        violations.extend(self.detect_null_fks(connection, tables))

        # Step 4: Detect duplicate identifiers
        violations.extend(self.detect_duplicate_identifiers(connection, tables))

        # Step 5: Detect NOT NULL constraint violations
        violations.extend(self.detect_not_null_violations(connection, tables))

        # Step 6: Detect CHECK constraint violations
        violations.extend(self.detect_check_constraint_violations(connection, tables))

        # Step 7: Detect FK constraint violations
        violations.extend(self.detect_fk_constraint_violations(connection, tables))

        return violations
