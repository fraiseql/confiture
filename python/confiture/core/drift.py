"""Schema drift detection for Confiture.

Compares live database schema against expected state from migrations
to detect unauthorized changes or migration mishaps.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import psycopg

from confiture.core.schema_analyzer import SchemaAnalyzer, SchemaInfo

logger = logging.getLogger(__name__)


class DriftType(Enum):
    """Types of schema drift."""

    MISSING_TABLE = "missing_table"
    EXTRA_TABLE = "extra_table"
    MISSING_COLUMN = "missing_column"
    EXTRA_COLUMN = "extra_column"
    TYPE_MISMATCH = "type_mismatch"
    NULLABLE_MISMATCH = "nullable_mismatch"
    DEFAULT_MISMATCH = "default_mismatch"
    MISSING_INDEX = "missing_index"
    EXTRA_INDEX = "extra_index"
    MISSING_CONSTRAINT = "missing_constraint"
    EXTRA_CONSTRAINT = "extra_constraint"


class DriftSeverity(Enum):
    """Severity of drift."""

    CRITICAL = "critical"  # Missing table/column
    WARNING = "warning"  # Extra objects, type changes
    INFO = "info"  # Minor differences


@dataclass
class DriftItem:
    """A single drift item."""

    drift_type: DriftType
    severity: DriftSeverity
    object_name: str
    expected: Any = None
    actual: Any = None
    message: str = ""

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.drift_type.value}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.drift_type.value,
            "severity": self.severity.value,
            "object": self.object_name,
            "expected": str(self.expected) if self.expected is not None else None,
            "actual": str(self.actual) if self.actual is not None else None,
            "message": self.message,
        }


@dataclass
class DriftReport:
    """Report of schema drift detection."""

    database_name: str
    expected_schema_source: str  # "migrations" or file path
    drift_items: list[DriftItem] = field(default_factory=list)
    tables_checked: int = 0
    columns_checked: int = 0
    indexes_checked: int = 0
    detection_time_ms: int = 0

    @property
    def has_drift(self) -> bool:
        """Check if any drift was detected."""
        return len(self.drift_items) > 0

    @property
    def has_critical_drift(self) -> bool:
        """Check if any critical drift was detected."""
        return any(d.severity == DriftSeverity.CRITICAL for d in self.drift_items)

    @property
    def critical_count(self) -> int:
        """Count of critical drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        """Count of warning drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of info drift items."""
        return sum(1 for d in self.drift_items if d.severity == DriftSeverity.INFO)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "database_name": self.database_name,
            "expected_schema_source": self.expected_schema_source,
            "has_drift": self.has_drift,
            "has_critical_drift": self.has_critical_drift,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "tables_checked": self.tables_checked,
            "columns_checked": self.columns_checked,
            "indexes_checked": self.indexes_checked,
            "detection_time_ms": self.detection_time_ms,
            "drift_items": [d.to_dict() for d in self.drift_items],
        }


