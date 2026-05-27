"""Schema drift detection for Confiture.

Compares live database schema against expected state from migrations
to detect unauthorized changes or migration mishaps.
"""

import fnmatch
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import psycopg

from confiture.core.schema_analyzer import SchemaAnalyzer, SchemaInfo

if TYPE_CHECKING:
    from confiture.config.environment import (
        AclExpectation,
        AclGrant,
        OwnershipExpectation,
    )

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
    MISSING_GRANT = "missing_grant"
    EXTRA_GRANT = "extra_grant"
    WRONG_OWNER = "wrong_owner"


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
        "tb_confiture",
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


class AclDriftDetector:
    """Detect ACL drift between live ``pg_class.relacl`` and the ``acls:`` config.

    Two query paths — kept visually separate by design:

    * :meth:`_check_missing` uses ``has_table_privilege(role, table, priv)``.
      That's a hypothesis-check: it answers "does this role hold this
      privilege?" and transparently handles role-membership inheritance,
      ``PUBLIC``, and ownership.  One question per ``(table, role, priv)``.

    * :meth:`_check_extra` uses ``information_schema.role_table_grants``.
      That's an enumeration of *directly granted* privileges per role on
      a table.  We need enumeration here because ``has_table_privilege``
      cannot say what *else* a role holds, only confirm or deny a guess.
      Privileges held only via ``PUBLIC`` (or via owner-implicit rules)
      are deliberately not in this view, so they don't show up as extras.

    System tables (``tb_confiture`` etc.) are excluded via the same
    :pyattr:`SchemaDriftDetector.SYSTEM_TABLES` set.

    Example::

        from confiture.config.environment import Environment
        from confiture.core.drift import AclDriftDetector

        env = Environment.load("production")
        with psycopg.connect(env.database_url) as conn:
            report = AclDriftDetector(conn).check(env.acls)
            if report.has_critical_drift:
                raise SystemExit(1)
    """

    # Reuse the same exclusion set as the structural detector so confiture's
    # own tracking tables never count as drift.
    SYSTEM_TABLES = SchemaDriftDetector.SYSTEM_TABLES

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def check(self, expectations: "list[AclExpectation]") -> DriftReport:
        """Compare every expectation against the live ACL state.

        Returns a :class:`DriftReport` with the originating database name
        baked in and one :class:`DriftItem` per ``(schema, table, role,
        priv)`` gap.  ``report.has_drift is False`` means the live ACLs
        match the spec.

        The shape matches :meth:`SchemaDriftDetector.compare_with_schema_file`
        so library consumers can compose both detectors uniformly — see
        :meth:`DriftReport` for the available helpers.
        """
        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="acls",
        )
        for expectation in expectations:
            tables = self._discover_tables(
                expectation.schema_, expectation.apply_to, expectation.ignore
            )
            for table in tables:
                report.tables_checked += 1
                for grant in expectation.grants:
                    missing = self._check_missing(expectation.schema_, table, grant)
                    if missing is not None:
                        report.drift_items.append(missing)
                    extras = self._check_extra(expectation.schema_, table, grant)
                    if extras is not None:
                        report.drift_items.append(extras)
        return report

    def _get_database_name(self) -> str:
        """Return the current database name for inclusion in the report."""
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    # ------------------------------------------------------------------ #
    # Table discovery                                                    #
    # ------------------------------------------------------------------ #

    # relkind values that count as "a table whose grants we care about":
    #   ``r`` — regular base tables.
    #   ``p`` — partitioned parents (relkind='p').  Grants here propagate
    #          to children automatically, so we MUST include parents in
    #          discovery or we'd silently miss their coverage gaps.
    # Excluded: ``v`` (view), ``m`` (materialized view), ``f`` (foreign),
    # ``i``/``I`` (indexes), ``t`` (TOAST), ``S`` (sequence).
    _INCLUDED_RELKINDS = ("r", "p")

    def _discover_tables(
        self,
        schema: str,
        apply_to: "str | list[str]",
        ignore: list[str],
    ) -> list[str]:
        """Return base-table relnames in *schema* matching *apply_to*, less *ignore*.

        Includes regular tables (``relkind = 'r'``) and partitioned parents
        (``relkind = 'p'``).  Partition *children* (``relispartition = true``)
        are excluded — grants on the parent propagate, and listing the child
        as a separate target would spuriously surface ``EXTRA_GRANT`` items
        for the inherited privileges.  Glob filtering happens in Python
        via :mod:`fnmatch`; the SQL side only constrains the schema.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind = ANY(%s)
                  AND c.relispartition = false
                ORDER BY c.relname
                """,
                (schema, list(self._INCLUDED_RELKINDS)),
            )
            relnames = [row[0] for row in cur.fetchall()]

        # Drop confiture's own tracking tables.
        relnames = [r for r in relnames if r not in self.SYSTEM_TABLES]

        # Apply pattern filter unless "ALL_TABLES".
        if apply_to != "ALL_TABLES":
            patterns = list(apply_to)
            relnames = [r for r in relnames if any(fnmatch.fnmatchcase(r, p) for p in patterns)]

        # Drop tables matching any ignore glob.
        if ignore:
            relnames = [r for r in relnames if not any(fnmatch.fnmatchcase(r, p) for p in ignore)]

        return relnames

    # ------------------------------------------------------------------ #
    # MISSING_GRANT — hypothesis check via has_table_privilege            #
    # ------------------------------------------------------------------ #

    def _check_missing(
        self,
        schema: str,
        table: str,
        grant: "AclGrant",
    ) -> DriftItem | None:
        """Return a single ``MISSING_GRANT`` item if *role* lacks any expected priv.

        Uses ``has_table_privilege`` because it transparently handles
        ``PUBLIC``, role-membership inheritance, and ownership — those
        confer privileges that ``information_schema.role_table_grants``
        does not enumerate, so checking the direct-grants view here
        would produce false positives for any role that inherits a
        privilege.

        Identifiers are quoted via :class:`psycopg.sql.Identifier` and
        passed as a *text literal* that ``::regclass`` resolves, so
        mixed-case tables created with ``CREATE TABLE "MyTable" …`` are
        looked up without case-folding.  Inlining the qualified name as
        bare SQL (``"schema"."table"::regclass``) would be parsed as a
        column reference (``column "table" of table "schema"``) and
        fail with ``missing FROM-clause entry`` — the text-cast form
        avoids that pitfall entirely.
        """
        # SQL-side qualifier needs the double-quoted form so mixed-case
        # relnames survive regclass lookup; the human-friendly object_name
        # used in DriftItem stays unquoted for display consistency with
        # OwnershipDriftDetector and the existing structural diff items.
        qualified_sql = f'"{schema}"."{table}"'
        display_name = f"{schema}.{table}"
        # ``has_table_privilege(role, table_oid, priv)`` takes a regclass.
        # Pass the qualified name as a TEXT parameter to ``::regclass``
        # so PostgreSQL resolves it through the regclass input function
        # rather than parsing it as a column reference.
        priv_query = "SELECT has_table_privilege(%s, %s::regclass, %s)"

        missing: list[str] = []
        for priv in grant.privileges:
            with self.connection.cursor() as cur:
                try:
                    cur.execute(priv_query, (grant.role, qualified_sql, priv))
                    row = cur.fetchone()
                except (
                    psycopg.errors.UndefinedObject,
                    psycopg.errors.UndefinedTable,
                ) as e:
                    # Role or table doesn't exist.  Treat as informational
                    # warning (role-not-present is itself a finding worth
                    # reporting, but it isn't a CRITICAL coverage gap).
                    self.connection.rollback()
                    cause = str(e)
                    # When the missing object looks like the table itself
                    # (i.e. an unquoted lookup of a quoted relname),
                    # surface that explicitly so the operator can fix it
                    # rather than chasing the role.
                    if "does not exist" in cause and table.lower() != table:
                        hint = (
                            " (mixed-case identifier — check that the live "
                            "table name in pg_class matches the spec exactly)"
                        )
                    else:
                        hint = ""
                    return DriftItem(
                        drift_type=DriftType.MISSING_GRANT,
                        severity=DriftSeverity.WARNING,
                        object_name=f"{display_name}({grant.role})",
                        expected=", ".join(grant.privileges),
                        actual=None,
                        message=(
                            f"Cannot verify grants for role '{grant.role}' "
                            f"on '{display_name}': {cause}{hint}"
                        ),
                    )
                if row is not None and row[0] is False:
                    missing.append(priv)
        if not missing:
            return None
        return DriftItem(
            drift_type=DriftType.MISSING_GRANT,
            severity=DriftSeverity.CRITICAL,
            object_name=f"{display_name}({grant.role})",
            expected=", ".join(grant.privileges),
            actual=None,
            message=(
                f"Role '{grant.role}' is missing grant(s) "
                f"{', '.join(missing)} on '{display_name}'"
            ),
        )

    # ------------------------------------------------------------------ #
    # EXTRA_GRANT — enumeration via information_schema.role_table_grants  #
    # ------------------------------------------------------------------ #

    def _check_extra(
        self,
        schema: str,
        table: str,
        grant: "AclGrant",
    ) -> DriftItem | None:
        """Return an ``EXTRA_GRANT`` item if *role* directly holds privileges beyond expected.

        Enumeration via ``information_schema.role_table_grants`` lists
        only *directly granted* privileges; ``PUBLIC`` and ownership
        rules are not in that view by design, so privileges held
        indirectly do not surface as extras (matches operator intent —
        you can't revoke what you didn't grant).
        """
        qualified = f"{schema}.{table}"
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = %s
                  AND table_schema = %s
                  AND table_name = %s
                """,
                (grant.role, schema, table),
            )
            actual = {row[0].upper() for row in cur.fetchall()}

        expected = set(grant.privileges)
        extras = sorted(actual - expected)
        if not extras:
            return None
        return DriftItem(
            drift_type=DriftType.EXTRA_GRANT,
            severity=DriftSeverity.WARNING,
            object_name=f"{qualified}({grant.role})",
            expected=", ".join(sorted(expected)) or "(none)",
            actual=", ".join(extras),
            message=(
                f"Role '{grant.role}' has unexpected grant(s) {', '.join(extras)} on '{qualified}'"
            ),
        )


class OwnershipDriftDetector:
    """Detect ownership drift between ``pg_class.relowner`` and the ``ownership:`` config.

    Issue #124 — the ownership axis of the same drift class that
    :class:`AclDriftDetector` covers on the ACL axis.

    Discovery query is a single SELECT against ``pg_class`` filtered by
    schema and ``relkind``.  Partition children (``relispartition =
    true``) are NOT excluded — Postgres allows each partition to have a
    distinct owner, and a drifted child is exactly the kind of mistake
    this detector exists to catch.  The ``ignore:`` glob list is
    evaluated Python-side after the query so the SQL stays simple and
    the cross-schema globs (``*.legacy_audit_log``) work uniformly.

    System tables (``tb_confiture`` etc.) are excluded via the same
    :pyattr:`SchemaDriftDetector.SYSTEM_TABLES` set.

    Example::

        from confiture.config.environment import Environment
        from confiture.core.drift import OwnershipDriftDetector

        env = Environment.load("production")
        with psycopg.connect(env.database_url) as conn:
            report = OwnershipDriftDetector(conn).check(env.ownership)
            if report.has_critical_drift:
                raise SystemExit(1)
    """

    SYSTEM_TABLES = SchemaDriftDetector.SYSTEM_TABLES

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def check(self, expectation: "OwnershipExpectation") -> DriftReport:
        """Compare every reachable relation against the expected owner.

        Returns a :class:`DriftReport` with one :class:`DriftItem` per
        relation whose actual owner differs from ``expected_owner``.
        ``report.has_drift is False`` means every in-scope relation has
        the canonical owner.
        """
        report = DriftReport(
            database_name=self._get_database_name(),
            expected_schema_source="ownership",
        )
        for apply_entry in expectation.apply_to:
            relations = self._discover_relations(
                apply_entry.schema_, apply_entry.relkinds, expectation.ignore
            )
            for schema, relname, _relkind, actual_owner in relations:
                report.tables_checked += 1
                if actual_owner != expectation.expected_owner:
                    qualified = f"{schema}.{relname}"
                    report.drift_items.append(
                        DriftItem(
                            drift_type=DriftType.WRONG_OWNER,
                            severity=DriftSeverity.CRITICAL,
                            object_name=qualified,
                            expected=expectation.expected_owner,
                            actual=actual_owner,
                            message=(
                                f"Relation '{qualified}' is owned by "
                                f"'{actual_owner}' but expected owner is "
                                f"'{expectation.expected_owner}'"
                            ),
                        )
                    )
        return report

    def _get_database_name(self) -> str:
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    def _discover_relations(
        self,
        schema: str,
        relkinds: list[str],
        ignore_patterns: list[str],
    ) -> list[tuple[str, str, str, str]]:
        """Return ``(schema, relname, relkind, owner)`` tuples in scope.

        Filters out system tables and any qualified name matching an
        ``ignore`` glob.  Ignore patterns may be either ``schema.name``
        or a glob form like ``*.audit_log`` evaluated against the
        ``schema.relname`` qualified form.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname,
                       c.relname,
                       c.relkind,
                       pg_get_userbyid(c.relowner) AS owner
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind = ANY(%s)
                ORDER BY n.nspname, c.relname
                """,
                (schema, list(relkinds)),
            )
            rows: list[tuple[str, str, str, str]] = [
                (row[0], row[1], row[2], row[3]) for row in cur.fetchall()
            ]

        rows = [r for r in rows if r[1] not in self.SYSTEM_TABLES]

        if ignore_patterns:
            rows = [
                r
                for r in rows
                if not _matches_any_glob(f"{r[0]}.{r[1]}", ignore_patterns)
            ]

        return rows


def _matches_any_glob(qualified_name: str, patterns: list[str]) -> bool:
    """Return ``True`` iff *qualified_name* matches any *patterns* glob.

    Patterns may be either literal ``schema.name`` or a glob form like
    ``*.audit_log`` or ``tenant.*_legacy``.  Uses :mod:`fnmatch`'s
    case-sensitive ``fnmatchcase`` to mirror :class:`AclDriftDetector`.
    """
    return any(fnmatch.fnmatchcase(qualified_name, p) for p in patterns)
