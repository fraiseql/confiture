"""Convert INSERT statements to PostgreSQL COPY format.

This module provides InsertToCopyConverter to parse INSERT statements
and convert them to COPY format for faster bulk loading.
"""

import re
from typing import Any

from confiture.core.seed.copy_formatter import CopyFormatter
from confiture.models.results import ConversionReport, ConversionResult


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

    def try_convert(
        self,
        insert_sql: str,
        file_path: str = "",
    ) -> ConversionResult:
        """Attempt to convert INSERT statement to COPY format with graceful fallback.

        Tries to convert the INSERT statement to COPY format. If conversion is not
        possible, returns a ConversionResult with success=False and a descriptive
        reason rather than raising an exception.

        Args:
            insert_sql: SQL INSERT statement
            file_path: Optional path to the file being converted (for reporting)

        Returns:
            ConversionResult with success status, converted format (if successful),
            rows converted (if successful), or failure reason (if unsuccessful)

        Example:
            >>> converter = InsertToCopyConverter()
            >>> result = converter.try_convert(
            ...     "INSERT INTO users (id) VALUES (1);",
            ...     file_path="users.sql"
            ... )
            >>> if result.success:
            ...     print(f"Converted {result.rows_converted} rows")
            ... else:
            ...     print(f"Cannot convert: {result.reason}")
        """
        # Check if conversion is possible before attempting
        if not self._can_convert_to_copy(insert_sql):
            reason = self._get_conversion_failure_reason(insert_sql)
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=reason,
            )

        # Try to convert
        try:
            copy_format = self.convert(insert_sql)

            # Count rows in COPY format
            # COPY format: header + data lines + \.
            lines = copy_format.strip().split("\n")
            # Subtract 1 for header (COPY ...) and 1 for footer (\.)
            rows_converted = max(0, len(lines) - 2)

            return ConversionResult(
                file_path=file_path,
                success=True,
                copy_format=copy_format,
                rows_converted=rows_converted,
            )
        except Exception as e:
            # Graceful fallback for unexpected errors
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=f"Parse error: {str(e)}",
            )

    def convert_batch(
        self,
        files: dict[str, str],
    ) -> ConversionReport:
        """Convert multiple INSERT files to COPY format in batch.

        Processes a collection of seed files, attempting to convert each one
        from INSERT format to COPY format. Returns a comprehensive report
        with success/failure metrics.

        Args:
            files: Dictionary mapping file paths to SQL content

        Returns:
            ConversionReport with aggregate statistics and per-file results

        Example:
            >>> converter = InsertToCopyConverter()
            >>> files = {
            ...     "users.sql": "INSERT INTO users (id) VALUES (1);",
            ...     "posts.sql": "INSERT INTO posts (ts) VALUES (NOW());",
            ... }
            >>> report = converter.convert_batch(files)
            >>> print(f"Converted {report.successful}/{report.total_files} files")
            Converted 1/2 files
        """
        results: list[ConversionResult] = []

        for file_path, sql_content in files.items():
            result = self.try_convert(sql_content, file_path=file_path)
            results.append(result)

        # Calculate statistics
        successful = sum(1 for r in results if r.success)
        failed = len(files) - successful

        return ConversionReport(
            total_files=len(files),
            successful=successful,
            failed=failed,
            results=results,
        )

    def _get_conversion_failure_reason(self, insert_sql: str) -> str:
        """Determine why an INSERT statement cannot be converted to COPY format.

        Analyzes the SQL and provides a human-readable reason for conversion failure.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            Descriptive reason why conversion failed
        """
        normalized = insert_sql.strip().upper()

        # Check for specific unsupported patterns
        if "ON CONFLICT" in normalized:
            return "ON CONFLICT clause is not compatible with COPY format"
        if "ON DUPLICATE" in normalized:
            return "ON DUPLICATE KEY clause is not compatible with COPY format"
        if "WITH " in normalized or "INSERT OR" in normalized:
            return "CTE or INSERT OR clause is not compatible with COPY format"
        if "RETURNING" in normalized:
            return "RETURNING clause is not compatible with COPY format"

        # Check VALUES clause for problematic patterns
        values_match = re.search(
            r"VALUES\s*(.+?)(?:;|\s*$)",
            insert_sql,
            re.IGNORECASE | re.DOTALL,
        )
        if values_match:
            values_clause = values_match.group(1)

            if re.search(r"\bSELECT\b", values_clause, re.IGNORECASE):
                return "SELECT query in VALUES clause is not compatible with COPY format"

            if re.search(r"\bCASE\s+WHEN\b", values_clause, re.IGNORECASE):
                return "CASE WHEN expression in VALUES is not compatible with COPY format"

            if re.search(
                r"\b(CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME|CURRENT_USER)\b",
                values_clause,
                re.IGNORECASE,
            ):
                return (
                    "SQL function (CURRENT_TIMESTAMP, CURRENT_DATE, etc.) in VALUES "
                    "is not compatible with COPY format"
                )

            # Check for function calls
            in_string = False
            i = 0
            while i < len(values_clause):
                char = values_clause[i]
                if char in ("'", '"') and (i == 0 or values_clause[i - 1] != "\\"):
                    in_string = not in_string

                if (
                    not in_string
                    and i < len(values_clause) - 1
                    and re.match(r"\w", char)
                ):
                    j = i
                    while j < len(values_clause) and (
                        values_clause[j].isalnum() or values_clause[j] == "_"
                    ):
                        j += 1
                    while j < len(values_clause) and values_clause[j].isspace():
                        j += 1
                    if j < len(values_clause) and values_clause[j] == "(":
                        func_name = values_clause[i:j].strip()
                        if not self._is_convertible_expression(func_name):
                            return (
                                f"Function call in VALUES: {func_name}() "
                                "is not compatible with COPY format"
                            )

                i += 1

            if "||" in values_clause:
                in_string = False
                for i, char in enumerate(values_clause):
                    if char in ("'", '"'):
                        if i == 0 or values_clause[i - 1] != "\\":
                            in_string = not in_string
                    elif (
                        not in_string
                        and i < len(values_clause) - 1
                        and values_clause[i : i + 2] == "||"
                    ):
                        return "String concatenation (||) in VALUES is not compatible with COPY format"

        return "This INSERT statement cannot be converted to COPY format"

    def _can_convert_to_copy(self, insert_sql: str) -> bool:
        """Check if INSERT statement can be safely converted to COPY format.

        Detects patterns that cannot be converted:
        - Function calls (NOW(), uuid_generate_v4(), UPPER(), etc.)
        - CURRENT_TIMESTAMP and similar special functions
        - ON CONFLICT, ON DUPLICATE KEY clauses
        - SELECT queries in VALUES
        - CTEs (WITH clauses)
        - CAST expressions
        - CASE WHEN expressions
        - String concatenation (||) in VALUES
        - Arithmetic operations in VALUES

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            True if statement can be converted, False otherwise
        """
        # Normalize for analysis
        normalized = insert_sql.strip().upper()

        # Check for clauses that make conversion impossible
        if any(
            pattern in normalized
            for pattern in [
                "ON CONFLICT",
                "ON DUPLICATE",
                "WITH ",
                "INSERT OR",
                "RETURNING",
            ]
        ):
            return False

        # Extract VALUES clause
        try:
            values_match = re.search(
                r"VALUES\s*(.+?)(?:;|\s*$)",
                insert_sql,
                re.IGNORECASE | re.DOTALL,
            )
            if not values_match:
                return False

            values_clause = values_match.group(1)

            # Check for SELECT in VALUES
            if re.search(r"\bSELECT\b", values_clause, re.IGNORECASE):
                return False

            # Check for CASE WHEN (case-insensitive)
            if re.search(r"\bCASE\s+WHEN\b", values_clause, re.IGNORECASE):
                return False

            # Check for CURRENT_TIMESTAMP and similar special expressions
            if re.search(
                r"\b(CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME|CURRENT_USER)\b",
                values_clause,
                re.IGNORECASE,
            ):
                return False

            # Skip quoted strings when looking for functions
            in_string = False
            quote_char = None
            i = 0
            while i < len(values_clause):
                char = values_clause[i]

                # Track string boundaries
                if char in ("'", '"') and (i == 0 or values_clause[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        quote_char = char
                    elif char == quote_char:
                        in_string = False
                        quote_char = None

                # Check for function call outside of strings
                if (
                    not in_string
                    and i < len(values_clause) - 1
                    and re.match(r"\w", char)
                    and values_clause[i : i + 20].find("(") >= 0
                ):
                    # Peek ahead to see if this looks like a function call
                    j = i
                    while j < len(values_clause) and (
                        values_clause[j].isalnum() or values_clause[j] == "_"
                    ):
                        j += 1
                    # Skip whitespace
                    while j < len(values_clause) and values_clause[j].isspace():
                        j += 1
                    # If we hit '(', it's a function call
                    if j < len(values_clause) and values_clause[j] == "(":
                        func_name = values_clause[i:j].strip()
                        # Check for known convertible patterns
                        if not self._is_convertible_expression(func_name):
                            return False

                i += 1

            # Check for string concatenation operator
            if "||" in values_clause:
                # Make sure it's not in a string
                in_string = False
                for i, char in enumerate(values_clause):
                    if char in ("'", '"'):
                        if i == 0 or values_clause[i - 1] != "\\":
                            in_string = not in_string
                    elif (
                        not in_string
                        and i < len(values_clause) - 1
                        and values_clause[i : i + 2] == "||"
                    ):
                        return False

            # Check for arithmetic operators outside strings
            arithmetic_ops = [" + ", " - ", " * ", " / ", " % "]
            in_string = False
            quote_char = None
            values_str_normalized = ""

            for i, char in enumerate(values_clause):
                if char in ("'", '"') and (i == 0 or values_clause[i - 1] != "\\"):
                    in_string = not in_string
                    quote_char = char if in_string else None

                if in_string:
                    values_str_normalized += " "
                else:
                    values_str_normalized += char

            # Check for arithmetic operations (but allow negative numbers)
            for op in arithmetic_ops:
                if (
                    op in values_str_normalized
                    and (op != " - " or not re.search(r"\(\s*-\s*\d", values_clause))
                    and re.search(r"\d\s*[\+\*/%]\s*\d", values_str_normalized)
                ):
                    return False

            return True

        except Exception:
            # If we can't parse it, assume it can't be converted
            return False

    def _is_convertible_expression(self, expr_name: str) -> bool:
        """Check if an expression/function is convertible.

        Some expressions like ::type casts are convertible because
        they represent literal type conversions.

        Args:
            expr_name: Name of expression/function

        Returns:
            True if expression is convertible, False otherwise
        """
        expr_upper = expr_name.upper()
        # Expressions/functions that we CANNOT convert
        non_convertible = {
            "NOW",
            "CURRENT_TIMESTAMP",
            "CURRENT_DATE",
            "CURRENT_TIME",
            "CURRENT_USER",
            "UUID_GENERATE_V4",
            "UUID_GENERATE_V1",
            "GEN_RANDOM_UUID",
            "RANDOM",
            "UPPER",
            "LOWER",
            "SUBSTRING",
            "LENGTH",
            "COALESCE",
            "NULLIF",
            "CASE",
            "CAST",
            "EXTRACT",
            "DATE_PART",
            "TO_CHAR",
            "TO_DATE",
            "TO_TIMESTAMP",
            "TO_NUMBER",
            "ROUND",
            "CEIL",
            "FLOOR",
            "ABS",
            "REPLACE",
            "TRIM",
            "LTRIM",
            "RTRIM",
            "CONCAT",
            "ARRAY",
            "ROW",
            "DISTINCT",
        }

        return expr_upper not in non_convertible

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
        table_match = re.search(r"INSERT\s+INTO\s+([\w.]+)\s*\(", sql, re.IGNORECASE)
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
