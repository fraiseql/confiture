"""Migration preconditions for fail-fast validation.

Declarative preconditions that are validated BEFORE migration execution begins.
This prevents migrations from failing mid-execution when the database state
doesn't match expectations.

Example:
    >>> from confiture.core.preconditions import TableExists, TableNotExists
    >>>
    >>> class MoveCatalogTables(Migration):
    ...     version = "004"
    ...     name = "move_catalog_tables"
    ...
    ...     up_preconditions = [
    ...         TableExists("tb_datasupplier", schema="tenant"),
    ...         TableNotExists("tb_datasupplier", schema="catalog"),
    ...     ]
    ...
    ...     down_preconditions = [
    ...         TableExists("tb_datasupplier", schema="catalog"),
    ...         TableNotExists("tb_datasupplier", schema="tenant"),
    ...     ]
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg


class PreconditionError(Exception):
    """Raised when a migration precondition fails.

    Attributes:
        precondition: The precondition that failed
        message: Detailed error message
        migration_version: Version of the migration (if available)
        migration_name: Name of the migration (if available)
    """

    def __init__(
        self,
        precondition: "Precondition",
        message: str,
        migration_version: str | None = None,
        migration_name: str | None = None,
    ):
        self.precondition = precondition
        self.migration_version = migration_version
        self.migration_name = migration_name
        super().__init__(message)


class PreconditionValidationError(Exception):
    """Raised when multiple preconditions fail.

    Attributes:
        failures: List of (precondition, error_message) tuples
        migration_version: Version of the migration
        migration_name: Name of the migration
    """

    def __init__(
        self,
        failures: list[tuple["Precondition", str]],
        migration_version: str | None = None,
        migration_name: str | None = None,
    ):
        self.failures = failures
        self.migration_version = migration_version
        self.migration_name = migration_name

        # Build detailed error message
        lines = [f"Migration preconditions failed ({len(failures)} failures):"]
        for precondition, error in failures:
            lines.append(f"  - {precondition}: {error}")

        super().__init__("\n".join(lines))


@dataclass
class Precondition(ABC):
    """Base class for migration preconditions.

    Preconditions are declarative checks that are validated before a migration
    runs. They provide fail-fast behavior and clear error messages.

    Subclasses must implement:
        - check(): Returns (passed: bool, message: str)
        - __str__(): Human-readable description

    Example:
        >>> class TableExists(Precondition):
        ...     table: str
        ...     schema: str = "public"
        ...
        ...     def check(self, conn):
        ...         # Query to check if table exists
        ...         ...
        ...         return (exists, f"Table {self.schema}.{self.table}")
    """

    @abstractmethod
    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        """Check if the precondition is satisfied.

        Args:
            connection: Database connection to use for checking

        Returns:
            Tuple of (passed, message):
                - passed: True if precondition is satisfied
                - message: Description of what was checked (for error reporting)
        """
        raise NotImplementedError

    @abstractmethod
    def __str__(self) -> str:
        """Return human-readable description of the precondition."""
        raise NotImplementedError


# =============================================================================
# Table Preconditions
# =============================================================================


@dataclass
class TableExists(Precondition):
    """Check that a table exists in the database.

    Example:
        >>> TableExists("users")  # Check users in public schema
        >>> TableExists("products", schema="catalog")
    """

    table: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (self.schema, self.table),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (exists, f"Table {self.schema}.{self.table} exists")

    def __str__(self) -> str:
        return f"TableExists({self.schema}.{self.table})"


@dataclass
class TableNotExists(Precondition):
    """Check that a table does NOT exist in the database.

    Useful for ensuring migrations don't conflict with existing tables.

    Example:
        >>> TableNotExists("users_backup")
        >>> TableNotExists("products", schema="catalog")
    """

    table: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (self.schema, self.table),
            )
            result = cursor.fetchone()
            not_exists = result[0] if result else False
            return (not_exists, f"Table {self.schema}.{self.table} does not exist")

    def __str__(self) -> str:
        return f"TableNotExists({self.schema}.{self.table})"


# =============================================================================
# Column Preconditions
# =============================================================================


@dataclass
class ColumnExists(Precondition):
    """Check that a column exists in a table.

    Example:
        >>> ColumnExists("users", "email")
        >>> ColumnExists("users", "created_at", schema="tenant")
    """

    table: str
    column: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                )
                """,
                (self.schema, self.table, self.column),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (exists, f"Column {self.schema}.{self.table}.{self.column} exists")

    def __str__(self) -> str:
        return f"ColumnExists({self.schema}.{self.table}.{self.column})"


