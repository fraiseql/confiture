"""Generate PostgreSQL COPY format from seed data.

This module provides CopyFormatter to convert seed data into PostgreSQL's
efficient COPY format for bulk loading.
"""

from typing import Any


class CopyFormatter:
    r"""Generate PostgreSQL COPY format from seed data.

    Converts seed data (list of dicts) into PostgreSQL COPY format for
    efficient bulk loading. Handles:
    - NULL value representation (\N)
    - Special character escaping (backslash, newline, tab, etc.)
    - Multiple data types (UUID, numeric, string, boolean)
    - Column ordering preservation
    - Tab-separated values

    Example:
        >>> formatter = CopyFormatter()
        >>> rows = [
        ...     {"id": "1", "name": "Alice"},
        ...     {"id": "2", "name": "Bob"},
        ... ]
        >>> columns = ["id", "name"]
        >>> copy_format = formatter.format_table("users", rows, columns)
        >>> print(copy_format)
        COPY users (id, name) FROM stdin;
        1\tAlice
        2\tBob
        \.
    """

    def __init__(self) -> None:
        """Initialize the formatter."""
        pass

    def format_table(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        """Format a table into PostgreSQL COPY format.

        Args:
            table_name: Name of the table
            rows: List of row dictionaries
            columns: Column names in order

        Returns:
            String in PostgreSQL COPY format
        """
        lines = []

        # Add COPY header
        column_list = ", ".join(columns)
        lines.append(f"COPY {table_name} ({column_list}) FROM stdin;")

        # Add data rows
        for row in rows:
            values = []
            for col in columns:
                value = row.get(col)
                formatted = self._format_value(value)
                values.append(formatted)
            lines.append("\t".join(values))

        # Add COPY terminator
        lines.append("\\.")

        return "\n".join(lines)

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a single value for COPY format.

        Args:
            value: The value to format

        Returns:
            String representation for COPY format
        """
        # NULL values
        if value is None:
            return "\\N"

        # Convert to string
        str_value = str(value)

        # Escape special characters
        # Backslash must be escaped first
        str_value = str_value.replace("\\", "\\\\")
        # Tab
        str_value = str_value.replace("\t", "\\t")
        # Newline
        str_value = str_value.replace("\n", "\\n")
        # Carriage return
        str_value = str_value.replace("\r", "\\r")
        # Backspace
        str_value = str_value.replace("\b", "\\b")
        # Form feed
        str_value = str_value.replace("\f", "\\f")

        return str_value
