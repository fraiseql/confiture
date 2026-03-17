"""Schema differ for detecting database schema changes.

This module provides functionality to:
- Parse SQL DDL statements into structured schema models
- Compare two schemas and detect differences
- Generate migrations from schema diffs
"""

import re
from typing import Any

import sqlparse
from sqlparse.exceptions import SQLParseError as _SqlParseError
from sqlparse.sql import Identifier, Parenthesis, Statement
from sqlparse.tokens import Keyword, Name

from confiture.models.schema import (
    CheckConstraint,
    Column,
    ColumnType,
    EnumType,
    ForeignKey,
    Index,
    ParsedSchema,
    SchemaChange,
    SchemaDiff,
    Sequence,
    Table,
    UniqueConstraint,
)

# ---------------------------------------------------------------------------
# Module-level constants: compiled once for performance
# ---------------------------------------------------------------------------

_COLUMN_TYPE_MAP: dict[str, ColumnType] = {
    "SMALLINT": ColumnType.SMALLINT,
    "INT2": ColumnType.SMALLINT,
    "INT": ColumnType.INTEGER,
    "INTEGER": ColumnType.INTEGER,
    "INT4": ColumnType.INTEGER,
    "BIGINT": ColumnType.BIGINT,
    "INT8": ColumnType.BIGINT,
    "SERIAL": ColumnType.SERIAL,
    "BIGSERIAL": ColumnType.BIGSERIAL,
    "NUMERIC": ColumnType.NUMERIC,
    "DECIMAL": ColumnType.DECIMAL,
    "REAL": ColumnType.REAL,
    "FLOAT4": ColumnType.REAL,
    "DOUBLE": ColumnType.DOUBLE_PRECISION,
    "FLOAT8": ColumnType.DOUBLE_PRECISION,
    "DOUBLE PRECISION": ColumnType.DOUBLE_PRECISION,
    "VARCHAR": ColumnType.VARCHAR,
    "CHARACTER VARYING": ColumnType.VARCHAR,
    "CHAR": ColumnType.CHAR,
    "CHARACTER": ColumnType.CHAR,
    "TEXT": ColumnType.TEXT,
    "BOOLEAN": ColumnType.BOOLEAN,
    "BOOL": ColumnType.BOOLEAN,
    "DATE": ColumnType.DATE,
    "TIME": ColumnType.TIME,
    "TIMETZ": ColumnType.TIME,
    "TIMESTAMP": ColumnType.TIMESTAMP,
    "TIMESTAMP WITHOUT TIME ZONE": ColumnType.TIMESTAMP,
    "TIMESTAMPTZ": ColumnType.TIMESTAMPTZ,
    "TIMESTAMP WITH TIME ZONE": ColumnType.TIMESTAMPTZ,
    "UUID": ColumnType.UUID,
    "JSON": ColumnType.JSON,
    "JSONB": ColumnType.JSONB,
    "BYTEA": ColumnType.BYTEA,
    # Network types
    "CIDR": ColumnType.CIDR,
    "INET": ColumnType.INET,
    "MACADDR": ColumnType.MACADDR,
    "MACADDR8": ColumnType.MACADDR8,
    # Money
    "MONEY": ColumnType.MONEY,
    # Bit strings
    "BIT": ColumnType.BIT,
    "VARBIT": ColumnType.VARBIT,
    "BIT VARYING": ColumnType.VARBIT,
    # Text search
    "TSVECTOR": ColumnType.TSVECTOR,
    "TSQUERY": ColumnType.TSQUERY,
    # XML
    "XML": ColumnType.XML,
    # Range types
    "INT4RANGE": ColumnType.INT4RANGE,
    "INT8RANGE": ColumnType.INT8RANGE,
    "NUMRANGE": ColumnType.NUMRANGE,
    "TSRANGE": ColumnType.TSRANGE,
    "TSTZRANGE": ColumnType.TSTZRANGE,
    "DATERANGE": ColumnType.DATERANGE,
}

# Regex patterns for ALTER TABLE / CREATE TYPE / CREATE SEQUENCE / CREATE INDEX
_FK_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\w+\.)?(?P<table>\w+)\s+ADD\s+CONSTRAINT\s+(?P<name>\w+)"
    r"\s+FOREIGN\s+KEY\s*\((?P<cols>[^)]+)\)"
    r"\s+REFERENCES\s+(?:(?P<ref_schema>\w+)\.)?(?P<ref_table>\w+)\s*\((?P<ref_cols>[^)]+)\)"
    r"(?:\s+ON\s+DELETE\s+(?P<on_delete>\w+(?:\s+\w+)?))?",
    re.IGNORECASE | re.DOTALL,
)

_CHECK_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\w+\.)?(?P<table>\w+)\s+ADD\s+CONSTRAINT\s+(?P<name>\w+)"
    r"\s+CHECK\s*\((?P<expr>.+?)\)\s*;?",
    re.IGNORECASE | re.DOTALL,
)

