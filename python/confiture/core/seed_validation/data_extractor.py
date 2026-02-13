"""Extract structured data from seed SQL files.

This module provides SQL parsing utilities for extracting:
- Table names from INSERT statements
- Column names and their order
- Row data (values) from various SQL patterns
- Foreign key references
- Support for complex queries (UNION, CTE, SELECT statements)
"""

import re
from typing import Any

# SQL parsing patterns
_INSERT_PATTERN = re.compile(r"INSERT\s+INTO\s+(\w+(?:\.\w+)?)", re.IGNORECASE)
_COLUMNS_PATTERN = re.compile(
    r"INSERT\s+INTO\s+\w+(?:\.\w+)?\s*\((.*?)\)", re.IGNORECASE | re.DOTALL
)
_VALUES_PATTERN = re.compile(r"VALUES\s*(.+?)(?:;|$)", re.IGNORECASE | re.DOTALL)
_SELECT_PATTERN = re.compile(
    r"SELECT\s+(.*?)\s+(?:FROM|WHERE|GROUP|ORDER|;|$)", re.IGNORECASE | re.DOTALL
)
_CTE_PATTERN = re.compile(r"WITH\s+(?:RECURSIVE\s+)?.*?\s+(?=SELECT)", re.IGNORECASE | re.DOTALL)
_ALIAS_PATTERN = re.compile(r"\s+AS\s+\w+$", re.IGNORECASE)


