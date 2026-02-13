"""UUID format validation for seed data.

This module provides RFC 4122 UUID format validation for detecting
malformed UUIDs in seed files before database execution.
"""

import re
from typing import Any

# RFC 4122 UUID regex pattern
# Format: 8-4-4-4-12 hex digit groups separated by dashes
_UUID_PATTERN_STR = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

# Pattern to find UUID literals in SQL statements (single-quoted strings)
_UUID_LITERAL_PATTERN_STR = (
    r"'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'"
)


class UUIDValidator:
    """Validator for RFC 4122 UUID format.

    Provides methods to validate UUID format and extract UUID literals
    from SQL statements.
    """

    # Compiled regex patterns for performance
    _uuid_pattern = re.compile(_UUID_PATTERN_STR)
    _uuid_literal_pattern = re.compile(_UUID_LITERAL_PATTERN_STR)

    def is_valid_uuid(self, uuid_str: Any) -> bool:
        """Check if a string is a valid RFC 4122 UUID.

        Args:
            uuid_str: String to validate. Can be any type.

        Returns:
            True if valid RFC 4122 format, False otherwise.

        Examples:
            >>> validator = UUIDValidator()
            >>> validator.is_valid_uuid('01442fe1-00c7-0000-0000-000000000001')
            True
            >>> validator.is_valid_uuid('invalid-uuid')
            False
            >>> validator.is_valid_uuid(None)
            False
        """
        if uuid_str is None:
            return False
        if not isinstance(uuid_str, str):
            return False

        return bool(self._uuid_pattern.match(uuid_str))

    def extract_uuid_literals(self, sql: str) -> list[str]:
        """Extract UUID literals from SQL statements.

        Finds all UUID values appearing in single-quoted strings within SQL.
        Case-insensitive matching: both 'ABC-...' and 'abc-...' are found.

        Args:
            sql: SQL statement to scan for UUID literals.

        Returns:
            List of UUID strings found in the SQL, in order of appearance.

        Examples:
            >>> validator = UUIDValidator()
            >>> sql = "INSERT INTO users (id) VALUES ('01442fe1-00c7-0000-0000-000000000001');"
            >>> validator.extract_uuid_literals(sql)
            ['01442fe1-00c7-0000-0000-000000000001']
            >>> sql = "INSERT INTO users (id) VALUES (NULL, '22222222-2222-2222-2222-222222222222');"
            >>> validator.extract_uuid_literals(sql)
            ['22222222-2222-2222-2222-222222222222']
        """
        if not sql:
            return []

        return self._uuid_literal_pattern.findall(sql)