_UNIQUE_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\w+\.)?(?P<table>\w+)\s+ADD\s+CONSTRAINT\s+(?P<name>\w+)"
    r"\s+UNIQUE\s*\((?P<cols>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)

_ENUM_RE = re.compile(
    r"CREATE\s+TYPE\s+(?:(?P<schema>\w+)\.)?(?P<name>\w+)"
    r"\s+AS\s+ENUM\s*\((?P<values>[^)]+)\)",
    re.IGNORECASE,
)

_SEQ_RE = re.compile(
    r"CREATE\s+SEQUENCE\s+(?:(?P<schema>\w+)\.)?(?P<name>\w+)"
    r"(?:\s+START(?:\s+WITH)?\s+(?P<start>\d+))?"
    r"(?:\s+INCREMENT(?:\s+BY)?\s+(?P<increment>\d+))?",
    re.IGNORECASE,
)

_INDEX_RE = re.compile(
    r"CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)\s+ON\s+(?:(?P<schema>\w+)\.)?(?P<table>\w+)"
    r"\s*\((?P<cols>[^)]+)\)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?(?:;|$)",
    re.IGNORECASE | re.DOTALL,
)

# DDL statement prefixes — used to filter out non-DDL (INSERT, COPY, GRANT, etc.)
# before passing individual statements to sqlparse (avoids MAX_GROUPING_TOKENS crash).
_DDL_PREFIXES = ("CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT")

# pglast reports internal type aliases rather than the SQL keyword the user wrote.
# Map them back to the canonical names in _COLUMN_TYPE_MAP.
_PGLAST_TYPE_ALIASES: dict[str, str] = {
    "INT4": "INTEGER",
    "INT8": "BIGINT",
    "INT2": "SMALLINT",
    "FLOAT4": "REAL",
    "FLOAT8": "DOUBLE PRECISION",
    "BOOL": "BOOLEAN",
}

# pglast FK on-delete action code → human-readable string
_PG_FK_DEL_ACTION: dict[str, str | None] = {
    "c": "CASCADE",
    "a": "SET NULL",
    "d": "NO ACTION",
    "r": "RESTRICT",
    "p": "SET DEFAULT",
    "": None,
    "\x00": None,
}

# Inline constraint patterns (inside CREATE TABLE body)
_INLINE_FK_RE = re.compile(
    r"CONSTRAINT\s+(?P<name>\w+)\s+FOREIGN\s+KEY\s*\((?P<cols>[^)]+)\)"
    r"\s+REFERENCES\s+(?:(?P<ref_schema>\w+)\.)?(?P<ref_table>\w+)\s*\((?P<ref_cols>[^)]+)\)"
    r"(?:\s+ON\s+DELETE\s+(?P<on_delete>\w+(?:\s+\w+)?))?",
    re.IGNORECASE | re.DOTALL,
)

_INLINE_CHECK_RE = re.compile(
    r"CONSTRAINT\s+(?P<name>\w+)\s+CHECK\s*\((?P<expr>.+)\)",
    re.IGNORECASE | re.DOTALL,
)