class DataExtractor:
    """Extract tables, columns, and row values from SQL INSERT statements.

    Handles simple INSERT VALUES statements as well as complex queries:
    - Multi-row INSERT VALUES
    - UNION/UNION ALL queries
    - CTE (WITH clause) queries
    - SELECT statements with type casts

    Example:
        >>> extractor = DataExtractor()
        >>> sql = "INSERT INTO users (id, name) VALUES ('1', 'Alice')"
        >>> extractor.extract_tables(sql)
        ['users']
        >>> extractor.extract_columns(sql, 'users')
        ['id', 'name']
        >>> rows = extractor.extract_rows(sql, 'users')
        >>> rows[0]['name']
        "'Alice'"
    """

    def __init__(self) -> None:
        """Initialize the data extractor."""
        pass

    def extract_tables(self, sql: str) -> list[str]:
        """Extract table names from INSERT statements.

        Args:
            sql: SQL statement to parse

        Returns:
            List of table names found in INSERT INTO clauses
        """
        if not sql or not sql.strip():
            return []

        # Only process INSERT statements
        if "INSERT" not in sql.upper():
            return []

        matches = _INSERT_PATTERN.findall(sql)
        # Return just the table name without schema prefix if present
        return [match.split(".")[-1] if "." in match else match for match in matches]

    def extract_columns(self, sql: str, table: str) -> list[str]:  # noqa: ARG002
        """Extract column names from INSERT statement.

        Preserves column order as they appear in the INSERT statement.

        Args:
            sql: SQL statement to parse
            table: Table name (for validation)

        Returns:
            List of column names in order, or empty list if not an INSERT
        """
        if not sql or not sql.strip():
            return []

        # Only process INSERT statements
        if "INSERT" not in sql.upper():
            return []

        match = _COLUMNS_PATTERN.search(sql)
        if not match:
            return []

        # Extract and clean column names
        columns_str = match.group(1)
        columns = [col.strip() for col in columns_str.split(",")]
        return columns

    def extract_rows(self, sql: str, table: str) -> list[dict[str, Any]]:  # noqa: ARG002
        """Extract row data from INSERT statement.

        Handles:
        - VALUES clauses with single or multiple rows
        - UNION/UNION ALL queries
        - CTE (WITH) queries
        - SELECT statements

        Args:
            sql: SQL statement to parse
            table: Table name (for validation)

        Returns:
            List of dicts, each representing a row with column -> value mapping
        """
        if not sql or not sql.strip():
            return []

        # Only process INSERT statements
        if "INSERT" not in sql.upper():
            return []

        # Get column names first
        columns = self.extract_columns(sql, table)
        if not columns:
            return []

        rows = []

        # Try to extract VALUES clause first
        rows.extend(self._extract_from_values(sql, columns))

        # If no VALUES found, try SELECT/UNION patterns
        if not rows:
            rows.extend(self._extract_from_select(sql, columns))

        return rows

    def _extract_from_values(self, sql: str, columns: list[str]) -> list[dict[str, Any]]:
        """Extract rows from VALUES clause.

        Handles:
        - Single-row VALUES (...)
        - Multi-row VALUES (...), (...), (...)
        - Complex expressions and type casts

        Args:
            sql: SQL statement
            columns: Column names

        Returns:
            List of row dictionaries
        """
        rows = []

        # Find VALUES keyword
        values_match = _VALUES_PATTERN.search(sql)
        if not values_match:
            return []

        values_section = values_match.group(1)

        # Extract individual row tuples: (...), (...), (...)
        # Handle nested parentheses in function calls, casts, etc.
        paren_depth = 0
        in_quote = False
        quote_char = None
        row_content = []

        for char in values_section:
            if char in ("'", '"') and (not row_content or row_content[-1] != "\\"):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif char == quote_char:
                    in_quote = False

            if not in_quote:
                if char == "(":
                    paren_depth += 1
                    if paren_depth == 1:
                        continue  # Skip the opening paren of row tuple
                elif char == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        # End of this row
                        if row_content:
                            values = self._split_values("".join(row_content))
                            if len(values) == len(columns):
                                row_dict = dict(zip(columns, values, strict=False))
                                rows.append(row_dict)
                        row_content = []
                        continue

            if paren_depth > 0:
                row_content.append(char)

        return rows

    def _extract_from_select(self, sql: str, columns: list[str]) -> list[dict[str, Any]]:
        """Extract rows from SELECT/UNION queries.

        Handles:
        - Simple SELECT ... values
        - UNION/UNION ALL queries
        - CTE (WITH) clauses
        - SELECT with FROM, WHERE, GROUP BY, ORDER BY

        Args:
            sql: SQL statement
            columns: Column names

        Returns:
            List of row dictionaries (simplified extraction)
        """
        rows = []

        # Remove CTE (WITH clause) if present to focus on the main SELECT
        sql_without_cte = _CTE_PATTERN.sub("", sql)

        # Split by UNION/UNION ALL to get individual SELECT statements
        union_parts = re.split(r"\s+UNION\s+(?:ALL)?\s+", sql_without_cte, flags=re.IGNORECASE)

        for select_stmt in union_parts:
            select_stmt = select_stmt.strip()

            # Extract SELECT list (values between SELECT and FROM/;)
            match = _SELECT_PATTERN.search(select_stmt)

            if not match:
                # Try simpler pattern for literal values
                match = re.search(r"SELECT\s+(.*?)(?:;|$)", select_stmt, re.IGNORECASE | re.DOTALL)

            if match:
                select_list = match.group(1).strip()

                # Split by comma, but preserve quoted strings and function calls
                values = self._split_values(select_list)

                # Remove aliases (AS colname)
                cleaned_values = []
                for val in values:
                    # Remove "AS colname" if present
                    val = _ALIAS_PATTERN.sub("", val)
                    cleaned_values.append(val.strip())

                if len(cleaned_values) == len(columns):
                    row_dict = dict(zip(columns, cleaned_values, strict=False))
                    rows.append(row_dict)

        return rows

    @staticmethod
    def _split_values(value_str: str) -> list[str]:
        """Split comma-separated values, handling quoted strings and functions.

        Args:
            value_str: String containing comma-separated values

        Returns:
            List of individual values
        """
        values = []
        current = []
        in_string = False
        in_parens = 0
        string_char = None

        for char in value_str:
            if char in ("'", '"') and (not current or current[-1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None

            if char == "(" and not in_string:
                in_parens += 1
            elif char == ")" and not in_string:
                in_parens -= 1

            if char == "," and not in_string and in_parens == 0:
                values.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            values.append("".join(current).strip())

        # Convert NULL values appropriately
        result = []
        for val in values:
            val = val.strip()
            if val.upper() == "NULL" or val.upper().startswith("NULL::"):
                result.append(None)
            else:
                result.append(val if val else None)

        return result
