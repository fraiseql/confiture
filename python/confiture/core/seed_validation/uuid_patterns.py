"""UUID pattern type detection and categorization."""

from enum import Enum

from confiture.core.seed_validation.seed_pattern_validator import (
    SeedEnumeratedValidator,
    TestPlaceholderValidator,
)
from confiture.core.seed_validation.uuid_validator import UUIDValidator


class UUIDPatternType(Enum):
    """Enumeration of UUID pattern types found in seed data."""

    RFC4122_RANDOM = "rfc4122_random"
    SEED_ENUMERATED = "seed_enumerated"
    TEST_PLACEHOLDER = "test_placeholder"


class UUIDPatternDetector:
    """Detector for UUID pattern types in seed data.

    Categorizes UUIDs into three types:
    1. RFC4122_RANDOM: Standard random UUIDs
    2. SEED_ENUMERATED: Seed-specific enumerated pattern
    3. TEST_PLACEHOLDER: Repeating digit test placeholders
    """

    def __init__(self) -> None:
        """Initialize detector with validators."""
        self._uuid_validator = UUIDValidator()
        self._seed_enum_validator = SeedEnumeratedValidator()
        self._placeholder_validator = TestPlaceholderValidator()

    def detect_type(
        self,
        uuid_str: str,
        schema_entity: str | None = None,
        directory: str | None = None,
        is_seed_file: bool = False,
    ) -> UUIDPatternType | None:
        """Detect the pattern type of a UUID.

        Detection order:
        1. Check if valid RFC 4122 format (if not, return None)
        2. Check if test placeholder (repeating digits)
        3. Check if seed enumerated (if in seed file with context)
        4. Default to RFC4122_RANDOM

        Args:
            uuid_str: UUID string to analyze
            schema_entity: Schema entity number (required for seed enumerated detection)
            directory: Directory code (required for seed enumerated detection)
            is_seed_file: Whether UUID is from a seed file

        Returns:
            UUIDPatternType if UUID is valid, None if invalid format

        Examples:
            >>> detector = UUIDPatternDetector()
            >>> detector.detect_type('2422ffde-753e-4645-836d-4d0499a96465')
            <UUIDPatternType.RFC4122_RANDOM: 'rfc4122_random'>
            >>> detector.detect_type(
            ...     '01421121-0000-0000-0000-000000000001',
            ...     schema_entity='014211', directory='21', is_seed_file=True
            ... )
            <UUIDPatternType.SEED_ENUMERATED: 'seed_enumerated'>
        """
        # Check if UUID is valid RFC 4122 format
        if not self._uuid_validator.is_valid_uuid(uuid_str):
            return None

        # Test placeholder pattern takes priority (simple check)
        if self._placeholder_validator.is_valid_pattern(uuid_str):
            return UUIDPatternType.TEST_PLACEHOLDER

        # Check for seed enumerated pattern (if in seed file with context)
        if (
            is_seed_file
            and schema_entity
            and directory
            and self._seed_enum_validator.is_valid_pattern(uuid_str, schema_entity, directory)
        ):
            return UUIDPatternType.SEED_ENUMERATED

        # Default to random RFC 4122
        return UUIDPatternType.RFC4122_RANDOM
