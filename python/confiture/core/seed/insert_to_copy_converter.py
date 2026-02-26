"""Convert INSERT statements to PostgreSQL COPY format.

This module provides InsertToCopyConverter to parse INSERT statements
and convert them to COPY format for faster bulk loading.
"""

from sqlglot import parse as sqlglot_parse

from confiture.core.seed.copy_formatter import CopyFormatter
from confiture.core.seed.insert_validator import InsertValidator
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

    def __init__(self) -> None:
        """Initialize converter with validator."""
        self.validator = InsertValidator()

    def _can_convert_to_copy(self, insert_sql: str) -> bool:
        """Check if INSERT statement can be converted to COPY format.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            True if convertible, False otherwise

        Note:
            This is a backward-compatibility wrapper around validator.can_convert_to_copy().
        """
        can_convert, _ = self.validator.can_convert_to_copy(insert_sql)
        return can_convert

    def try_convert(
        self,
        insert_sql: str,
        file_path: str = "",
    ) -> ConversionResult:
        """Attempt to convert INSERT statements to COPY format with graceful fallback.

        Handles files containing multiple INSERT statements. Statements targeting
        the same table with identical column lists are merged into a single COPY
        block; statements with different tables or different column lists each get
        their own COPY block. Non-convertible statements (functions, ON CONFLICT,
        etc.) are passed through as-is after the COPY blocks.

        Args:
            insert_sql: One or more SQL INSERT statements
            file_path: Optional path to the file being converted (for reporting)

        Returns:
            ConversionResult with success status, converted format (if successful),
            rows converted (if successful), or failure reason (if unsuccessful)

        Example:
            >>> converter = InsertToCopyConverter()
            >>> result = converter.try_convert(
            ...     "INSERT INTO users (id) VALUES (1);\\n"
            ...     "INSERT INTO users (id) VALUES (2);",
            ...     file_path="users.sql"
            ... )
            >>> if result.success:
            ...     print(f"Converted {result.rows_converted} rows")
            ... else:
            ...     print(f"Cannot convert: {result.reason}")
        """
        try:
            statements = [s for s in sqlglot_parse(insert_sql, dialect="postgres") if s is not None]
        except Exception as e:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=f"Parse error: {str(e)}",
            )

        if not statements:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason="No SQL statements found",
            )

        # Groups: (table_name, columns_tuple) -> accumulated rows
        groups: dict[tuple[str, tuple[str, ...]], list[list[str | None]]] = {}
        group_order: list[tuple[str, tuple[str, ...]]] = []
        passthrough: list[str] = []
        total_rows = 0
        first_failure_reason: str | None = None

        for stmt in statements:
            stmt_sql = stmt.sql(dialect="postgres")

            can_convert, reason = self.validator.can_convert_to_copy(stmt_sql)
            if not can_convert:
                if first_failure_reason is None:
                    first_failure_reason = reason
                passthrough.append(stmt_sql)
                continue

            table_name = self.validator.extract_table_name(stmt_sql)
            columns = self.validator.extract_columns(stmt_sql)
            rows = self.validator.extract_rows(stmt_sql)

            if table_name is None or columns is None or rows is None:
                passthrough.append(stmt_sql)
                continue

            key: tuple[str, tuple[str, ...]] = (table_name, tuple(columns))
            if key not in groups:
                groups[key] = []
                group_order.append(key)
            groups[key].extend(rows)
            total_rows += len(rows)

        if not groups:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=first_failure_reason or "No convertible INSERT statements found",
            )

        # Build output: one COPY block per (table, columns) group, then passthrough SQL
        formatter = CopyFormatter()
        output_parts: list[str] = []

        for key in group_order:
            table_name, col_tuple = key
            columns = list(col_tuple)
            rows = [dict(zip(columns, values, strict=False)) for values in groups[key]]
            output_parts.append(formatter.format_table(table_name, rows, columns))

        output_parts.extend(passthrough)
        combined = "\n".join(output_parts)

        return ConversionResult(
            file_path=file_path,
            success=True,
            copy_format=combined,
            rows_converted=total_rows,
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

    def convert(self, insert_sql: str) -> str:
        """Convert INSERT statement to COPY format.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            PostgreSQL COPY format string

        Raises:
            ValueError: If INSERT statement cannot be parsed
        """
        # Extract components using validator
        table_name = self.validator.extract_table_name(insert_sql)
        columns = self.validator.extract_columns(insert_sql)
        rows_data = self.validator.extract_rows(insert_sql)

        if not table_name:
            raise ValueError("Could not extract table name from INSERT statement")
        if not columns:
            raise ValueError("Could not extract columns from INSERT statement")
        if rows_data is None:
            raise ValueError("Could not extract values from INSERT statement")

        # Convert rows to dict format expected by formatter
        rows = [dict(zip(columns, values, strict=False)) for values in rows_data]

        # Convert to COPY format
        formatter = CopyFormatter()
        copy_output = formatter.format_table(table_name, rows, columns)

        return copy_output
