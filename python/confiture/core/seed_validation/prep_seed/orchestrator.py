"""Orchestrator for 5-level prep-seed validation with progressive execution.

This module coordinates running all validation levels (1-5) sequentially,
accumulating violations, and optionally stopping early on CRITICAL violations.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from confiture.core.connection import create_connection
from confiture.core.differ import SchemaDiffer
from confiture.core.seed_validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed_validation.prep_seed.level_2_schema import (
    Level2SchemaValidator,
    TableDefinition,
)
from confiture.core.seed_validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed_validation.prep_seed.level_4_runtime import (
    Level4RuntimeValidator,
)
from confiture.core.seed_validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)


@dataclass
class OrchestrationConfig:
    """Configuration for orchestrating prep-seed validation.

    Attributes:
        max_level: Maximum validation level to run (1-5)
        seeds_dir: Directory containing seed files
        schema_dir: Directory containing schema files
        database_url: Optional database URL for levels 4-5
        stop_on_critical: Stop early if CRITICAL violation found (default: True)
        show_progress: Show progress indicators during validation (default: True)
        prep_seed_schema: Schema name for prep-seed tables (default: "prep_seed")
        catalog_schema: Schema name for final tables (default: "catalog")
        tables_to_validate: Optional list of specific tables to validate
        level_5_mode: Validation mode for Level 5 ("standard" or "comprehensive")
    """

    max_level: int
    seeds_dir: Path
    schema_dir: Path
    database_url: str | None = None
    stop_on_critical: bool = True
    show_progress: bool = True
    prep_seed_schema: str = "prep_seed"
    catalog_schema: str = "catalog"
    tables_to_validate: list[str] | None = None
    level_5_mode: str = "standard"


class PrepSeedOrchestrator:
    """Orchestrates 5-level prep-seed validation with progressive execution.

    Runs validators 1→N sequentially, accumulates violations across levels,
    and optionally stops early on CRITICAL violations.

    Example:
        >>> config = OrchestrationConfig(
        ...     max_level=3,
        ...     seeds_dir=Path("db/seeds/prep"),
        ...     schema_dir=Path("db/schema"),
        ... )
        >>> orchestrator = PrepSeedOrchestrator(config)
        >>> report = orchestrator.run()
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} violations")
    """

    def __init__(self, config: OrchestrationConfig) -> None:
        """Initialize orchestrator.

        Args:
            config: Orchestration configuration
        """
        self.config = config

    def run(self) -> PrepSeedReport:
        """Run validation levels 1 through max_level.

        Runs validators sequentially, accumulating violations. Stops early on
        CRITICAL violations if configured.

        Returns:
            PrepSeedReport with accumulated violations from all levels

        Raises:
            ValueError: If database_url required for max_level but not provided
        """
        # Validate prerequisites
        if self.config.max_level >= 4 and not self.config.database_url:
            msg = "database_url required for levels 4-5"
            raise ValueError(msg)

        # Initialize report
        report = PrepSeedReport()

        # Level 1: Seed file validation
        if self.config.max_level >= 1:
            violations = self._run_level_1()
            report.violations.extend(violations)
            self._record_scanned_files_level1(report)

            if self._should_exit_early(report):
                return report

        # Level 2: Schema consistency
        if self.config.max_level >= 2:
            violations = self._run_level_2()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 3: Resolution function validation (CRITICAL level)
        if self.config.max_level >= 3:
            violations = self._run_level_3()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 4: Runtime validation
        if self.config.max_level >= 4:
            violations = self._run_level_4()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 5: Full execution
        if self.config.max_level >= 5:
            violations = self._run_level_5()
            report.violations.extend(violations)

        return report

    def _run_level_1(self) -> list[PrepSeedViolation]:
        """Run Level 1: Seed file validation."""
        validator = Level1SeedValidator()
        violations: list[PrepSeedViolation] = []

        # Scan for seed files
        sql_files = list(self.config.seeds_dir.rglob("*.sql"))

        for file_path in sql_files:
            try:
                content = file_path.read_text()
                file_violations = validator.validate_seed_file(content, str(file_path))
                violations.extend(file_violations)
            except OSError:
                # Skip files that can't be read
                pass

        return violations

    def _run_level_2(self) -> list[PrepSeedViolation]:
        """Run Level 2: Schema consistency validation.

        Validates that prep_seed tables have corresponding final tables
        with correct schema patterns (trinity pattern, FK mappings, etc.).

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Parse schema files to get table definitions
        prep_seed_tables, catalog_tables = self._parse_schema_files()

        if not prep_seed_tables:
            # No prep_seed tables to validate
            return violations

        # Create validator with callback to look up final tables
        def get_final_table(table_name: str) -> TableDefinition | None:
            return catalog_tables.get(table_name)

        validator = Level2SchemaValidator(get_final_table=get_final_table)

        # Validate each prep_seed table
        for table_name, prep_table in prep_seed_tables.items():
            try:
                table_violations = validator.validate_schema_mapping(prep_table)
                violations.extend(table_violations)
            except Exception as e:
                # Handle parsing errors gracefully
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                        severity=ViolationSeverity.WARNING,
                        message=f"Error validating schema for {table_name}: {str(e)}",
                        file_path=f"db/schema/{table_name}.sql",
                        line_number=1,
                        impact="Could not validate schema mappings",
                    )
                )

        return violations

    def _run_level_3(self) -> list[PrepSeedViolation]:
        """Run Level 3: Resolution function validation."""
        validator = Level3ResolutionValidator()
        violations: list[PrepSeedViolation] = []

        # Find resolution functions
        func_files = list(self.config.schema_dir.rglob("fn_resolve*.sql"))

        for file_path in func_files:
            try:
                content = file_path.read_text()
                func_name = file_path.stem
                file_violations = validator.validate_function(func_name, content)
                violations.extend(file_violations)
            except OSError:
                pass

        return violations

    def _run_level_4(self) -> list[PrepSeedViolation]:
        """Run Level 4: Runtime validation.

        Connects to database and validates that resolution functions
        can execute without errors (using SAVEPOINT for safety).

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        if not self.config.database_url:
            # Should not reach here (checked in run()), but be safe
            return violations

        # Discover resolution functions
        func_names = self._discover_resolution_functions()

        if not func_names:
            # No functions to validate
            return violations

        # Create database connection
        connection = None
        try:
            connection = create_connection({"database_url": self.config.database_url})

            # Define callbacks for table/column lookups
            def table_exists(schema: str, table: str) -> bool:
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        """
                        SELECT EXISTS(
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        )
                        """,
                        (schema, table),
                    )
                    result = cursor.fetchone()
                    cursor.close()
                    return result[0] if result else False
                except Exception:
                    return False

            def get_column_type(schema: str, table: str, column: str) -> str | None:
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        """
                        SELECT data_type FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        AND column_name = %s
                        """,
                        (schema, table, column),
                    )
                    result = cursor.fetchone()
                    cursor.close()
                    return result[0] if result else None
                except Exception:
                    return None

            # Create validator with callbacks
            validator = Level4RuntimeValidator(
                table_exists=table_exists,
                get_column_type=get_column_type,
            )

            # Validate each resolution function
            for func_name in func_names:
                # Extract target table from function name (fn_resolve_tb_X -> tb_X)
                target_table = func_name.replace("fn_resolve_", "")

                # Validate table exists
                runtime_violations = validator.validate_runtime(
                    func_name=func_name,
                    target_schema=self.config.catalog_schema,
                    target_table=target_table,
                )
                violations.extend(runtime_violations)

                # Skip dry-run if table doesn't exist
                if runtime_violations:
                    continue

                # Dry-run the resolution function with SAVEPOINT
                try:
                    dry_run_violations = validator.dry_run_resolution(
                        func_name=func_name,
                        connection=connection,
                    )
                    violations.extend(dry_run_violations)
                except Exception as e:
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                            severity=ViolationSeverity.ERROR,
                            message=(f"Failed to validate {func_name}: {str(e)}"),
                            file_path=f"db/schema/functions/{func_name}.sql",
                            line_number=1,
                            impact="Resolution function validation failed",
                        )
                    )

        except Exception as e:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Database connection failed: {str(e)}",
                    file_path="database_url",
                    line_number=1,
                    impact="Cannot validate resolution functions",
                )
            )

        finally:
            # Close connection
            if connection:
                with contextlib.suppress(Exception):
                    connection.close()

        return violations

    def _run_level_5(self) -> list[PrepSeedViolation]:
        """Run Level 5: Full execution validation.

        Executes seeds, runs resolution functions, and validates results
        for data integrity issues (NULL FKs, duplicates, constraint violations).

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        if not self.config.database_url:
            # Should not reach here (checked in run()), but be safe
            return violations

        # Collect seed files
        seed_files = list(self.config.seeds_dir.glob("*.sql"))
        seed_file_paths = [str(f) for f in seed_files]

        if not seed_file_paths:
            # No seeds to execute
            return violations

        # Collect resolution functions and target tables
        func_names = self._discover_resolution_functions()
        target_tables = (
            self.config.tables_to_validate
            if self.config.tables_to_validate
            else [fname.replace("fn_resolve_", "") for fname in func_names]
        )

        # Create database connection
        connection = None
        try:
            connection = create_connection({"database_url": self.config.database_url})

            # Start transaction for validation (will rollback)
            connection.execute("BEGIN;")

            # Create validator
            validator = Level5ExecutionValidator()

            # Choose execution mode
            if self.config.level_5_mode == "comprehensive":
                violations.extend(
                    validator.execute_full_cycle_comprehensive(
                        connection=connection,
                        seed_files=seed_file_paths,
                        resolution_functions=func_names,
                        tables=target_tables,
                    )
                )
            else:
                # Standard mode (default)
                violations.extend(
                    validator.execute_full_cycle(
                        connection=connection,
                        seed_files=seed_file_paths,
                        resolution_functions=func_names,
                        tables=target_tables,
                    )
                )

        except Exception as e:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Level 5 execution failed: {str(e)}",
                    file_path="database_url",
                    line_number=1,
                    impact="Could not validate seed execution",
                )
            )

        finally:
            # Rollback transaction (validation shouldn't persist data)
            if connection:
                with contextlib.suppress(Exception):
                    connection.execute("ROLLBACK;")

                with contextlib.suppress(Exception):
                    connection.close()

        return violations

    def _should_exit_early(self, report: PrepSeedReport) -> bool:
        """Check if orchestrator should exit early.

        Early exit occurs when:
        1. stop_on_critical is True AND
        2. Report contains at least one CRITICAL violation

        Args:
            report: Current report to check

        Returns:
            True if should exit early, False otherwise
        """
        if not self.config.stop_on_critical:
            return False

        return any(v.severity == ViolationSeverity.CRITICAL for v in report.violations)

    def _record_scanned_files_level1(self, report: PrepSeedReport) -> None:
        """Record scanned files from Level 1 to report."""
        sql_files = list(self.config.seeds_dir.rglob("*.sql"))
        for file_path in sql_files:
            report.add_file_scanned(str(file_path))

    def _parse_schema_files(
        self,
    ) -> tuple[dict[str, TableDefinition], dict[str, TableDefinition]]:
        """Parse schema files and return prep_seed and catalog tables.

        Uses SchemaDiffer to parse SQL DDL files and separate tables by
        schema (prep_seed vs catalog) based on file path heuristic.

        Returns:
            Tuple of (prep_seed_tables, catalog_tables) dicts.
            Keys are table names, values are TableDefinition objects.
        """
        if not self.config.schema_dir.exists():
            return {}, {}

        prep_seed_tables: dict[str, TableDefinition] = {}
        catalog_tables: dict[str, TableDefinition] = {}

        differ = SchemaDiffer()

        # Find all SQL files in schema directory
        sql_files = sorted(self.config.schema_dir.rglob("*.sql"))

        for sql_file in sql_files:
            try:
                # Skip function files (fn_resolve_*.sql)
                if sql_file.name.startswith("fn_resolve"):
                    continue

                # Read and parse SQL
                sql_content = sql_file.read_text()
                tables = differ.parse_sql(sql_content)

                # Separate tables by path heuristic
                is_prep_seed = "prep_seed" in str(sql_file)
                target_dict = prep_seed_tables if is_prep_seed else catalog_tables

                # Convert Table to TableDefinition
                for table in tables:
                    schema = (
                        self.config.prep_seed_schema if is_prep_seed else self.config.catalog_schema
                    )

                    # Build column type dictionary
                    columns = {col.name: str(col.type) for col in table.columns}

                    table_def = TableDefinition(
                        name=table.name,
                        schema=schema,
                        columns=columns,
                    )

                    target_dict[table.name] = table_def

            except Exception:
                # Silently skip unparseable files
                pass

        return prep_seed_tables, catalog_tables

    def _discover_resolution_functions(self) -> list[str]:
        """Discover resolution function names from schema directory.

        Globs for fn_resolve*.sql files and returns function names (stems).

        Returns:
            List of resolution function names
        """
        if not self.config.schema_dir.exists():
            return []

        func_files = sorted(self.config.schema_dir.rglob("fn_resolve*.sql"))

        return [f.stem for f in func_files]
