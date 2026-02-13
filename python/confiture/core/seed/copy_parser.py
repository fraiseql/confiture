"""Parse PostgreSQL COPY format back into seed data structures.

This module provides CopyParser to convert COPY format strings back into
dictionaries for use in seed data validation and manipulation.
"""

from typing import Any


class CopyParser:
    r"""Parse PostgreSQL COPY format back into seed data.

    Converts COPY format strings (tab-separated values with escape sequences)
    back into dictionaries. Handles:
    - NULL value representation (\N -> None)
    - Special character unescaping (\\, \n, \t, etc.)
    - Column mapping
    - Multiple data types
    - Empty tables

    Example:
        >>> parser = CopyParser()
        >>> copy_data = "1\tAlice\n2\tBob\n\\."
        >>> columns = ["id", "name"]
        >>> rows = parser.parse_table(copy_data, columns)
        >>> rows[0]
        {"id": "1", "name": "Alice"}
    """

    def __init__(self) -> None:
        """Initialize the parser."""
        pass

    def parse_table(self, copy_data: str, columns: list[str]) -> list[dict[str, Any]]:
        """Parse COPY format data back into rows.

        Args:
            copy_data: String in PostgreSQL COPY format (tab-separated)
            columns: Column names in order

        Returns:
            List of dictionaries representing rows
        """
        rows = []

        # Split by newlines to get individual rows
        lines = copy_data.strip().split("\n")

        for line in lines:
            # Skip empty lines and the terminator
            if not line or line == "\\.":
                continue

            # Split by tabs
            values = line.split("\t")

            # Ensure we have the right number of columns
            if len(values) != len(columns):
                continue

            # Unescape and convert values
            row_dict = {}
            for col, value in zip(columns, values, strict=False):
                unescaped = self._unescape_value(value)
                row_dict[col] = unescaped

            rows.append(row_dict)

        return rows

    @staticmethod
    def _unescape_value(value: str) -> Any:
        """Unescape a single value from COPY format.

        Args:
            value: Escaped value string

        Returns:
            Unescaped value (None for \\N, otherwise string)
        """
        # NULL values
        if value == "\\N":
            return None

        # Unescape special characters
        # Must unescape backslash first, then others
        unescaped = value.replace("\\\\", "\x00")  # Temporary placeholder
        unescaped = unescaped.replace("\\n", "\n")
        unescaped = unescaped.replace("\\t", "\t")
        unescaped = unescaped.replace("\\r", "\r")
        unescaped = unescaped.replace("\\b", "\b")
        unescaped = unescaped.replace("\\f", "\f")
        unescaped = unescaped.replace("\x00", "\\")  # Restore backslash

        return unescaped
