"""Orchestrator for 5-level prep-seed validation with progressive execution.

This module coordinates running all validation levels (1-5) sequentially,
accumulating violations, and optionally stopping early on CRITICAL violations.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import pglast.parser
import psycopg

from confiture.core import live_catalog
from confiture.core.connection import create_connection
from confiture.core.differ import SchemaDiffer
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import Table
from confiture.core.seed.validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed.validation.prep_seed.level_2_schema import (
    Level2SchemaValidator,
    TableDefinition,
)
from confiture.core.seed.validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed.validation.prep_seed.level_4_runtime import (
    Level4RuntimeValidator,
)
from confiture.core.seed.validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)


@dataclass
class SchemaTables:
    """What the schema files declare, sorted onto the two sides level 2 compares.

    Keyed by ``(schema, name)``: a bare table name is not an identity, which is
    how ``tenant.tb_x`` and ``etl.tb_x`` used to become one entry. ``schemas_seen``
    is every schema the files actually declare into, so a tree with nothing in
    either configured schema can say so rather than pass empty.
    """

    prep: dict[tuple[str, str], TableDefinition] = field(default_factory=dict)
    catalog: dict[tuple[str, str], TableDefinition] = field(default_factory=dict)
    violations: list[PrepSeedViolation] = field(default_factory=list)
    schemas_seen: set[str] = field(default_factory=set)


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
        tables = self._parse_schema_files()
        violations: list[PrepSeedViolation] = list(tables.violations)

        if not tables.prep:
            violations.extend(self._nothing_to_compare(tables))
            return violations

        # The catalog counterpart of a prep-seed table is the same name in the
        # configured catalog schema — the pairing is across schemas, by name,
        # which is what makes the *side* a table is on the thing that had to be
        # read from its qualifier.
        catalog_schema = self.config.catalog_schema.lower()

        def get_final_table(table_name: str) -> TableDefinition | None:
            return tables.catalog.get((catalog_schema, table_name))

        validator = Level2SchemaValidator(get_final_table=get_final_table)

        for (_schema, table_name), prep_table in tables.prep.items():
            try:
                violations.extend(validator.validate_schema_mapping(prep_table))
            except Exception as e:  # Reason: level-2 validation parses arbitrary seed SQL; any parser failure is a reported violation
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                        severity=ViolationSeverity.WARNING,
                        message=f"Error validating schema for {table_name}: {e!s}",
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
                    return live_catalog.relation_exists(
                        connection, schema, table, kinds=live_catalog.TABLE_LIKE
                    )
                except psycopg.Error:
                    return False

            def get_column_type(schema: str, table: str, column: str) -> str | None:
                try:
                    found = live_catalog.column(connection, schema, table, column)
                except psycopg.Error:
                    return None
                return found.type_text if found is not None else None

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
                except Exception as e:  # Reason: dry-running a user resolution function; any failure is a reported violation
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                            severity=ViolationSeverity.ERROR,
                            message=(f"Failed to validate {func_name}: {e!s}"),
                            file_path=f"db/schema/functions/{func_name}.sql",
                            line_number=1,
                            impact="Resolution function validation failed",
                        )
                    )

        except Exception as e:  # Reason: level-4 reaches the database through create_connection; any failure is a CRITICAL violation, not a crash
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Database connection failed: {e!s}",
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
            # `catalog_schema` is a documented OrchestrationConfig field that
            # level 5 used to ignore: `catalog.` was hardwired into one query and
            # absent from the rest.
            validator = Level5ExecutionValidator(catalog_schema=self.config.catalog_schema)

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

        except Exception as e:  # Reason: level-5 executes arbitrary seed SQL; any failure is a CRITICAL violation, not a crash
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Level 5 execution failed: {e!s}",
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

    def _parse_schema_files(self) -> SchemaTables:
        """The tables the schema files declare, on the side their qualifier puts them.

        Which side a table is on is a fact the statement carries:
        ``CREATE TABLE catalog.tb_manufacturer`` is in ``catalog``, and
        ``Table.schema`` has held that since 1.13.0. This read it from
        ``"prep_seed" in str(sql_file)`` instead and keyed the result on
        ``table.name`` — #313's defect one module over, and latent only because
        the shipped ``examples/06`` happens to put its two ``tb_manufacturer``
        declarations in directories the heuristic separates (#317).

        Identity is ``(schema, name)`` with a missing qualifier folded to
        :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA`, so a table in
        neither configured schema is on neither side rather than colliding with
        one that is.
        """
        tables = SchemaTables()
        if not self.config.schema_dir.exists():
            return tables

        differ = SchemaDiffer()
        sides = {
            self.config.prep_seed_schema.lower(): tables.prep,
            self.config.catalog_schema.lower(): tables.catalog,
        }

        for sql_file in sorted(self.config.schema_dir.rglob("*.sql")):
            # Resolution functions are level 3's subject, not level 2's.
            if sql_file.name.startswith("fn_resolve"):
                continue
            try:
                parsed = differ.parse_sql(sql_file.read_text())
            except (OSError, UnicodeDecodeError, pglast.parser.ParseError):
                continue
            for table in parsed:
                self._place(table, sides, tables)

        return tables

    def _place(
        self,
        table: Table,
        sides: dict[str, dict[tuple[str, str], TableDefinition]],
        tables: SchemaTables,
    ) -> None:
        """Put one parsed table on its side, or report that it is already there."""
        schema = (table.schema or DEFAULT_SCHEMA).lower()
        tables.schemas_seen.add(schema)
        side = sides.get(schema)
        if side is None:
            return
        key = (schema, table.name)
        if key in side:
            # ``confiture build`` concatenates in order and a table has no
            # ``OR REPLACE`` form, so the first definition is the one the
            # database ends up with — ``duplicates.wins``' answer for a table.
            # Last-one-wins is the silence #313 removed from the differ.
            tables.violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.WARNING,
                    message=(
                        f"Table {schema}.{table.name} is defined more than once in the "
                        "schema files; the first definition is the one the build keeps"
                    ),
                    file_path=str(self.config.schema_dir),
                    line_number=1,
                    impact="Level 2 validates the first definition",
                )
            )
            return
        side[key] = TableDefinition(
            name=table.name,
            schema=schema,
            columns={col.folded: col.raw_sql_type or col.type_key or "" for col in table.columns},
        )

    def _nothing_to_compare(self, tables: SchemaTables) -> list[PrepSeedViolation]:
        """Level 2 looked at a schema tree and found no prep-seed table in it.

        Returning no violations for a tree it never compared is the silent pass
        this reader used to hide behind the path heuristic: the heuristic routed
        unqualified DDL somewhere, and a qualifier cannot. Saying which schemas
        the files actually declare is the difference between "nothing is wrong"
        and "nothing was checked".
        """
        if not tables.schemas_seen:
            return []
        return [
            PrepSeedViolation(
                pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                severity=ViolationSeverity.WARNING,
                message=(
                    f"No table is declared in the configured prep-seed schema "
                    f"'{self.config.prep_seed_schema}'; the schema files declare tables in "
                    f"{', '.join(sorted(tables.schemas_seen))}. Level 2 compared nothing."
                ),
                file_path=str(self.config.schema_dir),
                line_number=1,
                impact="Schema mapping between prep-seed and final tables was not validated",
            )
        ]

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


def validate_seeds(
    seeds_dir: Path,
    *,
    schema_dir: Path,
    max_level: int = 3,
    database_url: str | None = None,
    prep_seed_schema: str = "prep_seed",
    catalog_schema: str = "catalog",
) -> PrepSeedReport:
    """Run prep-seed validation levels 1 through *max_level* over *seeds_dir*.

    Levels 1-3 read files and need no database; 4 and 5 load the seeds and run
    the resolvers against *database_url*, in a transaction they roll back.
    Nothing is printed: the report is the answer.

    Raises:
        ValueError: *max_level* of 4 or 5 without a *database_url*.
    """
    config = OrchestrationConfig(
        max_level=max_level,
        seeds_dir=seeds_dir,
        schema_dir=schema_dir,
        database_url=database_url,
        show_progress=False,
        prep_seed_schema=prep_seed_schema,
        catalog_schema=catalog_schema,
    )
    return PrepSeedOrchestrator(config).run()