@dataclass
class ColumnNotExists(Precondition):
    """Check that a column does NOT exist in a table.

    Example:
        >>> ColumnNotExists("users", "legacy_field")
    """

    table: str
    column: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                )
                """,
                (self.schema, self.table, self.column),
            )
            result = cursor.fetchone()
            not_exists = result[0] if result else False
            return (
                not_exists,
                f"Column {self.schema}.{self.table}.{self.column} does not exist",
            )

    def __str__(self) -> str:
        return f"ColumnNotExists({self.schema}.{self.table}.{self.column})"


@dataclass
class ColumnType(Precondition):
    """Check that a column has a specific data type.

    Example:
        >>> ColumnType("users", "id", "uuid")
        >>> ColumnType("products", "price", "numeric")
    """

    table: str
    column: str
    expected_type: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
                """,
                (self.schema, self.table, self.column),
            )
            result = cursor.fetchone()
            if result is None:
                return (False, f"Column {self.schema}.{self.table}.{self.column} not found")

            actual_type = result[0].lower()
            expected_lower = self.expected_type.lower()

            # Handle common type aliases
            type_aliases = {
                "int": "integer",
                "int4": "integer",
                "int8": "bigint",
                "serial": "integer",
                "bigserial": "bigint",
                "varchar": "character varying",
                "char": "character",
                "bool": "boolean",
                "float": "double precision",
                "float8": "double precision",
                "float4": "real",
            }

            expected_normalized = type_aliases.get(expected_lower, expected_lower)
            actual_normalized = type_aliases.get(actual_type, actual_type)

            matches = actual_normalized == expected_normalized or actual_type.startswith(
                expected_lower
            )
            return (
                matches,
                f"Column {self.schema}.{self.table}.{self.column} type is {self.expected_type} (actual: {actual_type})",
            )

    def __str__(self) -> str:
        return f"ColumnType({self.schema}.{self.table}.{self.column}={self.expected_type})"


# =============================================================================
# Constraint Preconditions
# =============================================================================


@dataclass
class ConstraintExists(Precondition):
    """Check that a constraint exists on a table.

    Example:
        >>> ConstraintExists("users", "users_pkey")
        >>> ConstraintExists("orders", "fk_orders_user")
    """

    table: str
    constraint: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND constraint_name = %s
                )
                """,
                (self.schema, self.table, self.constraint),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (
                exists,
                f"Constraint {self.constraint} on {self.schema}.{self.table} exists",
            )

    def __str__(self) -> str:
        return f"ConstraintExists({self.schema}.{self.table}.{self.constraint})"


@dataclass
class ConstraintNotExists(Precondition):
    """Check that a constraint does NOT exist on a table.

    Example:
        >>> ConstraintNotExists("users", "old_constraint")
    """

    table: str
    constraint: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND constraint_name = %s
                )
                """,
                (self.schema, self.table, self.constraint),
            )
            result = cursor.fetchone()
            not_exists = result[0] if result else False
            return (
                not_exists,
                f"Constraint {self.constraint} on {self.schema}.{self.table} does not exist",
            )

    def __str__(self) -> str:
        return f"ConstraintNotExists({self.schema}.{self.table}.{self.constraint})"


