"""Level 5: Full seed execution validation.

Cycles 5-8: Seed loading, resolution execution, NULL FK detection, data integrity.

Validates by actually executing seeds and transformations.
Catches runtime issues that static analysis can't detect.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import sql

from confiture.core import live_catalog
from confiture.core.seed.executor import run_script
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)

if TYPE_CHECKING:
    from confiture.core.schema_model import Column, Constraint, ConstraintKind


@contextmanager
def _probe(connection: Any) -> Iterator[None]:
    """Run a read-only probe without leaving the caller's transaction aborted.

    Level 5 runs inside one ``BEGIN``. A failed statement poisons it, so each
    probe gets a SAVEPOINT of its own and rolls back to it on error.
    """
    connection.execute("SAVEPOINT confiture_level5_probe")
    try:
        yield
    except psycopg.Error:
        connection.execute("ROLLBACK TO SAVEPOINT confiture_level5_probe")
        raise
    finally:
        with contextlib.suppress(psycopg.Error):
            connection.execute("RELEASE SAVEPOINT confiture_level5_probe")


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

                # Bytes, decoded: a text-mode read turns a carriage return inside
                # a string literal into a newline. Run as `seed apply` runs it, so
                # a COPY block loads here too.
                with connection.cursor() as cursor:
                    run_script(cursor, seed_file.read_bytes().decode("utf-8"))

            except (OSError, UnicodeDecodeError, psycopg.Error) as e:
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                        severity=ViolationSeverity.ERROR,
                        message=f"Error loading seeds from {seed_file_path}: {e!s}",
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

            except Exception as e:  # Reason: executes a user resolution function; any failure is a reported violation
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                        severity=ViolationSeverity.ERROR,
                        message=(f"Error executing {func_name}: {e!s}"),
                        file_path=f"db/schema/functions/{func_name}.sql",
                        line_number=1,
                        impact="Resolution failed",
                    )
                )

        return violations

    def __init__(self, catalog_schema: str = "catalog") -> None:
        """Args: catalog_schema: schema holding the resolved (BIGINT-keyed) tables."""
        self.catalog_schema = catalog_schema

    def _relation(self, table: str) -> sql.Identifier:
        return sql.Identifier(self.catalog_schema, table)

    def _columns(self, connection: Any, table: str) -> tuple[Column, ...]:
        """The columns of ``catalog.<table>``, in order; none for a table that is not there."""
        with _probe(connection):
            return live_catalog.columns(connection, self.catalog_schema, table)

    def _constraints(self, connection: Any, table: str, kind: ConstraintKind) -> list[Constraint]:
        """The constraints of one kind on ``catalog.<table>``, by name."""
        with _probe(connection):
            found = live_catalog.constraints(connection, self.catalog_schema, table)
        return [constraint for constraint in found if constraint.kind == kind]

    @staticmethod
    def _referenced(constraint: Constraint) -> tuple[sql.Identifier, str]:
        """The relation a foreign key references, and its name for a message.

        ``pg_get_constraintdef`` qualifies the referenced table only when
        ``search_path`` would not find it, so an unqualified one is named
        unqualified on this same connection — and reaches the same table.
        """
        schema, _, name = (constraint.ref_table or "").rpartition(".")
        return (sql.Identifier(schema, name) if schema else sql.Identifier(name)), name

    def _count(self, connection: Any, table: str, predicate: sql.Composable) -> int:
        """How many rows of ``catalog.<table>`` satisfy *predicate*."""
        query = sql.SQL("SELECT COUNT(*) FROM {} WHERE {}").format(self._relation(table), predicate)
        with _probe(connection):
            row = connection.execute(query).fetchone()
        return int(row[0]) if row else 0

    def detect_null_fks(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect NULL foreign keys after resolution.

        A resolution function that missed its join leaves an ``fk_`` column
        NULL rather than failing, which is the whole reason this level exists.
        The count is of rows, from the table itself.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                columns = [c.name for c in self._columns(connection, table)]
                for column in (name for name in columns if name.startswith("fk_")):
                    null_count = self._count(
                        connection,
                        table,
                        sql.SQL("{} IS NULL").format(sql.Identifier(column)),
                    )
                    if null_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.NULL_FK_AFTER_RESOLUTION,
                                severity=ViolationSeverity.CRITICAL,
                                message=(
                                    f"Found {null_count} NULL values in "
                                    f"{self.catalog_schema}.{table}.{column} "
                                    f"after resolution"
                                ),
                                file_path=f"db/schema/{table}.sql",
                                line_number=1,
                                impact=(
                                    "Data integrity compromised - foreign key constraint violated"
                                ),
                            )
                        )
            except psycopg.Error:
                # The table may not exist; a missing table is level 4's finding.
                continue

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
                query = sql.SQL(
                    "SELECT id, COUNT(*) AS cnt FROM {} GROUP BY id HAVING COUNT(*) > 1"
                ).format(self._relation(table))

                with _probe(connection):
                    duplicates = connection.execute(query).fetchall()

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

            except psycopg.Error:
                # Ignore query errors (table might not exist)
                pass

        return violations

    def detect_not_null_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect NOT NULL constraint violations.

        PostgreSQL enforces an ordinary NOT NULL, so this reports only where a
        row outlived the constraint — a ``NOT VALID`` NOT NULL (PostgreSQL 18)
        or a constraint added to data that already broke it.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                columns = [c.name for c in self._columns(connection, table) if c.not_null]
                for column in columns:
                    null_count = self._count(
                        connection,
                        table,
                        sql.SQL("{} IS NULL").format(sql.Identifier(column)),
                    )
                    if null_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                                severity=ViolationSeverity.CRITICAL,
                                message=(
                                    f"NOT NULL constraint violation in {table}.{column}: "
                                    f"found {null_count} NULL values"
                                ),
                                file_path=f"db/schema/{table}.sql",
                                line_number=1,
                                impact="Data integrity compromised - NOT NULL constraint violated",
                            )
                        )
            except psycopg.Error:
                continue

        return violations

    def detect_check_constraint_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect CHECK constraint violations.

        A row violates a CHECK when the expression evaluates to FALSE; NULL is
        unknown and passes, which is why the test is ``IS FALSE`` and not
        ``NOT (...)``. As with NOT NULL, an enforced constraint cannot be broken
        — what this finds is a ``NOT VALID`` one.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                for check in self._constraints(connection, table, "check"):
                    name, expression = check.name, check.expression
                    if not expression:
                        continue
                    violation_count = self._count(
                        connection, table, sql.SQL("({}) IS FALSE").format(sql.SQL(expression))
                    )
                    if violation_count > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"CHECK constraint violation in {table}.{name}: "
                                    f"found {violation_count} violations"
                                ),
                                file_path=f"db/schema/{table}.sql",
                                line_number=1,
                                impact="Data integrity compromised - CHECK constraint violated",
                            )
                        )
            except psycopg.Error:
                continue

        return violations

    def detect_fk_constraint_violations(
        self,
        connection: Any,
        tables: list[str],
    ) -> list[PrepSeedViolation]:
        """Detect foreign keys pointing at rows that do not exist.

        The previous query named ``information_schema.referential_constraints.
        column_name``, which is not a column of that view, so it raised on every
        call and the error was swallowed: this detector had never reported
        anything. The foreign keys come from ``core/live_catalog``'s constraint
        reader instead, and the orphans are counted with a ``NOT EXISTS``
        against the parent.

        Args:
            connection: Database connection
            tables: List of final table names

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        for table in tables:
            try:
                for fk in self._constraints(connection, table, "foreign_key"):
                    child_cols, parent_cols = fk.columns, fk.ref_columns
                    if not child_cols or not parent_cols:
                        continue
                    parent, parent_table = self._referenced(fk)
                    joins = sql.SQL(" AND ").join(
                        sql.SQL("parent.{} = child.{}").format(
                            sql.Identifier(parent_col), sql.Identifier(child_col)
                        )
                        for child_col, parent_col in zip(child_cols, parent_cols, strict=True)
                    )
                    set_cols = sql.SQL(" AND ").join(
                        sql.SQL("child.{} IS NOT NULL").format(sql.Identifier(col))
                        for col in child_cols
                    )
                    query = sql.SQL(
                        "SELECT COUNT(*) FROM {child} AS child "
                        "WHERE {set_cols} AND NOT EXISTS ("
                        "SELECT 1 FROM {parent} AS parent WHERE {joins})"
                    ).format(
                        child=self._relation(table),
                        parent=parent,
                        set_cols=set_cols,
                        joins=joins,
                    )
                    with _probe(connection):
                        row = connection.execute(query).fetchone()
                    orphans = int(row[0]) if row else 0
                    if orphans > 0:
                        violations.append(
                            PrepSeedViolation(
                                pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                                severity=ViolationSeverity.ERROR,
                                message=(
                                    f"Foreign key constraint violation in "
                                    f"{table}.{', '.join(child_cols)} "
                                    f"referencing {parent_table}: "
                                    f"found {orphans} orphaned references"
                                ),
                                file_path=f"db/schema/{table}.sql",
                                line_number=1,
                                impact=(
                                    "Data integrity compromised - foreign key constraint violated"
                                ),
                            )
                        )
            except psycopg.Error:
                continue

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
