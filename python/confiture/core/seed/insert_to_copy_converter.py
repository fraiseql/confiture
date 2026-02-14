"""Convert INSERT statements to PostgreSQL COPY format.

This module provides InsertToCopyConverter to parse INSERT statements
and convert them to COPY format for faster bulk loading.
"""

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
        # Check if conversion is possible using validator
        can_convert, reason = self.validator.can_convert_to_copy(insert_sql)
        if not can_convert:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=reason or "Cannot convert to COPY format",
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
