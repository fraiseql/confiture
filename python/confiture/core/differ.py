"""Schema differ for detecting database schema changes.

This module provides functionality to:
- Parse SQL DDL statements into structured schema models
- Compare two schemas and detect differences
- Generate migrations from schema diffs
"""

import re

import sqlparse
from sqlparse.sql import Identifier, Parenthesis, Statement
from sqlparse.tokens import Keyword, Name

from confiture.models.schema import Column, ColumnType, Table


class SchemaDiffer:
    """Parses SQL and detects schema differences.

    Example:
        >>> differ = SchemaDiffer()
        >>> tables = differ.parse_sql("CREATE TABLE users (id INT)")
        >>> print(tables[0].name)
        users
    """

    def parse_sql(self, sql: str) -> list[Table]:
        """Parse SQL DDL into structured Table objects.

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
        if not sql or not sql.strip():
            return []

        # Parse SQL into statements
        statements = sqlparse.parse(sql)

        tables: list[Table] = []
        for stmt in statements:
            if self._is_create_table(stmt):
                table = self._parse_create_table(stmt)
                if table:
                    tables.append(table)

        return tables

    def _is_create_table(self, stmt: Statement) -> bool:
        """Check if statement is a CREATE TABLE statement."""
        # Check if statement type is CREATE
        stmt_type: str | None = stmt.get_type()
        return bool(stmt_type == "CREATE")

    def _parse_create_table(self, stmt: Statement) -> Table | None:
        """Parse a CREATE TABLE statement."""
        try:
            # Extract table name
            table_name = self._extract_table_name(stmt)
            if not table_name:
                return None

            # Extract column definitions
            columns = self._extract_columns(stmt)

            return Table(name=table_name, columns=columns)

        except Exception:
            # Skip malformed statements
            return None

    def _extract_table_name(self, stmt: Statement) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        # Find the table name after CREATE TABLE keywords
        found_create = False
        found_table = False

        for token in stmt.tokens:
            if token.is_whitespace:
                continue

            # Check for CREATE keyword
            if token.ttype is Keyword.DDL and token.value.upper() == "CREATE":
                found_create = True
                continue

            # Check for TABLE keyword
            if found_create and token.ttype is Keyword and token.value.upper() == "TABLE":
                found_table = True
                continue

            # Next identifier is the table name
            if found_table:
                if isinstance(token, Identifier):
                    return str(token.get_real_name())
                if token.ttype is Name:
                    return str(token.value)

        return None

    def _extract_columns(self, stmt: Statement) -> list[Column]:
        """Extract column definitions from CREATE TABLE statement."""
        columns: list[Column] = []

        # Find the parenthesis containing column definitions
        column_def_parens = None
        for token in stmt.tokens:
            if isinstance(token, Parenthesis):
                column_def_parens = token
                break

        if not column_def_parens:
            return columns

        # Parse column definitions
        # Split on commas to get individual columns
        column_text = str(column_def_parens.value)[1:-1]  # Remove outer parens
        column_parts = self._split_columns(column_text)

        for part in column_parts:
            column = self._parse_column_definition(part.strip())
            if column:
                columns.append(column)

        return columns

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

            col_name = parts[0].strip('"\'')
            col_type_str = parts[1].upper()

            # Extract column type and length
            col_type, length = self._parse_column_type(col_type_str)

            # Parse constraints
            upper_def = col_def.upper()
            nullable = "NOT NULL" not in upper_def
            primary_key = "PRIMARY KEY" in upper_def
            unique = "UNIQUE" in upper_def and not primary_key

            # Extract default value
            default = self._extract_default(col_def)

            return Column(
                name=col_name,
                type=col_type,
                nullable=nullable,
                default=default,
                primary_key=primary_key,
                unique=unique,
                length=length,
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
        # Extract length from types like VARCHAR(255)
        length = None
        match = re.match(r"([A-Z]+)\((\d+)\)", type_str)
        if match:
            type_str = match.group(1)
            length = int(match.group(2))

        # Map SQL type to ColumnType enum
        type_mapping = {
            "SMALLINT": ColumnType.SMALLINT,
            "INT": ColumnType.INTEGER,
            "INTEGER": ColumnType.INTEGER,
            "BIGINT": ColumnType.BIGINT,
            "SERIAL": ColumnType.SERIAL,
            "BIGSERIAL": ColumnType.BIGSERIAL,
            "NUMERIC": ColumnType.NUMERIC,
            "DECIMAL": ColumnType.DECIMAL,
            "REAL": ColumnType.REAL,
            "DOUBLE": ColumnType.DOUBLE_PRECISION,
            "VARCHAR": ColumnType.VARCHAR,
            "CHAR": ColumnType.CHAR,
            "TEXT": ColumnType.TEXT,
            "BOOLEAN": ColumnType.BOOLEAN,
            "BOOL": ColumnType.BOOLEAN,
            "DATE": ColumnType.DATE,
            "TIME": ColumnType.TIME,
            "TIMESTAMP": ColumnType.TIMESTAMP,
            "TIMESTAMPTZ": ColumnType.TIMESTAMPTZ,
            "UUID": ColumnType.UUID,
            "JSON": ColumnType.JSON,
            "JSONB": ColumnType.JSONB,
            "BYTEA": ColumnType.BYTEA,
        }

        col_type = type_mapping.get(type_str, ColumnType.UNKNOWN)
        return col_type, length

    def _extract_default(self, col_def: str) -> str | None:
        """Extract DEFAULT value from column definition."""
        match = re.search(r"DEFAULT\s+([^\s,]+)", col_def, re.IGNORECASE)
        if match:
            default_val = match.group(1)
            # Handle function calls like NOW()
            if "(" in default_val:
                # Find the matching closing paren
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
