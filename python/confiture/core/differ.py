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

from confiture.models.schema import Column, ColumnType, SchemaChange, SchemaDiff, Table


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
        old_tables = self.parse_sql(old_sql)
        new_tables = self.parse_sql(new_sql)

        changes: list[SchemaChange] = []

        # Build name-to-table maps for efficient lookup
        old_table_map = {t.name: t for t in old_tables}
        new_table_map = {t.name: t for t in new_tables}

        # Detect table-level changes
        old_table_names = set(old_table_map.keys())
        new_table_names = set(new_table_map.keys())

        # Check for renamed tables (fuzzy match before drop/add)
        renamed_tables = self._detect_table_renames(
            old_table_names - new_table_names, new_table_names - old_table_names
        )

        # Process renamed tables
        for old_name, new_name in renamed_tables.items():
            changes.append(
                SchemaChange(type="RENAME_TABLE", old_value=old_name, new_value=new_name)
            )
            # Mark as processed
            old_table_names.discard(old_name)
            new_table_names.discard(new_name)

        # Dropped tables (in old but not in new, and not renamed)
        for table_name in old_table_names - new_table_names:
            changes.append(SchemaChange(type="DROP_TABLE", table=table_name))

        # New tables (in new but not in old, and not renamed)
        for table_name in new_table_names - old_table_names:
            changes.append(SchemaChange(type="ADD_TABLE", table=table_name))

        # Compare columns in tables that exist in both schemas
        for table_name in old_table_names & new_table_names:
            old_table = old_table_map[table_name]
            new_table = new_table_map[table_name]
            table_changes = self._compare_table_columns(old_table, new_table)
            changes.extend(table_changes)

        return SchemaDiff(changes=changes)

    def _detect_table_renames(
        self, old_names: set[str], new_names: set[str]
    ) -> dict[str, str]:
        """Detect renamed tables using fuzzy matching.

        Args:
            old_names: Set of table names that exist in old schema only
            new_names: Set of table names that exist in new schema only

        Returns:
            Dictionary mapping old_name -> new_name for detected renames
        """
        renames: dict[str, str] = {}

        for old_name in old_names:
            # Look for similar names in new_names
            best_match = self._find_best_match(old_name, new_names)
            if best_match and self._similarity_score(old_name, best_match) > 0.5:
                renames[old_name] = best_match

        return renames

    def _compare_table_columns(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Compare columns between two versions of the same table.

        Args:
            old_table: Old version of table
            new_table: New version of table

        Returns:
            List of SchemaChange objects for column-level changes
        """
        changes: list[SchemaChange] = []

        old_col_map = {c.name: c for c in old_table.columns}
        new_col_map = {c.name: c for c in new_table.columns}

        old_col_names = set(old_col_map.keys())
        new_col_names = set(new_col_map.keys())

        # Detect renamed columns
        renamed_columns = self._detect_column_renames(
            old_col_names - new_col_names, new_col_names - old_col_names
        )

        # Process renamed columns
        for old_name, new_name in renamed_columns.items():
            changes.append(
                SchemaChange(
                    type="RENAME_COLUMN",
                    table=old_table.name,
                    old_value=old_name,
                    new_value=new_name,
                )
            )
            # Mark as processed
            old_col_names.discard(old_name)
            new_col_names.discard(new_name)

        # Dropped columns
        for col_name in old_col_names - new_col_names:
            changes.append(
                SchemaChange(type="DROP_COLUMN", table=old_table.name, column=col_name)
            )

        # New columns
        for col_name in new_col_names - old_col_names:
            changes.append(
                SchemaChange(type="ADD_COLUMN", table=old_table.name, column=col_name)
            )

        # Compare columns that exist in both
        for col_name in old_col_names & new_col_names:
            old_col = old_col_map[col_name]
            new_col = new_col_map[col_name]
            col_changes = self._compare_column_properties(old_table.name, old_col, new_col)
            changes.extend(col_changes)

        return changes

    def _detect_column_renames(
        self, old_names: set[str], new_names: set[str]
    ) -> dict[str, str]:
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

        # Type change
        if old_col.type != new_col.type:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_TYPE",
                    table=table_name,
                    column=old_col.name,
                    old_value=old_col.type.value,
                    new_value=new_col.type.value,
                )
            )

        # Nullable change
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

        # Default change
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

        # Exact match
        if name1 == name2:
            return 1.0

        # Split on underscores to get word parts
        name1_parts = name1.split("_")
        name2_parts = name2.split("_")

        # Check for common suffix/prefix patterns
        # e.g., "full_name" and "display_name" share "_name" suffix
        if len(name1_parts) > 1 or len(name2_parts) > 1:
            # Check suffix
            if name1_parts[-1] == name2_parts[-1]:
                # Same suffix, different prefix -> likely rename
                return 0.6

            # Check prefix
            if name1_parts[0] == name2_parts[0]:
                # Same prefix, different suffix -> likely rename
                return 0.6

        # Word-level similarity
        name1_words = set(name1_parts)
        name2_words = set(name2_parts)
        common_words = name1_words & name2_words

        if common_words:
            # Jaccard similarity for words
            return len(common_words) / len(name1_words | name2_words)

        # Character-level Jaccard similarity
        name1_chars = set(name1)
        name2_chars = set(name2)
        common_chars = name1_chars & name2_chars

        if common_chars:
            return len(common_chars) / len(name1_chars | name2_chars)

        return 0.0

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