class SchemaDriftDetector:
    """Detects schema drift between live database and expected state.

    Compares live database schema against expected state to find:
    - Missing/extra tables
    - Missing/extra columns
    - Type mismatches
    - Nullable mismatches
    - Missing/extra indexes

    Example:
        >>> detector = SchemaDriftDetector(conn)
        >>> report = detector.compare_with_expected(expected_schema)
        >>> if report.has_critical_drift:
        ...     print("CRITICAL: Schema has drifted!")
        ...     for item in report.drift_items:
        ...         print(f"  {item}")
    """

    # Tables to always ignore
    SYSTEM_TABLES = {
        "confiture_migrations",
        "confiture_version",
        "confiture_audit_log",
    }

    def __init__(
        self,
        connection: psycopg.Connection,
        ignore_tables: list[str] | None = None,
    ):
        """Initialize drift detector.

        Args:
            connection: Database connection
            ignore_tables: Additional tables to ignore in drift detection
        """
        self.connection = connection
        self.analyzer = SchemaAnalyzer(connection)
        self.ignore_tables = set(ignore_tables or [])
        # Always ignore Confiture's own tables
        self.ignore_tables.update(self.SYSTEM_TABLES)

    def compare_schemas(
        self,
        expected: SchemaInfo,
        actual: SchemaInfo,
    ) -> DriftReport:
        """Compare two schema info objects.

        Args:
            expected: Expected schema state
            actual: Actual (live) schema state

        Returns:
            DriftReport with differences
        """
        start_time = time.perf_counter()

        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="provided",
        )

        # Compare tables
        expected_tables = set(expected.tables.keys()) - self.ignore_tables
        actual_tables = set(actual.tables.keys()) - self.ignore_tables

        # Missing tables (in expected but not actual)
        for table in sorted(expected_tables - actual_tables):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    severity=DriftSeverity.CRITICAL,
                    object_name=table,
                    expected=table,
                    actual=None,
                    message=f"Table '{table}' is missing from database",
                )
            )

        # Extra tables (in actual but not expected)
        for table in sorted(actual_tables - expected_tables):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_TABLE,
                    severity=DriftSeverity.WARNING,
                    object_name=table,
                    expected=None,
                    actual=table,
                    message=f"Table '{table}' exists but is not in expected schema",
                )
            )

        # Compare columns for tables that exist in both
        for table in sorted(expected_tables & actual_tables):
            report.tables_checked += 1
            self._compare_table_columns(
                table,
                expected.tables[table],
                actual.tables[table],
                report,
            )

        # Compare indexes
        self._compare_indexes(expected, actual, report)

        report.detection_time_ms = int((time.perf_counter() - start_time) * 1000)
        return report

    def _compare_table_columns(
        self,
        table_name: str,
        expected_cols: dict[str, dict],
        actual_cols: dict[str, dict],
        report: DriftReport,
    ) -> None:
        """Compare columns for a single table."""
        expected_col_names = set(expected_cols.keys())
        actual_col_names = set(actual_cols.keys())

        # Missing columns
        for col in sorted(expected_col_names - actual_col_names):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.MISSING_COLUMN,
                    severity=DriftSeverity.CRITICAL,
                    object_name=f"{table_name}.{col}",
                    expected=expected_cols[col],
                    actual=None,
                    message=f"Column '{table_name}.{col}' is missing",
                )
            )

        # Extra columns
        for col in sorted(actual_col_names - expected_col_names):
            report.drift_items.append(
                DriftItem(
                    drift_type=DriftType.EXTRA_COLUMN,
                    severity=DriftSeverity.WARNING,
                    object_name=f"{table_name}.{col}",
                    expected=None,
                    actual=actual_cols[col],
                    message=f"Column '{table_name}.{col}' exists but is not expected",
                )
            )

        # Compare matching columns
        for col in sorted(expected_col_names & actual_col_names):
            report.columns_checked += 1
            exp = expected_cols[col]
            act = actual_cols[col]

            # Type mismatch
            exp_type = exp.get("type", "").lower()
            act_type = act.get("type", "").lower()
            # Check for compatible types (e.g., integer vs int4)
            if (
                exp_type
                and act_type
                and exp_type != act_type
                and not self._types_compatible(exp_type, act_type)
            ):
                report.drift_items.append(
                    DriftItem(
                        drift_type=DriftType.TYPE_MISMATCH,
                        severity=DriftSeverity.WARNING,
                        object_name=f"{table_name}.{col}",
                        expected=exp_type,
                        actual=act_type,
                        message=f"Column '{table_name}.{col}' type mismatch: "
                        f"expected {exp_type}, got {act_type}",
                    )
                )

            # Nullable mismatch
            exp_nullable = exp.get("nullable")
            act_nullable = act.get("nullable")
            if (
                exp_nullable is not None
                and act_nullable is not None
                and exp_nullable != act_nullable
            ):
                report.drift_items.append(
                    DriftItem(
                        drift_type=DriftType.NULLABLE_MISMATCH,
                        severity=DriftSeverity.WARNING,
                        object_name=f"{table_name}.{col}",
                        expected=f"nullable={exp_nullable}",
                        actual=f"nullable={act_nullable}",
                        message=f"Column '{table_name}.{col}' nullable mismatch: "
                        f"expected {exp_nullable}, got {act_nullable}",
                    )
                )

    def _types_compatible(self, type1: str, type2: str) -> bool:
        """Check if two PostgreSQL types are compatible/equivalent."""
        # Normalize type names
        type_aliases = {
            "integer": "int4",
            "int": "int4",
            "bigint": "int8",
            "smallint": "int2",
            "boolean": "bool",
            "character varying": "varchar",
            "character": "char",
            "double precision": "float8",
            "real": "float4",
            "timestamp without time zone": "timestamp",
            "timestamp with time zone": "timestamptz",
        }

        t1 = type_aliases.get(type1.lower(), type1.lower())
        t2 = type_aliases.get(type2.lower(), type2.lower())

        return t1 == t2

    def _compare_indexes(
        self,
        expected: SchemaInfo,
        actual: SchemaInfo,
        report: DriftReport,
    ) -> None:
        """Compare indexes between schemas."""
        for table in expected.indexes:
            if table in self.ignore_tables:
                continue

            exp_indexes = set(expected.indexes.get(table, []))
            act_indexes = set(actual.indexes.get(table, []))

            # Missing indexes
            for idx in sorted(exp_indexes - act_indexes):
                report.indexes_checked += 1
                report.drift_items.append(
                    DriftItem(
                        drift_type=DriftType.MISSING_INDEX,
                        severity=DriftSeverity.WARNING,
                        object_name=f"{table}.{idx}",
                        expected=idx,
                        actual=None,
                        message=f"Index '{idx}' on '{table}' is missing",
                    )
                )

            # Extra indexes
            for idx in sorted(act_indexes - exp_indexes):
                report.indexes_checked += 1
                report.drift_items.append(
                    DriftItem(
                        drift_type=DriftType.EXTRA_INDEX,
                        severity=DriftSeverity.INFO,
                        object_name=f"{table}.{idx}",
                        expected=None,
                        actual=idx,
                        message=f"Index '{idx}' on '{table}' exists but is not expected",
                    )
                )

    def get_live_schema(self) -> SchemaInfo:
        """Get the current live database schema.

        Returns:
            SchemaInfo with current database state
        """
        return self.analyzer.get_schema_info(refresh=True)

    def compare_with_expected(self, expected: SchemaInfo) -> DriftReport:
        """Compare live database with expected schema.

        Args:
            expected: Expected schema state

        Returns:
            DriftReport with differences
        """
        actual = self.get_live_schema()
        report = self.compare_schemas(expected, actual)
        report.expected_schema_source = "provided"
        return report

    def compare_with_schema_file(self, schema_file_path: str) -> DriftReport:
        """Compare live database with a schema SQL file.

        This parses a SQL schema file to extract expected schema.

        Args:
            schema_file_path: Path to schema SQL file

        Returns:
            DriftReport with differences
        """
        from pathlib import Path

        path = Path(schema_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file_path}")

        sql_content = path.read_text()
        expected = self._parse_schema_from_sql(sql_content)

        actual = self.get_live_schema()
        report = self.compare_schemas(expected, actual)
        report.expected_schema_source = f"file:{schema_file_path}"
        return report

    def _parse_schema_from_sql(self, sql: str) -> SchemaInfo:
        """Parse SQL DDL to extract schema information.

        This is a simplified parser that extracts table and column info
        from CREATE TABLE statements.

        Args:
            sql: SQL DDL statements

        Returns:
            SchemaInfo extracted from SQL
        """
        import re

        import sqlparse

        info = SchemaInfo()

        # Parse CREATE TABLE statements
        statements = sqlparse.parse(sql)
        for stmt in statements:
            stmt_str = str(stmt).strip()
            if not stmt_str:
                continue

            # Check for CREATE TABLE
            match = re.match(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
                stmt_str,
                re.IGNORECASE,
            )
            if match:
                table_name = match.group(1).lower()
                columns = self._extract_columns_from_create(stmt_str)
                info.tables[table_name] = columns

            # Check for CREATE INDEX
            match = re.match(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
                r"(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?\s+ON\s+(?:\")?(\w+)(?:\")?",
                stmt_str,
                re.IGNORECASE,
            )
            if match:
                index_name = match.group(1).lower()
                table_name = match.group(2).lower()
                if table_name not in info.indexes:
                    info.indexes[table_name] = []
                info.indexes[table_name].append(index_name)

        return info

    def _extract_columns_from_create(self, create_stmt: str) -> dict[str, dict]:
        """Extract column definitions from CREATE TABLE statement."""
        import re

        columns: dict[str, dict] = {}

        # Find the column definitions between parentheses
        match = re.search(r"\((.*)\)", create_stmt, re.DOTALL)
        if not match:
            return columns

        definitions = match.group(1)

        # Split by comma, but be careful about nested parentheses
        parts = self._split_column_definitions(definitions)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            upper_part = part.upper()

            # Skip table-level constraints (start with constraint keywords)
            # But NOT column definitions that happen to have PRIMARY KEY inline
            constraint_starters = [
                "PRIMARY KEY",
                "FOREIGN KEY",
                "UNIQUE",
                "CHECK",
                "CONSTRAINT",
            ]
            if any(upper_part.startswith(kw) for kw in constraint_starters):
                continue

            # Parse column definition
            col_match = re.match(r"(?:\")?(\w+)(?:\")?\s+(\w+(?:\([^)]*\))?)", part)
            if col_match:
                col_name = col_match.group(1).lower()
                col_type = col_match.group(2).lower()

                # Check for NOT NULL (PRIMARY KEY implies NOT NULL)
                nullable = "NOT NULL" not in upper_part and "PRIMARY KEY" not in upper_part

                columns[col_name] = {
                    "type": col_type,
                    "nullable": nullable,
                    "default": None,
                }

        return columns

    def _split_column_definitions(self, definitions: str) -> list[str]:
        """Split column definitions respecting parentheses."""
        parts = []
        current = []
        depth = 0

        for char in definitions:
            if char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(char)

        if current:
            parts.append("".join(current))

        return parts

    def _get_database_name(self) -> str:
        """Get current database name."""
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            result = cur.fetchone()
            return result[0] if result else "unknown"