@dataclass
class ForeignKeyExists(Precondition):
    """Check that a foreign key relationship exists.

    Example:
        >>> ForeignKeyExists("orders", "user_id", "users", "id")
    """

    table: str
    column: str
    references_table: str
    references_column: str
    schema: str = "public"
    references_schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.key_column_usage kcu
                    JOIN information_schema.referential_constraints rc
                        ON kcu.constraint_name = rc.constraint_name
                        AND kcu.constraint_schema = rc.constraint_schema
                    JOIN information_schema.key_column_usage kcu2
                        ON rc.unique_constraint_name = kcu2.constraint_name
                        AND rc.unique_constraint_schema = kcu2.constraint_schema
                    WHERE kcu.table_schema = %s
                      AND kcu.table_name = %s
                      AND kcu.column_name = %s
                      AND kcu2.table_schema = %s
                      AND kcu2.table_name = %s
                      AND kcu2.column_name = %s
                )
                """,
                (
                    self.schema,
                    self.table,
                    self.column,
                    self.references_schema,
                    self.references_table,
                    self.references_column,
                ),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (
                exists,
                f"FK {self.schema}.{self.table}.{self.column} -> "
                f"{self.references_schema}.{self.references_table}.{self.references_column}",
            )

    def __str__(self) -> str:
        return (
            f"ForeignKeyExists({self.schema}.{self.table}.{self.column} -> "
            f"{self.references_schema}.{self.references_table}.{self.references_column})"
        )


# =============================================================================
# Index Preconditions
# =============================================================================


@dataclass
class IndexExists(Precondition):
    """Check that an index exists on a table.

    Example:
        >>> IndexExists("users", "idx_users_email")
    """

    table: str
    index: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = %s
                      AND tablename = %s
                      AND indexname = %s
                )
                """,
                (self.schema, self.table, self.index),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (exists, f"Index {self.index} on {self.schema}.{self.table} exists")

    def __str__(self) -> str:
        return f"IndexExists({self.schema}.{self.table}.{self.index})"


@dataclass
class IndexNotExists(Precondition):
    """Check that an index does NOT exist on a table.

    Example:
        >>> IndexNotExists("users", "idx_users_legacy")
    """

    table: str
    index: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = %s
                      AND tablename = %s
                      AND indexname = %s
                )
                """,
                (self.schema, self.table, self.index),
            )
            result = cursor.fetchone()
            not_exists = result[0] if result else False
            return (
                not_exists,
                f"Index {self.index} on {self.schema}.{self.table} does not exist",
            )

    def __str__(self) -> str:
        return f"IndexNotExists({self.schema}.{self.table}.{self.index})"


# =============================================================================
# Schema Preconditions
# =============================================================================


@dataclass
class SchemaExists(Precondition):
    """Check that a database schema exists.

    Example:
        >>> SchemaExists("catalog")
        >>> SchemaExists("tenant")
    """

    schema: str

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = %s
                )
                """,
                (self.schema,),
            )
            result = cursor.fetchone()
            exists = result[0] if result else False
            return (exists, f"Schema {self.schema} exists")

    def __str__(self) -> str:
        return f"SchemaExists({self.schema})"