_INLINE_UNIQUE_RE = re.compile(
    r"CONSTRAINT\s+(?P<name>\w+)\s+UNIQUE\s*\((?P<cols>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)


class SchemaDiffer:
    """Parses SQL and detects schema differences.

    Example:
        >>> differ = SchemaDiffer()
        >>> tables = differ.parse_sql("CREATE TABLE users (id INT)")
        >>> print(tables[0].name)
        users
    """

    def parse_sql(self, sql: str) -> list[Table]:
        """Parse SQL DDL into structured Table objects (backwards-compatible shim).

        Args:
            sql: SQL DDL string containing CREATE TABLE statements

        Returns:
            List of parsed Table objects

        Example:
            >>> differ = SchemaDiffer()
            >>> sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
            >>> tables = differ.parse_sql(sql)
            >>> print(len(tables))
            1
        """
        return self.parse_schema(sql).tables

    def parse_schema(self, sql: str) -> ParsedSchema:
        """Parse SQL DDL into a ParsedSchema (tables, enums, sequences).

        Uses pglast (PostgreSQL's own parser) when available for accurate,
        limit-free parsing. Falls back to sqlparse when pglast is not installed.
        Non-DDL statements (INSERT, COPY, GRANT, etc.) are silently ignored.

        Args:
            sql: SQL DDL string (may contain any SQL, including non-DDL)

        Returns:
            ParsedSchema with tables, enum_types, sequences
        """
        if not sql or not sql.strip():
            return ParsedSchema()

        result = ParsedSchema()

        # Primary path: pglast — uses PostgreSQL's actual C parser, no token limits.
        # Falls back to sqlparse when pglast is not installed (optional dependency).
        try:
            import pglast  # noqa: PLC0415

            self._parse_create_tables_pglast(sql, result, pglast)
        except ImportError:
            self._parse_create_tables_sqlparse(sql, result)

        # Regex pass: CREATE INDEX / TYPE AS ENUM / SEQUENCE / ALTER TABLE ADD CONSTRAINT.
        # These are more reliably matched by regex than by either AST parser, and regex
        # has no token-count limits.
        self._parse_alter_table(sql, result)

        for m in _INDEX_RE.finditer(sql):
            cols = [c.strip() for c in m.group("cols").split(",")]
            table_name = m.group("table")
            idx = Index(
                name=m.group("name"),
                table=table_name,
                columns=cols,
                unique=bool(m.group("unique")),
                where=m.group("where"),
            )
            for t in result.tables:
                if t.name == table_name:
                    t.indexes.append(idx)
                    break

        for m in _ENUM_RE.finditer(sql):
            raw_values = m.group("values")
            values = [v.strip().strip("'\"") for v in raw_values.split(",")]
            result.enum_types.append(
                EnumType(name=m.group("name"), schema=m.group("schema"), values=values)
            )

        for m in _SEQ_RE.finditer(sql):
            result.sequences.append(
                Sequence(
                    name=m.group("name"),
                    schema=m.group("schema"),
                    start=int(m.group("start")) if m.group("start") else 1,
                    increment=int(m.group("increment")) if m.group("increment") else 1,
                )
            )

        return result

    # ------------------------------------------------------------------
    # pglast-based CREATE TABLE parser (primary path)
    # ------------------------------------------------------------------

    def _parse_create_tables_pglast(self, sql: str, result: ParsedSchema, pglast: Any) -> None:
        """Parse CREATE TABLE statements using pglast (PostgreSQL's own parser).

        pglast has no token/recursion limits and handles all PostgreSQL syntax.
        Falls back to the sqlparse path on any parse error.

        Args:
            sql: Full SQL text (may contain any statements)
            result: ParsedSchema to populate
            pglast: The already-imported pglast module
        """
        try:
            tree = pglast.parse_sql(sql)
        except Exception:
            # pglast parse error (e.g. non-PostgreSQL syntax) — fall back to sqlparse
            self._parse_create_tables_sqlparse(sql, result)
            return

        if tree is None:
            return

        for stmt_wrapper in tree:
            stmt = stmt_wrapper.stmt
            if type(stmt).__name__ == "CreateStmt":
                table = self._parse_create_table_pglast(stmt)
                if table:
                    result.tables.append(table)

    def _parse_create_table_pglast(self, stmt: Any) -> Table | None:
        """Build a Table model from a pglast CreateStmt node."""
        try:
            from pglast.enums.parsenodes import ConstrType  # noqa: PLC0415

            table = Table(name=stmt.relation.relname)

            for elt in stmt.tableElts or []:
                if type(elt).__name__ == "ColumnDef":
                    col = self._parse_column_pglast(elt, ConstrType)
                    if col:
                        table.columns.append(col)
                elif type(elt).__name__ == "Constraint":
                    self._parse_table_constraint_pglast(elt, table, ConstrType)

            return table
        except Exception:
            return None

    def _parse_column_pglast(self, col_def: Any, ConstrType: Any) -> Column | None:
        """Build a Column model from a pglast ColumnDef node."""
        try:
            # Extract type name: last entry in typeName.names (skip 'pg_catalog' prefix)
            names = [n.sval for n in col_def.typeName.names]
            raw_type_str = names[-1].upper()
            lookup_str = _PGLAST_TYPE_ALIASES.get(raw_type_str, raw_type_str)
            col_type = _COLUMN_TYPE_MAP.get(lookup_str, ColumnType.UNKNOWN)
            raw_sql_type = raw_type_str.lower() if col_type == ColumnType.UNKNOWN else None

            # Extract length from first typmod (VARCHAR(N), NUMERIC(P,S), etc.)
            length: int | None = None
            typmods = col_def.typeName.typmods
            if typmods:
                first = typmods[0]
                if type(first).__name__ == "A_Const" and hasattr(first, "val"):
                    val = first.val
                    if type(val).__name__ == "Integer":
                        length = val.ival

            # Array column (INT[], TEXT[], etc.) → UNKNOWN with raw type preserved
            if col_def.typeName.arrayBounds:
                col_type = ColumnType.UNKNOWN
                raw_sql_type = raw_type_str.lower() + "[]"

            nullable = True
            primary_key = False
            default: str | None = None

            for constraint in col_def.constraints or []:
                ctype = constraint.contype
                if ctype == ConstrType.CONSTR_NOTNULL:
                    nullable = False
                elif ctype == ConstrType.CONSTR_PRIMARY:
                    primary_key = True
                    nullable = False
                elif ctype == ConstrType.CONSTR_DEFAULT:
                    default = self._render_default_pglast(constraint.raw_expr)

            return Column(
                name=col_def.colname,
                type=col_type,
                nullable=nullable,
                default=default,
                primary_key=primary_key,
                unique=False,
                length=length,
                raw_sql_type=raw_sql_type,
            )
        except Exception:
            return None

    def _parse_table_constraint_pglast(
        self, constraint: Any, table: Table, ConstrType: Any
    ) -> None:
        """Attach a table-level inline constraint (FK / CHECK / UNIQUE) to the table."""
        try:
            ctype = constraint.contype
            name = constraint.conname or ""

            if ctype == ConstrType.CONSTR_FOREIGN:
                fk_cols = [s.sval for s in (constraint.fk_attrs or [])]
                pk_cols = [s.sval for s in (constraint.pk_attrs or [])]
                ref_table = constraint.pktable.relname if constraint.pktable else ""
                on_delete = _PG_FK_DEL_ACTION.get(str(constraint.fk_del_action or ""))
                table.foreign_keys.append(
                    ForeignKey(
                        name=name,
                        table=table.name,
                        columns=fk_cols,
                        ref_table=ref_table,
                        ref_columns=pk_cols,
                        on_delete=on_delete,
                    )
                )
            elif ctype == ConstrType.CONSTR_CHECK:
                # Store the AST node type as a placeholder — identity-level comparison
                # (detecting that a CHECK constraint was added/removed) is what matters.
                expr = type(constraint.raw_expr).__name__ if constraint.raw_expr else ""
                table.check_constraints.append(
                    CheckConstraint(name=name, table=table.name, expression=expr)
                )
            elif ctype == ConstrType.CONSTR_UNIQUE:
                cols = [s.sval for s in (constraint.keys or [])]
                table.unique_constraints.append(
                    UniqueConstraint(name=name, table=table.name, columns=cols)
                )
        except Exception:
            pass

    def _render_default_pglast(self, raw_expr: Any) -> str | None:
        """Render a pglast default expression as a comparable string."""
        if raw_expr is None:
            return None
        ntype = type(raw_expr).__name__
        if ntype == "A_Const":
            if getattr(raw_expr, "isnull", False):
                return "NULL"
            val = getattr(raw_expr, "val", None)
            if val is None:
                return None
            vtype = type(val).__name__
            if vtype == "Integer":
                return str(val.ival)
            if vtype == "Float":
                return str(val.fval)
            if vtype == "String":
                return f"'{val.sval}'"
            if vtype == "Boolean":
                return "true" if val.boolval else "false"
        if ntype == "FuncCall":
            funcnames = [n.sval for n in (raw_expr.funcname or [])]
            return ".".join(funcnames) + "()"
        # TypeCast, ColumnRef, or other complex expression — non-None signals presence
        return "expression"

    # ------------------------------------------------------------------
    # sqlparse-based CREATE TABLE parser (fallback when pglast not installed)
    # ------------------------------------------------------------------

    def _parse_create_tables_sqlparse(self, sql: str, result: ParsedSchema) -> None:
        """Parse CREATE TABLE statements using sqlparse (fallback path).

        Splits the SQL into individual statements and filters to DDL-only
        before passing each to sqlparse, avoiding the MAX_GROUPING_TOKENS
        crash that occurs when a large combined string is parsed at once.

        Args:
            sql: Full SQL text
            result: ParsedSchema to populate
        """
        raw_statements = sqlparse.split(sql)
        for raw_stmt in raw_statements:
            if not raw_stmt.strip():
                continue
            upper = raw_stmt.lstrip().upper()
            if not any(upper.startswith(p) for p in _DDL_PREFIXES):
                continue
            try:
                parsed = sqlparse.parse(raw_stmt)
            except _SqlParseError:
                continue
            if not parsed:
                continue
            stmt = parsed[0]
            stmt_type: str | None = stmt.get_type()
            if stmt_type == "CREATE" and self._statement_has_keyword(stmt, "TABLE"):
                table = self._parse_create_table(stmt)
                if table:
                    result.tables.append(table)

    def _statement_has_keyword(self, stmt: Statement, keyword: str) -> bool:
        """Return True if the statement contains the given keyword token."""
        kw_upper = keyword.upper()
        return any(token.value.upper() == kw_upper for token in stmt.flatten())

    def _parse_alter_table(self, sql_text: str, result: ParsedSchema) -> None:
        """Parse ALTER TABLE ... ADD CONSTRAINT ... statements via regex."""
        for m in _FK_RE.finditer(sql_text):
            table_name = m.group("table")
            fk = ForeignKey(
                name=m.group("name"),
                table=table_name,
                columns=[c.strip() for c in m.group("cols").split(",")],
                ref_table=m.group("ref_table"),
                ref_columns=[c.strip() for c in m.group("ref_cols").split(",")],
                on_delete=m.group("on_delete"),
            )
            for t in result.tables:
                if t.name == table_name:
                    t.foreign_keys.append(fk)
                    break

        for m in _CHECK_RE.finditer(sql_text):
            table_name = m.group("table")
            cc = CheckConstraint(
                name=m.group("name"),
                table=table_name,
                expression=m.group("expr").strip(),
            )
            for t in result.tables:
                if t.name == table_name:
                    t.check_constraints.append(cc)
                    break

        for m in _UNIQUE_RE.finditer(sql_text):
            table_name = m.group("table")
            uc = UniqueConstraint(
                name=m.group("name"),
                table=table_name,
                columns=[c.strip() for c in m.group("cols").split(",")],
            )
            for t in result.tables:
                if t.name == table_name:
                    t.unique_constraints.append(uc)
                    break

    def compare(self, old_sql: str, new_sql: str) -> SchemaDiff:
        """Compare two schemas and detect changes.

        Args:
            old_sql: SQL DDL for the old schema
            new_sql: SQL DDL for the new schema

        Returns:
            SchemaDiff object containing list of changes

        Example:
            >>> differ = SchemaDiffer()
            >>> old = "CREATE TABLE users (id INT);"
            >>> new = "CREATE TABLE users (id INT, name TEXT);"
            >>> diff = differ.compare(old, new)
            >>> print(len(diff.changes))
            1
        """
        old_schema = self.parse_schema(old_sql)
        new_schema = self.parse_schema(new_sql)

        changes: list[SchemaChange] = []

        # --- Table-level changes ---
        old_table_map = {t.name: t for t in old_schema.tables}
        new_table_map = {t.name: t for t in new_schema.tables}

        old_table_names = set(old_table_map.keys())
        new_table_names = set(new_table_map.keys())

        renamed_tables = self._detect_table_renames(
            old_table_names - new_table_names, new_table_names - old_table_names
        )

        for old_name, new_name in renamed_tables.items():
            changes.append(
                SchemaChange(type="RENAME_TABLE", old_value=old_name, new_value=new_name)
            )
            old_table_names.discard(old_name)
            new_table_names.discard(new_name)

        for table_name in old_table_names - new_table_names:
            changes.append(SchemaChange(type="DROP_TABLE", table=table_name))

        for table_name in new_table_names - old_table_names:
            changes.append(SchemaChange(type="ADD_TABLE", table=table_name))

        for table_name in old_table_names & new_table_names:
            old_table = old_table_map[table_name]
            new_table = new_table_map[table_name]
            changes.extend(self._compare_table_columns(old_table, new_table))
            changes.extend(self._compare_indexes(old_table, new_table))
            changes.extend(self._compare_foreign_keys(old_table, new_table))
            changes.extend(self._compare_check_constraints(old_table, new_table))
            changes.extend(self._compare_unique_constraints(old_table, new_table))

        # --- Enum type changes ---
        changes.extend(self._compare_enum_types(old_schema.enum_types, new_schema.enum_types))

        # --- Sequence changes ---
        changes.extend(self._compare_sequences(old_schema.sequences, new_schema.sequences))

        return SchemaDiff(changes=changes)

    # ------------------------------------------------------------------
    # Table column comparison
    # ------------------------------------------------------------------

    def _detect_table_renames(self, old_names: set[str], new_names: set[str]) -> dict[str, str]:
        """Detect renamed tables using fuzzy matching."""
        renames: dict[str, str] = {}
        for old_name in old_names:
            best_match = self._find_best_match(old_name, new_names)
            if best_match and self._similarity_score(old_name, best_match) > 0.5:
                renames[old_name] = best_match
        return renames

    def _compare_table_columns(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Compare columns between two versions of the same table."""
        changes: list[SchemaChange] = []

        old_col_map = {c.name: c for c in old_table.columns}
        new_col_map = {c.name: c for c in new_table.columns}

        old_col_names = set(old_col_map.keys())
        new_col_names = set(new_col_map.keys())

        renamed_columns = self._detect_column_renames(
            old_col_names - new_col_names, new_col_names - old_col_names
        )

        for old_name, new_name in renamed_columns.items():
            changes.append(
                SchemaChange(
                    type="RENAME_COLUMN",
                    table=old_table.name,
                    old_value=old_name,
                    new_value=new_name,
                )
            )
            old_col_names.discard(old_name)
            new_col_names.discard(new_name)

        for col_name in old_col_names - new_col_names:
            changes.append(SchemaChange(type="DROP_COLUMN", table=old_table.name, column=col_name))

        for col_name in new_col_names - old_col_names:
            changes.append(SchemaChange(type="ADD_COLUMN", table=old_table.name, column=col_name))

        for col_name in old_col_names & new_col_names:
            old_col = old_col_map[col_name]
            new_col = new_col_map[col_name]
            changes.extend(self._compare_column_properties(old_table.name, old_col, new_col))

        return changes

    def _detect_column_renames(self, old_names: set[str], new_names: set[str]) -> dict[str, str]:
        """Detect renamed columns using fuzzy matching."""
        renames: dict[str, str] = {}
        for old_name in old_names:
            best_match = self._find_best_match(old_name, new_names)
            if best_match and self._similarity_score(old_name, best_match) > 0.5:
                renames[old_name] = best_match
        return renames

    def _compare_column_properties(
        self, table_name: str, old_col: Column, new_col: Column
    ) -> list[SchemaChange]:
        """Compare properties of a column."""
        changes: list[SchemaChange] = []

        # Type change — handle UNKNOWN types using raw_sql_type
        if old_col.type == new_col.type == ColumnType.UNKNOWN:
            if old_col.raw_sql_type != new_col.raw_sql_type:
                changes.append(
                    SchemaChange(
                        type="CHANGE_COLUMN_TYPE",
                        table=table_name,
                        column=old_col.name,
                        old_value=old_col.raw_sql_type,
                        new_value=new_col.raw_sql_type,
                    )
                )
        elif old_col.type != new_col.type:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_TYPE",
                    table=table_name,
                    column=old_col.name,
                    old_value=old_col.type.value,
                    new_value=new_col.type.value,
                )
            )

        if old_col.nullable != new_col.nullable:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_NULLABLE",
                    table=table_name,
                    column=old_col.name,
                    old_value="true" if old_col.nullable else "false",
                    new_value="true" if new_col.nullable else "false",
                )
            )

        if old_col.default != new_col.default:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_DEFAULT",
                    table=table_name,
                    column=old_col.name,
                    old_value=str(old_col.default) if old_col.default else None,
                    new_value=str(new_col.default) if new_col.default else None,
                )
            )

        return changes

    # ------------------------------------------------------------------
    # Index, FK, constraint, enum, sequence comparison helpers
    # ------------------------------------------------------------------

    def _compare_indexes(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped indexes."""
        return self._compare_named_objects(
            old_map={idx.name: idx for idx in old_table.indexes},
            new_map={idx.name: idx for idx in new_table.indexes},
            add_type="ADD_INDEX",
            drop_type="DROP_INDEX",
            table=old_table.name,
            detail_fn=lambda obj: {"index_name": obj.name, "columns": obj.columns},
        )

    def _compare_foreign_keys(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            old_map={fk.name: fk for fk in old_table.foreign_keys},
            new_map={fk.name: fk for fk in new_table.foreign_keys},
            add_type="ADD_FOREIGN_KEY",
            drop_type="DROP_FOREIGN_KEY",
            table=old_table.name,
            detail_fn=lambda obj: {
                "name": obj.name,
                "columns": obj.columns,
                "ref_table": obj.ref_table,
                "ref_columns": obj.ref_columns,
                "on_delete": obj.on_delete,
            },
        )

    def _compare_check_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            old_map={cc.name: cc for cc in old_table.check_constraints},
            new_map={cc.name: cc for cc in new_table.check_constraints},
            add_type="ADD_CHECK_CONSTRAINT",
            drop_type="DROP_CHECK_CONSTRAINT",
            table=old_table.name,
            detail_fn=lambda obj: {"name": obj.name, "expression": obj.expression},
        )

    def _compare_unique_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped unique constraints."""
        return self._compare_named_objects(
            old_map={uc.name: uc for uc in old_table.unique_constraints},
            new_map={uc.name: uc for uc in new_table.unique_constraints},
            add_type="ADD_UNIQUE_CONSTRAINT",
            drop_type="DROP_UNIQUE_CONSTRAINT",
            table=old_table.name,
            detail_fn=lambda obj: {"name": obj.name, "columns": obj.columns},
        )

    def _compare_enum_types(
        self, old_enums: list[EnumType], new_enums: list[EnumType]
    ) -> list[SchemaChange]:
        """Detect added / dropped / changed enum types."""
        changes: list[SchemaChange] = []
        old_map = {e.name: e for e in old_enums}
        new_map = {e.name: e for e in new_enums}

        for name in set(new_map) - set(old_map):
            changes.append(SchemaChange(type="ADD_ENUM_TYPE", table=name))

        for name in set(old_map) - set(new_map):
            changes.append(SchemaChange(type="DROP_ENUM_TYPE", table=name))

        for name in set(old_map) & set(new_map):
            old_vals = set(old_map[name].values)
            new_vals = set(new_map[name].values)
            if old_vals != new_vals:
                changes.append(
                    SchemaChange(
                        type="CHANGE_ENUM_VALUES",
                        table=name,
                        details={
                            "added_values": sorted(new_vals - old_vals),
                            "removed_values": sorted(old_vals - new_vals),
                        },
                    )
                )

        return changes

    def _compare_sequences(
        self, old_seqs: list[Sequence], new_seqs: list[Sequence]
    ) -> list[SchemaChange]:
        """Detect added / dropped sequences."""
        changes: list[SchemaChange] = []
        old_map = {s.name: s for s in old_seqs}
        new_map = {s.name: s for s in new_seqs}

        for name in set(new_map) - set(old_map):
            changes.append(SchemaChange(type="ADD_SEQUENCE", table=name))

        for name in set(old_map) - set(new_map):
            changes.append(SchemaChange(type="DROP_SEQUENCE", table=name))

        return changes

    def _compare_named_objects(
        self,
        old_map: dict,
        new_map: dict,
        add_type: str,
        drop_type: str,
        table: str,
        detail_fn: object,
    ) -> list[SchemaChange]:
        """Generic name-based add/drop comparison for indexes/constraints."""
        from collections.abc import Callable

        detail_fn_typed: Callable = detail_fn  # type: ignore[assignment]
        changes: list[SchemaChange] = []
        old_names = set(old_map.keys())
        new_names = set(new_map.keys())

        for name in new_names - old_names:
            obj = new_map[name]
            changes.append(
                SchemaChange(
                    type=add_type,
                    table=table,
                    details=detail_fn_typed(obj),
                )
            )

        for name in old_names - new_names:
            obj = old_map[name]
            changes.append(
                SchemaChange(
                    type=drop_type,
                    table=table,
                    details=detail_fn_typed(obj),
                )
            )

        return changes

    # ------------------------------------------------------------------
    # Fuzzy matching helpers
    # ------------------------------------------------------------------

    def _find_best_match(self, name: str, candidates: set[str]) -> str | None:
        """Find best matching name from candidates."""
        if not candidates:
            return None

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            score = self._similarity_score(name, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate

        return best_match

    def _similarity_score(self, name1: str, name2: str) -> float:
        """Calculate similarity score between two names (0.0 to 1.0).

        Uses multiple heuristics to detect renames:
        1. Common suffix/prefix patterns (e.g., "full_name" -> "display_name" = 0.5)
        2. Word-based similarity (e.g., "user_accounts" -> "user_profiles" = 0.5)
        3. Character-based Jaccard similarity
        """
        name1 = name1.lower()
        name2 = name2.lower()

        if name1 == name2:
            return 1.0

        name1_parts = name1.split("_")
        name2_parts = name2.split("_")

        if len(name1_parts) > 1 or len(name2_parts) > 1:
            if name1_parts[-1] == name2_parts[-1]:
                return 0.6
            if name1_parts[0] == name2_parts[0]:
                return 0.6

        name1_words = set(name1_parts)
        name2_words = set(name2_parts)
        common_words = name1_words & name2_words

        if common_words:
            return len(common_words) / len(name1_words | name2_words)

        name1_chars = set(name1)
        name2_chars = set(name2)
        common_chars = name1_chars & name2_chars

        if common_chars:
            return len(common_chars) / len(name1_chars | name2_chars)

        return 0.0

    # ------------------------------------------------------------------
    # SQL parsing helpers
    # ------------------------------------------------------------------

    def _parse_create_table(self, stmt: Statement) -> Table | None:
        """Parse a CREATE TABLE statement."""
        try:
            table_name = self._extract_table_name(stmt)
            if not table_name:
                return None

            table = Table(name=table_name)
            columns, inline_fks, inline_checks, inline_uniques = self._extract_columns(
                stmt, table_name
            )
            table.columns = columns
            table.foreign_keys = inline_fks
            table.check_constraints = inline_checks
            table.unique_constraints = inline_uniques

            return table

        except Exception:
            return None

    def _extract_table_name(self, stmt: Statement) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        found_create = False
        found_table = False

        for token in stmt.tokens:
            if token.is_whitespace:
                continue

            if token.ttype is Keyword.DDL and token.value.upper() == "CREATE":
                found_create = True
                continue

            if found_create and token.ttype is Keyword and token.value.upper() == "TABLE":
                found_table = True
                continue

            if found_table:
                if isinstance(token, Identifier):
                    return str(token.get_real_name())
                if token.ttype is Name:
                    return str(token.value)

        return None

    def _extract_columns(
        self, stmt: Statement, table_name: str
    ) -> tuple[list[Column], list[ForeignKey], list[CheckConstraint], list[UniqueConstraint]]:
        """Extract column definitions and inline constraints from CREATE TABLE."""
        columns: list[Column] = []
        fks: list[ForeignKey] = []
        checks: list[CheckConstraint] = []
        uniques: list[UniqueConstraint] = []

        column_def_parens = None
        for token in stmt.tokens:
            if isinstance(token, Parenthesis):
                column_def_parens = token
                break

        if not column_def_parens:
            return columns, fks, checks, uniques

        column_text = str(column_def_parens.value)[1:-1]
        column_parts = self._split_columns(column_text)

        for part in column_parts:
            stripped = part.strip()
            upper = stripped.upper()

            # Route inline constraints
            if upper.startswith("CONSTRAINT") or "FOREIGN KEY" in upper:
                fk, ck, uq = self._parse_inline_constraint(stripped, table_name)
                if fk:
                    fks.append(fk)
                if ck:
                    checks.append(ck)
                if uq:
                    uniques.append(uq)
                continue

            if upper.startswith("PRIMARY KEY") or upper.startswith("UNIQUE ("):
                # table-level PK/UNIQUE — skip (column-level already handled)
                continue

            column = self._parse_column_definition(stripped)
            if column:
                columns.append(column)

        return columns, fks, checks, uniques

    def _parse_inline_constraint(
        self, text: str, table_name: str
    ) -> tuple[ForeignKey | None, CheckConstraint | None, UniqueConstraint | None]:
        """Parse an inline CONSTRAINT clause from a CREATE TABLE body."""
        m = _INLINE_FK_RE.search(text)
        if m:
            return (
                ForeignKey(
                    name=m.group("name"),
                    table=table_name,
                    columns=[c.strip() for c in m.group("cols").split(",")],
                    ref_table=m.group("ref_table"),
                    ref_columns=[c.strip() for c in m.group("ref_cols").split(",")],
                    on_delete=m.group("on_delete"),
                ),
                None,
                None,
            )

        m = _INLINE_CHECK_RE.search(text)
        if m:
            return (
                None,
                CheckConstraint(
                    name=m.group("name"), table=table_name, expression=m.group("expr").strip()
                ),
                None,
            )

        m = _INLINE_UNIQUE_RE.search(text)
        if m:
            return (
                None,
                None,
                UniqueConstraint(
                    name=m.group("name"),
                    table=table_name,
                    columns=[c.strip() for c in m.group("cols").split(",")],
                ),
            )

        return None, None, None

    def _split_columns(self, text: str) -> list[str]:
        """Split column definitions by comma, respecting nested parentheses."""
        parts: list[str] = []
        current = []
        paren_depth = 0

        for char in text:
            if char == "(":
                paren_depth += 1
                current.append(char)
            elif char == ")":
                paren_depth -= 1
                current.append(char)
            elif char == "," and paren_depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(char)

        if current:
            parts.append("".join(current))

        return parts

    def _parse_column_definition(self, col_def: str) -> Column | None:
        """Parse a single column definition string."""
        try:
            parts = col_def.split()
            if len(parts) < 2:
                return None

            col_name = parts[0].strip("\"'")
            col_type_str = parts[1].upper()

            col_type, length = self._parse_column_type(col_type_str)
            raw_sql_type = col_type_str.lower() if col_type == ColumnType.UNKNOWN else None

            upper_def = col_def.upper()
            nullable = "NOT NULL" not in upper_def
            primary_key = "PRIMARY KEY" in upper_def
            unique = "UNIQUE" in upper_def and not primary_key

            default = self._extract_default(col_def)

            return Column(
                name=col_name,
                type=col_type,
                nullable=nullable,
                default=default,
                primary_key=primary_key,
                unique=unique,
                length=length,
                raw_sql_type=raw_sql_type,
            )

        except Exception:
            return None

    def _parse_column_type(self, type_str: str) -> tuple[ColumnType, int | None]:
        """Parse column type string into ColumnType and optional length.

        Args:
            type_str: Column type string (e.g., "VARCHAR(255)", "INT", "TIMESTAMP")

        Returns:
            Tuple of (ColumnType, length)
        """
        length = None
        match = re.match(r"([A-Z_]+)\((\d+)\)", type_str)
        if match:
            type_str = match.group(1)
            length = int(match.group(2))

        # Handle array types: INT[], TEXT[], etc.
        if type_str.endswith("[]"):
            base = type_str[:-2]
            base_type = _COLUMN_TYPE_MAP.get(base, ColumnType.UNKNOWN)
            if base_type == ColumnType.UNKNOWN:
                return ColumnType.UNKNOWN, length
            # Map to UNKNOWN with raw type preserved (array types stay UNKNOWN for now)
            return ColumnType.UNKNOWN, length

        col_type = _COLUMN_TYPE_MAP.get(type_str, ColumnType.UNKNOWN)
        return col_type, length

    def _extract_default(self, col_def: str) -> str | None:
        """Extract DEFAULT value from column definition."""
        match = re.search(r"DEFAULT\s+([^\s,]+)", col_def, re.IGNORECASE)
        if match:
            default_val = match.group(1)
            if "(" in default_val:
                start = match.start(1)
                text = col_def[start:]
                paren_count = 0
                end_idx = 0
                for i, char in enumerate(text):
                    if char == "(":
                        paren_count += 1
                    elif char == ")":
                        paren_count -= 1
                        if paren_count == 0:
                            end_idx = i + 1
                            break
                return text[:end_idx] if end_idx > 0 else default_val
            return default_val
        return None
