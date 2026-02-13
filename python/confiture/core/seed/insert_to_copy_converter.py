"""Convert INSERT statements to PostgreSQL COPY format.

This module provides InsertToCopyConverter to parse INSERT statements
and convert them to COPY format for faster bulk loading.
"""

import re
from typing import Any

from confiture.core.seed.copy_formatter import CopyFormatter


class InsertToCopyConverter:
    r"""Convert INSERT statements to COPY format.

    Parses SQL INSERT statements and converts them to PostgreSQL COPY format
    for efficient bulk loading. Handles:
    - Single and multi-row INSERT statements
    - Various data types (strings, numbers, NULL, booleans)
    - Quoted strings with escaped characters
    - Whitespace normalization

    Example:
        >>> converter = InsertToCopyConverter()
        >>> insert_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
        >>> copy_format = converter.convert(insert_sql)
        >>> print(copy_format)
        COPY users (id, name) FROM stdin;
        1   Alice
        2   Bob
        \.
    """

    def convert(self, insert_sql: str) -> str:
        """Convert INSERT statement to COPY format.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            PostgreSQL COPY format string

        Raises:
            ValueError: If INSERT statement cannot be parsed
        """
        # Normalize whitespace
        normalized = self._normalize_sql(insert_sql)

        # Extract components
        table_name = self._extract_table_name(normalized)
        columns = self._extract_columns(normalized)
        values_str = self._extract_values_clause(normalized)

        # Parse rows
        rows = self._parse_rows(values_str, columns)

        # Convert to COPY format
        formatter = CopyFormatter()
        copy_output = formatter.format_table(table_name, rows, columns)

        return copy_output

    def _extract_table_name(self, sql: str) -> str:
        """Extract table name from INSERT statement.

        Args:
            sql: Normalized INSERT statement

        Returns:
            Table name

        Raises:
            ValueError: If table name cannot be extracted
        """
        table_match = re.search(r"INSERT\s+INTO\s+(\w+)\s*\(", sql, re.IGNORECASE)
        if not table_match:
            raise ValueError("Could not extract table name from INSERT statement")
        return table_match.group(1)

    def _extract_columns(self, sql: str) -> list[str]:
        """Extract column names from INSERT statement.

        Args:
            sql: Normalized INSERT statement

        Returns:
            List of column names

        Raises:
            ValueError: If columns cannot be extracted
        """
        columns_match = re.search(r"\(([\w\s,]+)\)\s*VALUES", sql, re.IGNORECASE)
        if not columns_match:
            raise ValueError("Could not extract columns from INSERT statement")
        return [col.strip() for col in columns_match.group(1).split(",")]

    def _extract_values_clause(self, sql: str) -> str:
        """Extract VALUES clause from INSERT statement.

        Args:
            sql: Normalized INSERT statement

        Returns:
            Values clause content

        Raises:
            ValueError: If values cannot be extracted
        """
        values_match = re.search(r"VALUES\s*(.+?)(?:;|\s*$)", sql, re.IGNORECASE | re.DOTALL)
        if not values_match:
            raise ValueError("Could not extract values from INSERT statement")
        return values_match.group(1)

    def _normalize_sql(self, sql: str) -> str:
        """Normalize SQL whitespace.

        Args:
            sql: SQL statement

        Returns:
            Normalized SQL
        """
        # Remove leading/trailing whitespace
        sql = sql.strip()

        # Replace multiple spaces with single space (but preserve string content)
        # This is a simple approach - just normalize outside of quotes
        result = []
        in_string = False
        quote_char = None

        for char in sql:
            if char in ("'", '"') and (not in_string or quote_char == char):
                in_string = not in_string
                quote_char = char if in_string else None
                result.append(char)
            elif char.isspace() and not in_string:
                # Skip multiple spaces outside strings
                if not result or result[-1] != " ":
                    result.append(" ")
            else:
                result.append(char)

        return "".join(result)

    def _parse_rows(self, values_str: str, columns: list[str]) -> list[dict[str, Any]]:
        """Parse VALUES clause into rows.

        Args:
            values_str: String containing VALUES (...)(...)
            columns: List of column names

        Returns:
            List of row dictionaries
        """
        rows = []

        # Split by rows (each row is a parenthesized group)
        # This regex finds all parenthesized value groups
        row_pattern = r"\(([^)]+)\)"
        row_matches = re.finditer(row_pattern, values_str)

        for match in row_matches:
            values_str_row = match.group(1)
            values = self._parse_values(values_str_row)

            if len(values) == len(columns):
                row = dict(zip(columns, values, strict=False))
                rows.append(row)

        return rows

    def _parse_values(self, values_str: str) -> list[Any]:
        """Parse comma-separated values.

        Args:
            values_str: String of comma-separated values

        Returns:
            List of parsed values
        """
        values = []
        i = 0

        while i < len(values_str):
            # Skip whitespace
            while i < len(values_str) and values_str[i] in (" ", "\t"):
                i += 1

            if i >= len(values_str):
                break

            # Check for quoted string
            if values_str[i] in ("'", '"'):
                quote_char = values_str[i]
                i += 1
                string_content = ""

                while i < len(values_str):
                    char = values_str[i]

                    if char == quote_char:
                        # Check if it's doubled (SQL escape)
                        if i + 1 < len(values_str) and values_str[i + 1] == quote_char:
                            string_content += quote_char
                            i += 2
                        else:
                            # End of string
                            i += 1
                            break
                    elif char == "\\":
                        # Handle backslash escapes
                        if i + 1 < len(values_str):
                            next_char = values_str[i + 1]
                            string_content += next_char
                            i += 2
                        else:
                            i += 1
                    else:
                        string_content += char
                        i += 1

                values.append(string_content)

                # Skip to comma or end
                while i < len(values_str) and values_str[i] in (" ", "\t"):
                    i += 1
                if i < len(values_str) and values_str[i] == ",":
                    i += 1
            else:
                # Unquoted value
                value = ""
                while i < len(values_str) and values_str[i] != ",":
                    value += values_str[i]
                    i += 1

                values.append(self._parse_single_value(value.strip()))

                if i < len(values_str) and values_str[i] == ",":
                    i += 1

        return values

    def _parse_single_value(self, value_str: str) -> Any:
        """Parse a single value.

        Args:
            value_str: String representation of value

        Returns:
            Parsed value (string, number, None, or boolean)
        """
        value_str = value_str.strip()

        # Check for NULL
        if value_str.upper() == "NULL":
            return None

        # Check for boolean
        if value_str.lower() == "true":
            return "true"
        if value_str.lower() == "false":
            return "false"

        # Check for quoted string
        if (value_str.startswith("'") and value_str.endswith("'")) or (
            value_str.startswith('"') and value_str.endswith('"')
        ):
            # Remove quotes
            string_content = value_str[1:-1]
            # Unescape doubled quotes (SQL convention)
            string_content = string_content.replace("''", "'").replace('""', '"')
            return string_content

        # Try to parse as number
        try:
            if "." in value_str:
                return str(float(value_str))
            else:
                return str(int(value_str))
        except ValueError:
            # Return as string
            return value_str
