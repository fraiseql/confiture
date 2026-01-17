"""Schema analysis and validation for dry-run mode.

Analyzes SQL statements against current database schema to detect
issues before execution.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import psycopg
import sqlparse

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity of validation issues."""

    ERROR = "error"  # Will definitely fail
    WARNING = "warning"  # Might fail or cause issues
    INFO = "info"  # Informational


@dataclass
class ValidationIssue:
    """A single validation issue."""

    severity: ValidationSeverity
    message: str
    sql_fragment: str | None = None
    line_number: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "severity": self.severity.value,
            "message": self.message,
            "sql_fragment": self.sql_fragment,
            "line_number": self.line_number,
            "suggestion": self.suggestion,
        }


@dataclass
class SchemaInfo:
    """Current database schema information."""

    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexes: dict[str, list[str]] = field(default_factory=dict)
    constraints: dict[str, list[str]] = field(default_factory=dict)
    sequences: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    foreign_keys: dict[str, list[dict[str, str]]] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of schema validation."""

    migration_name: str
    migration_version: str
    issues: list[ValidationIssue] = field(default_factory=list)
    statements_analyzed: int = 0
    validation_time_ms: int = 0

    @property
    def has_errors(self) -> bool:
        """Check if any errors were found."""
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings were found."""
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)

    @property
    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return not self.has_errors

    @property
    def error_count(self) -> int:
        """Count of errors."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warnings."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.WARNING)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "migration_name": self.migration_name,
            "migration_version": self.migration_version,
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "statements_analyzed": self.statements_analyzed,
            "validation_time_ms": self.validation_time_ms,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class SchemaAnalyzer:
    """Analyzes migrations against current database schema.

    Validates SQL statements before execution to catch issues early:
    - Table/column existence
    - Foreign key references
    - Type compatibility
    - Index column existence

    Example:
        >>> analyzer = SchemaAnalyzer(conn)
        >>> result = analyzer.validate_migration(migration)
        >>> if not result.is_valid:
        ...     for issue in result.issues:
        ...         print(f"{issue.severity.value}: {issue.message}")
    """

    def __init__(self, connection: psycopg.Connection):
        """Initialize schema analyzer.

        Args:
            connection: Active database connection
        """
        self.connection = connection
        self._schema_info: SchemaInfo | None = None

    def get_schema_info(self, refresh: bool = False) -> SchemaInfo:
        """Get current database schema information.

        Args:
            refresh: Force refresh of cached schema info

        Returns:
            SchemaInfo with current database state
        """
        if self._schema_info is not None and not refresh:
            return self._schema_info

        info = SchemaInfo()

        # Get tables and columns
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT
                    t.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    c.character_maximum_length,
                    c.numeric_precision,
                    c.numeric_scale
                FROM information_schema.tables t
                JOIN information_schema.columns c
                    ON t.table_name = c.table_name
                    AND t.table_schema = c.table_schema
                WHERE t.table_schema = 'public'
                AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name, c.ordinal_position
            """)

            for row in cur.fetchall():
                table_name = row[0]
                if table_name not in info.tables:
                    info.tables[table_name] = {}
                info.tables[table_name][row[1]] = {
                    "type": row[2],
                    "nullable": row[3] == "YES",
                    "default": row[4],
                    "max_length": row[5],
                    "precision": row[6],
                    "scale": row[7],
                }

        # Get indexes
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
            """)
            for row in cur.fetchall():
                if row[0] not in info.indexes:
                    info.indexes[row[0]] = []
                info.indexes[row[0]].append(row[1])

        # Get constraints
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT
                    tc.table_name,
                    tc.constraint_name,
                    tc.constraint_type
                FROM information_schema.table_constraints tc
                WHERE tc.table_schema = 'public'
            """)
            for row in cur.fetchall():
                if row[0] not in info.constraints:
                    info.constraints[row[0]] = []
                info.constraints[row[0]].append(row[1])

        # Get foreign keys
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
            """)
            for row in cur.fetchall():
                table_name = row[0]
                if table_name not in info.foreign_keys:
                    info.foreign_keys[table_name] = []
                info.foreign_keys[table_name].append(
                    {
                        "column": row[1],
                        "foreign_table": row[2],
                        "foreign_column": row[3],
                        "constraint_name": row[4],
                    }
                )

        # Get extensions
        with self.connection.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension")
            info.extensions = [row[0] for row in cur.fetchall()]

        # Get sequences
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT sequence_name
                FROM information_schema.sequences
                WHERE sequence_schema = 'public'
            """)
            info.sequences = [row[0] for row in cur.fetchall()]

        self._schema_info = info
        return info

    def validate_sql(self, sql: str) -> list[ValidationIssue]:
        """Validate a SQL string against current schema.

        Args:
            sql: SQL statement(s) to validate

        Returns:
            List of validation issues found
        """
        issues: list[ValidationIssue] = []
        schema_info = self.get_schema_info()

        # Parse SQL into statements
        statements = sqlparse.parse(sql)

        for i, stmt in enumerate(statements, 1):
            stmt_str = str(stmt).strip()
            if not stmt_str or stmt_str == ";":
                continue

            stmt_issues = self._validate_statement(stmt_str, schema_info, i)
            issues.extend(stmt_issues)

        return issues

    def validate_migration(self, migration: Any) -> ValidationResult:
        """Validate a migration against current schema.

        Args:
            migration: Migration instance with version, name, and SQL

        Returns:
            ValidationResult with any issues found
        """
        import time

        start_time = time.perf_counter()

        result = ValidationResult(
            migration_name=getattr(migration, "name", "unknown"),
            migration_version=getattr(migration, "version", "unknown"),
        )

        # Try to get SQL from migration
        sql_statements = self._extract_sql_from_migration(migration)

        if not sql_statements:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    message="Could not extract SQL from migration for validation",
                )
            )
            return result

        schema_info = self.get_schema_info()

        for i, sql in enumerate(sql_statements, 1):
            result.statements_analyzed += 1
            issues = self._validate_statement(sql, schema_info, i)
            result.issues.extend(issues)

        result.validation_time_ms = int((time.perf_counter() - start_time) * 1000)
        return result

    def _extract_sql_from_migration(self, migration: Any) -> list[str]:
        """Extract SQL statements from a migration object.

        Args:
            migration: Migration instance

        Returns:
            List of SQL statements
        """
        statements: list[str] = []

        # Check for sql_statements attribute (if migration stores them)
        if hasattr(migration, "sql_statements"):
            return list(migration.sql_statements)

        # Check for _sql_history attribute (captured SQL)
        if hasattr(migration, "_sql_history"):
            return list(migration._sql_history)

        # Try to get from up() docstring or source
        # This is a best-effort approach
        return statements

    def _validate_statement(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate a single SQL statement.

        Args:
            sql: SQL statement
            schema: Current schema info
            line_num: Statement number for error reporting

        Returns:
            List of validation issues
        """
        issues: list[ValidationIssue] = []

        # Parse SQL
        parsed = sqlparse.parse(sql)
        if not parsed:
            return issues

        stmt = parsed[0]
        stmt_type = stmt.get_type()

        if stmt_type == "CREATE":
            issues.extend(self._validate_create(sql, schema, line_num))
        elif stmt_type == "ALTER":
            issues.extend(self._validate_alter(sql, schema, line_num))
        elif stmt_type == "DROP":
            issues.extend(self._validate_drop(sql, schema, line_num))
        elif stmt_type == "INSERT":
            issues.extend(self._validate_insert(sql, schema, line_num))
        elif stmt_type == "UPDATE":
            issues.extend(self._validate_update(sql, schema, line_num))
        elif stmt_type == "DELETE":
            issues.extend(self._validate_delete(sql, schema, line_num))

        return issues

    def _validate_create(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate CREATE statements."""
        issues: list[ValidationIssue] = []
        sql_upper = sql.upper()

        # Check for CREATE TABLE that already exists
        match = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match:
            table_name = match.group(1).lower()
            if table_name in schema.tables and "IF NOT EXISTS" not in sql_upper:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Table '{table_name}' already exists",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF NOT EXISTS' or use ALTER TABLE",
                    )
                )

            # Validate foreign key references in CREATE TABLE
            fk_issues = self._validate_fk_references_in_create(sql, schema, line_num)
            issues.extend(fk_issues)

        # Check for CREATE INDEX on non-existent table
        match = re.search(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX.*ON\s+(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match:
            table_name = match.group(1).lower()
            if table_name not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot create index: table '{table_name}' does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )
            else:
                # Validate index columns exist
                col_issues = self._validate_index_columns(sql, table_name, schema, line_num)
                issues.extend(col_issues)

        return issues

    def _validate_fk_references_in_create(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate foreign key references in CREATE TABLE."""
        issues: list[ValidationIssue] = []

        # Find REFERENCES clauses
        references_pattern = r"REFERENCES\s+(?:\")?(\w+)(?:\")?\s*\((?:\")?(\w+)(?:\")?\)"
        for match in re.finditer(references_pattern, sql, re.IGNORECASE):
            target_table = match.group(1).lower()
            target_column = match.group(2).lower()

            if target_table not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"FK target table '{target_table}' does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )
            elif target_column not in schema.tables[target_table]:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"FK target column '{target_table}.{target_column}' does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )

        return issues

    def _validate_index_columns(
        self,
        sql: str,
        table_name: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate that index columns exist."""
        issues: list[ValidationIssue] = []

        # Extract column names from index
        match = re.search(r"ON\s+\w+\s*\(([^)]+)\)", sql, re.IGNORECASE)
        if match:
            columns_str = match.group(1)
            # Parse column names (handle expressions, DESC, etc.)
            for col_part in columns_str.split(","):
                col_name = col_part.strip().split()[0].strip('"').lower()
                # Skip expressions
                if "(" in col_name or col_name.upper() in ("ASC", "DESC", "NULLS"):
                    continue
                if table_name in schema.tables and col_name not in schema.tables[table_name]:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            message=f"Index column '{col_name}' does not exist in '{table_name}'",
                            sql_fragment=sql[:100],
                            line_number=line_num,
                        )
                    )

        return issues

    def _validate_alter(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate ALTER statements."""
        issues: list[ValidationIssue] = []
        sql_upper = sql.upper()

        # Check table exists
        match = re.search(
            r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match:
            table_name = match.group(1).lower()
            if table_name not in schema.tables and "IF EXISTS" not in sql_upper:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot alter table '{table_name}': table does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF EXISTS' or create the table first",
                    )
                )
            elif table_name in schema.tables:
                # Check column operations
                issues.extend(self._validate_column_operations(sql, schema, table_name, line_num))

        return issues

    def _validate_column_operations(
        self,
        sql: str,
        schema: SchemaInfo,
        table_name: str,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate column ADD/DROP/ALTER operations."""
        issues: list[ValidationIssue] = []
        sql_upper = sql.upper()
        table_columns = schema.tables.get(table_name, {})

        # ADD COLUMN that already exists
        match = re.search(
            r"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?", sql_upper
        )
        if match and "ADD CONSTRAINT" not in sql_upper:
            col_name = match.group(1).lower()
            if col_name in table_columns and "IF NOT EXISTS" not in sql_upper:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Column '{col_name}' already exists in '{table_name}'",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF NOT EXISTS' to handle existing column",
                    )
                )

        # DROP COLUMN that doesn't exist
        match = re.search(
            r"DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match and "DROP CONSTRAINT" not in sql_upper:
            col_name = match.group(1).lower()
            if col_name not in table_columns and "IF EXISTS" not in sql_upper:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Column '{col_name}' does not exist in '{table_name}'",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF EXISTS' to handle missing column",
                    )
                )

        # Validate ADD CONSTRAINT with FK reference
        if "ADD CONSTRAINT" in sql_upper and "FOREIGN KEY" in sql_upper:
            fk_issues = self._validate_fk_references_in_create(sql, schema, line_num)
            issues.extend(fk_issues)

        return issues

    def _validate_drop(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate DROP statements."""
        issues: list[ValidationIssue] = []
        sql_upper = sql.upper()

        # DROP TABLE that doesn't exist
        match = re.search(
            r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match and "IF EXISTS" not in sql_upper:
            table_name = match.group(1).lower()
            if table_name not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot drop table '{table_name}': does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF EXISTS' to handle missing table",
                    )
                )

        # DROP INDEX that doesn't exist
        match = re.search(
            r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
            sql_upper,
        )
        if match and "IF EXISTS" not in sql_upper:
            index_name = match.group(1).lower()
            # Check if index exists in any table
            index_exists = any(index_name in indexes for indexes in schema.indexes.values())
            if not index_exists:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot drop index '{index_name}': does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                        suggestion="Add 'IF EXISTS' to handle missing index",
                    )
                )

        return issues

    def _validate_insert(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate INSERT statements."""
        issues: list[ValidationIssue] = []

        # Check target table exists
        match = re.search(r"INSERT\s+INTO\s+(?:\")?(\w+)(?:\")?", sql, re.IGNORECASE)
        if match:
            table_name = match.group(1).lower()
            if table_name not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot insert into '{table_name}': table does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )

        return issues

    def _validate_update(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate UPDATE statements."""
        issues: list[ValidationIssue] = []

        # Check target table exists
        match = re.search(r"UPDATE\s+(?:\")?(\w+)(?:\")?", sql, re.IGNORECASE)
        if match:
            table_name = match.group(1).lower()
            if table_name not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot update '{table_name}': table does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )

        return issues

    def _validate_delete(
        self,
        sql: str,
        schema: SchemaInfo,
        line_num: int,
    ) -> list[ValidationIssue]:
        """Validate DELETE statements."""
        issues: list[ValidationIssue] = []

        # Check target table exists
        match = re.search(r"DELETE\s+FROM\s+(?:\")?(\w+)(?:\")?", sql, re.IGNORECASE)
        if match:
            table_name = match.group(1).lower()
            if table_name not in schema.tables:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=f"Cannot delete from '{table_name}': table does not exist",
                        sql_fragment=sql[:100],
                        line_number=line_num,
                    )
                )

        return issues

    def validate_foreign_key(
        self,
        source_table: str,
        source_column: str,
        target_table: str,
        target_column: str,
    ) -> ValidationIssue | None:
        """Validate a foreign key reference.

        Args:
            source_table: Source table name
            source_column: Source column name
            target_table: Target (referenced) table name
            target_column: Target (referenced) column name

        Returns:
            ValidationIssue if invalid, None if valid
        """
        schema = self.get_schema_info()

        if target_table not in schema.tables:
            return ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message=f"FK target table '{target_table}' does not exist",
            )

        if target_column not in schema.tables[target_table]:
            return ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message=f"FK target column '{target_table}.{target_column}' does not exist",
            )

        # Check type compatibility
        if source_table in schema.tables and source_column in schema.tables[source_table]:
            source_type = schema.tables[source_table][source_column].get("type")
            target_type = schema.tables[target_table][target_column].get("type")
            if source_type and target_type and source_type != target_type:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    message=f"FK type mismatch: {source_table}.{source_column} ({source_type}) -> "
                    f"{target_table}.{target_column} ({target_type})",
                )

        return None