@dataclass
class SchemaNotExists(Precondition):
    """Check that a database schema does NOT exist.

    Example:
        >>> SchemaNotExists("legacy_schema")
    """

    schema: str

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = %s
                )
                """,
                (self.schema,),
            )
            result = cursor.fetchone()
            not_exists = result[0] if result else False
            return (not_exists, f"Schema {self.schema} does not exist")

    def __str__(self) -> str:
        return f"SchemaNotExists({self.schema})"


# =============================================================================
# Row Count Preconditions
# =============================================================================


@dataclass
class RowCountEquals(Precondition):
    """Check that a table has exactly N rows.

    Example:
        >>> RowCountEquals("migrations", 5)  # Exactly 5 migrations applied
    """

    table: str
    expected_count: int
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            # Use fully qualified table name to prevent SQL injection
            cursor.execute(
                f'SELECT COUNT(*) FROM "{self.schema}"."{self.table}"'  # noqa: S608
            )
            result = cursor.fetchone()
            actual_count = result[0] if result else 0
            matches = actual_count == self.expected_count
            return (
                matches,
                f"Table {self.schema}.{self.table} has {self.expected_count} rows "
                f"(actual: {actual_count})",
            )

    def __str__(self) -> str:
        return f"RowCountEquals({self.schema}.{self.table}={self.expected_count})"


@dataclass
class RowCountGreaterThan(Precondition):
    """Check that a table has more than N rows.

    Example:
        >>> RowCountGreaterThan("users", 0)  # At least 1 user exists
    """

    table: str
    min_count: int
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) FROM "{self.schema}"."{self.table}"'  # noqa: S608
            )
            result = cursor.fetchone()
            actual_count = result[0] if result else 0
            matches = actual_count > self.min_count
            return (
                matches,
                f"Table {self.schema}.{self.table} has > {self.min_count} rows "
                f"(actual: {actual_count})",
            )

    def __str__(self) -> str:
        return f"RowCountGreaterThan({self.schema}.{self.table}>{self.min_count})"


@dataclass
class TableIsEmpty(Precondition):
    """Check that a table has no rows.

    Example:
        >>> TableIsEmpty("temp_data")  # Ensure temp table is empty before use
    """

    table: str
    schema: str = "public"

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) FROM "{self.schema}"."{self.table}"'  # noqa: S608
            )
            result = cursor.fetchone()
            count = result[0] if result else 0
            is_empty = count == 0
            return (is_empty, f"Table {self.schema}.{self.table} is empty (rows: {count})")

    def __str__(self) -> str:
        return f"TableIsEmpty({self.schema}.{self.table})"


# =============================================================================
# Custom SQL Precondition
# =============================================================================


@dataclass
class CustomSQL(Precondition):
    """Execute custom SQL that returns a boolean result.

    The SQL must return a single boolean value. If True, the precondition passes.

    Example:
        >>> CustomSQL(
        ...     "SELECT COUNT(*) = 0 FROM users WHERE status = 'pending'",
        ...     description="No pending users"
        ... )
    """

    sql: str
    description: str
    params: tuple = field(default_factory=tuple)

    def check(self, connection: "psycopg.Connection") -> tuple[bool, str]:
        with connection.cursor() as cursor:
            if self.params:
                cursor.execute(self.sql, self.params)
            else:
                cursor.execute(self.sql)
            result = cursor.fetchone()
            if result is None:
                return (False, f"{self.description} (no result returned)")
            passed = bool(result[0])
            return (passed, self.description)

    def __str__(self) -> str:
        return f"CustomSQL({self.description})"


# =============================================================================
# Precondition Validator
# =============================================================================


class PreconditionValidator:
    """Validates a list of preconditions against a database.

    Example:
        >>> validator = PreconditionValidator(connection)
        >>> preconditions = [
        ...     TableExists("users"),
        ...     ColumnExists("users", "email"),
        ... ]
        >>> validator.validate(preconditions)  # Raises on failure
        >>> validator.check(preconditions)  # Returns (passed, failures)
    """

    def __init__(self, connection: "psycopg.Connection"):
        """Initialize validator with database connection.

        Args:
            connection: Database connection for running checks
        """
        self.connection = connection

    def check(
        self, preconditions: list[Precondition]
    ) -> tuple[bool, list[tuple[Precondition, str]]]:
        """Check all preconditions and return results.

        Args:
            preconditions: List of preconditions to check

        Returns:
            Tuple of (all_passed, failures):
                - all_passed: True if all preconditions passed
                - failures: List of (precondition, error_message) for failures
        """
        failures: list[tuple[Precondition, str]] = []

        for precondition in preconditions:
            try:
                passed, message = precondition.check(self.connection)
                if not passed:
                    failures.append((precondition, message))
            except Exception as e:
                failures.append((precondition, f"Check failed with error: {e}"))

        return (len(failures) == 0, failures)

    def validate(
        self,
        preconditions: list[Precondition],
        migration_version: str | None = None,
        migration_name: str | None = None,
    ) -> None:
        """Validate all preconditions, raising on any failure.

        Args:
            preconditions: List of preconditions to validate
            migration_version: Optional migration version for error context
            migration_name: Optional migration name for error context

        Raises:
            PreconditionValidationError: If any precondition fails
        """
        all_passed, failures = self.check(preconditions)

        if not all_passed:
            raise PreconditionValidationError(
                failures,
                migration_version=migration_version,
                migration_name=migration_name,
            )

    def validate_single(
        self,
        precondition: Precondition,
        migration_version: str | None = None,
        migration_name: str | None = None,
    ) -> None:
        """Validate a single precondition, raising on failure.

        Args:
            precondition: Precondition to validate
            migration_version: Optional migration version for error context
            migration_name: Optional migration name for error context

        Raises:
            PreconditionError: If the precondition fails
        """
        try:
            passed, message = precondition.check(self.connection)
            if not passed:
                raise PreconditionError(
                    precondition,
                    message,
                    migration_version=migration_version,
                    migration_name=migration_name,
                )
        except PreconditionError:
            raise
        except Exception as e:
            raise PreconditionError(
                precondition,
                f"Check failed with error: {e}",
                migration_version=migration_version,
                migration_name=migration_name,
            ) from e
