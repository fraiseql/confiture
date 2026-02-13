"""Tests for UUID pattern type detection and categorization."""

from confiture.core.seed_validation.uuid_patterns import (
    UUIDPatternDetector,
    UUIDPatternType,
)


class TestUUIDPatternDetection:
    """Test automatic pattern type detection."""

    def test_categorizes_random_uuid(self):
        """Test categorization of random RFC 4122 UUID."""
        uuid = "2422ffde-753e-4645-836d-4d0499a96465"
        detector = UUIDPatternDetector()
        pattern_type = detector.detect_type(uuid)

        assert pattern_type == UUIDPatternType.RFC4122_RANDOM

    def test_categorizes_seed_enumerated_read_seed(self):
        """Test categorization of seed enumerated UUID (read seed)."""
        uuid = "01421121-0000-0000-0000-000000000001"
        detector = UUIDPatternDetector()
        pattern_type = detector.detect_type(
            uuid, schema_entity="014211", directory="21", is_seed_file=True
        )

        assert pattern_type == UUIDPatternType.SEED_ENUMERATED

    def test_categorizes_seed_enumerated_with_function(self):
        """Test categorization of seed enumerated UUID with function."""
        uuid = "01421121-4211-1000-0000-000000000001"
        detector = UUIDPatternDetector()
        pattern_type = detector.detect_type(
            uuid, schema_entity="014211", directory="21", is_seed_file=True
        )

        assert pattern_type == UUIDPatternType.SEED_ENUMERATED

    def test_categorizes_test_placeholder(self):
        """Test categorization of test placeholder UUID."""
        uuid = "11111111-1111-1111-1111-111111111111"
        detector = UUIDPatternDetector()
        pattern_type = detector.detect_type(uuid)

        assert pattern_type == UUIDPatternType.TEST_PLACEHOLDER

    def test_categorizes_test_placeholder_all_twos(self):
        """Test categorization of test placeholder with different digit."""
        uuid = "22222222-2222-2222-2222-222222222222"
        detector = UUIDPatternDetector()
        pattern_type = detector.detect_type(uuid)

        assert pattern_type == UUIDPatternType.TEST_PLACEHOLDER

    def test_test_placeholder_takes_priority_over_random(self):
        """Test that test placeholder is detected before random UUID."""
        uuid = "11111111-1111-1111-1111-111111111111"
        detector = UUIDPatternDetector()
        # Even if we pass seed file context, test placeholder should be detected
        pattern_type = detector.detect_type(
            uuid, schema_entity="111111", directory="11", is_seed_file=True
        )

        assert pattern_type == UUIDPatternType.TEST_PLACEHOLDER

    def test_seed_enumerated_requires_seed_file_context(self):
        """Test that seed enumerated requires is_seed_file=True."""
        uuid = "01421121-0000-0000-0000-000000000001"
        detector = UUIDPatternDetector()

        # Without seed file context, should be random
        pattern_type = detector.detect_type(uuid, is_seed_file=False)
        assert pattern_type == UUIDPatternType.RFC4122_RANDOM

        # With seed file context and entity/directory, should be seed enumerated
        pattern_type = detector.detect_type(
            uuid, schema_entity="014211", directory="21", is_seed_file=True
        )
        assert pattern_type == UUIDPatternType.SEED_ENUMERATED

    def test_seed_enumerated_requires_entity_and_directory(self):
        """Test that seed enumerated detection requires entity and directory."""
        uuid = "01421121-0000-0000-0000-000000000001"
        detector = UUIDPatternDetector()

        # With seed file but no entity/directory, should be random
        pattern_type = detector.detect_type(uuid, is_seed_file=True)
        assert pattern_type == UUIDPatternType.RFC4122_RANDOM

    def test_multiple_uuids_different_patterns(self):
        """Test detection of multiple different UUID patterns."""
        detector = UUIDPatternDetector()

        random_uuid = "2422ffde-753e-4645-836d-4d0499a96465"
        seed_uuid = "01421121-0000-0000-0000-000000000001"
        placeholder_uuid = "11111111-1111-1111-1111-111111111111"

        assert detector.detect_type(random_uuid) == UUIDPatternType.RFC4122_RANDOM
        assert (
            detector.detect_type(
                seed_uuid, schema_entity="014211", directory="21", is_seed_file=True
            )
            == UUIDPatternType.SEED_ENUMERATED
        )
        assert detector.detect_type(placeholder_uuid) == UUIDPatternType.TEST_PLACEHOLDER

    def test_detects_invalid_uuid_as_none(self):
        """Test that invalid UUIDs are detected as None type."""
        detector = UUIDPatternDetector()

        # Invalid format
        pattern_type = detector.detect_type("not-a-uuid-at-all")
        assert pattern_type is None

        # Invalid segment count
        pattern_type = detector.detect_type("01421121-0000-0000-0000")
        assert pattern_type is None

    def test_detection_with_context_printoptim_backend(self):
        """Test detection with PrintOptim backend context."""
        detector = UUIDPatternDetector()

        # Real backend seed enumerated
        uuid = "01421121-0000-0000-0000-000000000001"
        pattern_type = detector.detect_type(
            uuid, schema_entity="014211", directory="21", is_seed_file=True
        )
        assert pattern_type == UUIDPatternType.SEED_ENUMERATED

    def test_detection_with_context_printoptim_frontend(self):
        """Test detection with PrintOptim frontend context."""
        detector = UUIDPatternDetector()

        # Real frontend seed enumerated
        uuid = "01312131-0000-0000-0000-000000000001"
        pattern_type = detector.detect_type(
            uuid, schema_entity="013121", directory="31", is_seed_file=True
        )
        assert pattern_type == UUIDPatternType.SEED_ENUMERATED

    def test_detection_with_context_printoptim_common(self):
        """Test detection with PrintOptim common seed context."""
        detector = UUIDPatternDetector()

        # Real common seed enumerated
        uuid = "01421111-0000-0000-0000-000000000001"
        pattern_type = detector.detect_type(
            uuid, schema_entity="014211", directory="11", is_seed_file=True
        )
        assert pattern_type == UUIDPatternType.SEED_ENUMERATED


class TestUUIDPatternTypeEnum:
    """Test UUID pattern type enum."""

    def test_has_required_pattern_types(self):
        """Test that enum has all required pattern types."""
        assert hasattr(UUIDPatternType, "RFC4122_RANDOM")
        assert hasattr(UUIDPatternType, "SEED_ENUMERATED")
        assert hasattr(UUIDPatternType, "TEST_PLACEHOLDER")

    def test_pattern_types_are_distinct(self):
        """Test that pattern types are distinct values."""
        assert UUIDPatternType.RFC4122_RANDOM != UUIDPatternType.SEED_ENUMERATED
        assert UUIDPatternType.SEED_ENUMERATED != UUIDPatternType.TEST_PLACEHOLDER
        assert UUIDPatternType.RFC4122_RANDOM != UUIDPatternType.TEST_PLACEHOLDER
