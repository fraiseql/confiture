"""Validators for seed-specific UUID patterns.

This module provides:
- SchemaEntityExtractor: Maps seed table numbers to canonical schema entities
- DirectoryExtractor: Extracts directory codes from seed file paths
- SeedEnumeratedValidator: Validates seed enumerated UUID patterns
- TestPlaceholderValidator: Validates test placeholder UUIDs
"""

import re
from pathlib import Path


class SchemaEntityExtractor:
    """Extract canonical schema entity numbers from seed file paths.

    Schema entities are the canonical table numbers from db/0_schema.
    Seed tables map to them by replacing the seed level digit with 0.

    Examples:
        - Seed backend 214211 → Schema 014211
        - Seed frontend 314211 → Schema 014211
        - Seed common 114211 → Schema 014211
    """

    def extract_schema_entity(self, seed_path: Path) -> str:
        """Extract schema entity number from a seed file path.

        Converts seed table number to canonical schema table number
        by replacing the first digit (seed level) with 0.

        Args:
            seed_path: Path to seed file (e.g., db/2_seed_backend/21_.../214211_table.sql)

        Returns:
            Schema entity number as string (e.g., "014211")

        Examples:
            >>> extractor = SchemaEntityExtractor()
            >>> path = Path("db/2_seed_backend/21_write_side/214_dim/2142_org/21421_org_unit/214211_tb.sql")
            >>> extractor.extract_schema_entity(path)
            '014211'
        """
        # Extract table number from filename (first digits before underscore)
        filename = seed_path.name
        match = re.match(r"(\d+)", filename)
        if not match:
            return ""

        table_num = match.group(1)

        # Convert seed level digit to 0
        # First digit is seed level (1, 2, 3, 6)
        # Rest is the actual hierarchy
        if len(table_num) > 0:
            return "0" + table_num[1:]

        return ""


class DirectoryExtractor:
    """Extract directory codes from seed file paths.

    The directory code is the first 2 digits of the materialized path,
    which combines seed level and first category.

    Examples:
        - db/2_seed_backend/21_write_side → "21"
        - db/3_seed_frontend/31_write_side → "31"
        - db/1_seed_common/11_write_side → "11"
    """

    def extract_directory(self, seed_path: Path) -> str:
        """Extract directory number from seed file path.

        Gets the first 2 digits of the seed materialized path
        (seed level + first category digit).

        The directory code is found in the first named directory after
        the seed level (e.g., 21_write_side, 31_catalog, etc.)

        Args:
            seed_path: Path to seed file

        Returns:
            Directory code as 2-digit string (e.g., "21")

        Examples:
            >>> extractor = DirectoryExtractor()
            >>> path = Path("db/2_seed_backend/21_write_side/214_dim/214211_table.sql")
            >>> extractor.extract_directory(path)
            '21'
        """
        # Look for numeric directory codes in path
        # Skip "db" and look for patterns like "2_seed_backend", "21_write_side"
        parts = seed_path.parts
        numeric_dirs = []

        for part in parts:
            match = re.match(r"^(\d+)", part)
            if match:
                code = match.group(1)
                numeric_dirs.append(code)

        # We want the second numeric directory (first is seed level like "2",
        # second is the directory code like "21")
        if len(numeric_dirs) >= 2:
            return numeric_dirs[1]

        return ""


class SeedEnumeratedValidator:
    """Validator for seed enumerated UUID pattern.

    Seed enumerated UUIDs follow the pattern:
    {entity:6}{directory:2}-{function:4}-{scenario:4}-0000-{increment:12}

    Where:
    - entity: Schema table number (6 digits)
    - directory: Seed level + category (2 digits)
    - function: 0000 for read-only, or 4-digit function number
    - scenario: 0000 for no scenario, or 1000/2000/3000 for scenarios
    - segment 4: Always 0000
    - increment: Sequential counter (numeric)
    """

    def is_valid_pattern(self, uuid_str: str, schema_entity: str, directory: str) -> bool:
        """Check if UUID matches seed enumerated pattern.

        Args:
            uuid_str: UUID string to validate
            schema_entity: Expected schema entity (6 digits)
            directory: Expected directory code (2 digits)

        Returns:
            True if UUID matches the pattern, False otherwise

        Examples:
            >>> validator = SeedEnumeratedValidator()
            >>> validator.is_valid_pattern(
            ...     '01421121-0000-0000-0000-000000000001',
            ...     '014211', '21'
            ... )
            True
        """
        if not uuid_str or len(uuid_str) != 36:
            return False

        # Split UUID into segments
        parts = uuid_str.split("-")
        if len(parts) != 5:
            return False

        first_seg, seg2, seg3, seg4, seg5 = parts

        # Check first segment: entity (6) + directory (2) = 8 chars
        expected_prefix = schema_entity + directory
        if first_seg.lower() != expected_prefix.lower():
            return False

        # Check segment 2: function (0000 or 4-digit hex)
        if not self._is_valid_function(seg2):
            return False

        # Check segment 3: scenario (0000 or 1000/2000/3000)
        if not self._is_valid_scenario(seg3):
            return False

        # Check segment 4: always 0000
        if seg4 != "0000":
            return False

        # Check segment 5: numeric increment
        return self._is_valid_increment(seg5)

    @staticmethod
    def _is_valid_function(func_seg: str) -> bool:
        """Check if function segment is valid."""
        if len(func_seg) != 4:
            return False
        # Must be 4 hex digits
        try:
            int(func_seg, 16)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_valid_scenario(scenario_seg: str) -> bool:
        """Check if scenario segment is valid."""
        if len(scenario_seg) != 4:
            return False
        # Must be 0000 or 1000, 2000, 3000
        return scenario_seg in ("0000", "1000", "2000", "3000")

    @staticmethod
    def _is_valid_increment(increment_seg: str) -> bool:
        """Check if increment segment is valid."""
        if len(increment_seg) != 12:
            return False
        # Must be all numeric
        return increment_seg.isdigit()


class TestPlaceholderValidator:
    """Validator for test placeholder UUID pattern.

    Test placeholder UUIDs have all segments containing the same digit.
    Examples: 11111111-1111-1111-1111-111111111111
    """

    def is_valid_pattern(self, uuid_str: str) -> bool:
        """Check if UUID is a valid test placeholder.

        Args:
            uuid_str: UUID string to validate

        Returns:
            True if all segments contain the same digit, False otherwise

        Examples:
            >>> validator = TestPlaceholderValidator()
            >>> validator.is_valid_pattern('11111111-1111-1111-1111-111111111111')
            True
            >>> validator.is_valid_pattern('11111111-2222-2222-2222-222222222222')
            False
        """
        if not uuid_str or len(uuid_str) != 36:
            return False

        # Get all non-dash characters
        chars = uuid_str.replace("-", "")
        if len(chars) != 32:
            return False

        # Check if all characters are the same and digit
        if not chars or not chars.isdigit():
            return False

        return all(c == chars[0] for c in chars)
