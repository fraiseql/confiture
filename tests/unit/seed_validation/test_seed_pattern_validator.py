"""Tests for seed enumerated and test placeholder UUID validators."""

from confiture.core.seed_validation.seed_pattern_validator import (
    SeedEnumeratedValidator,
    TestPlaceholderValidator,
)


class TestSeedEnumeratedValidator:
    """Test seed enumerated UUID pattern validation."""

    def test_validates_read_seed_pattern_no_function_no_scenario(self):
        """Test valid read seed UUID (no test function, no scenario)."""
        uuid = "01421121-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_validates_multiple_read_seeds(self):
        """Test multiple valid read seed UUIDs with different increments."""
        validator = SeedEnumeratedValidator()
        schema_entity = "014211"
        directory = "21"

        assert validator.is_valid_pattern(
            "01421121-0000-0000-0000-000000000001", schema_entity, directory
        )
        assert validator.is_valid_pattern(
            "01421121-0000-0000-0000-000000000002", schema_entity, directory
        )
        assert validator.is_valid_pattern(
            "01421121-0000-0000-0000-000000000100", schema_entity, directory
        )

    def test_validates_test_function_with_scenario(self):
        """Test UUID with test function and scenario."""
        uuid = "01421121-4211-1000-0000-000000000001"
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_wrong_entity_prefix(self):
        """Test rejection of wrong schema entity."""
        uuid = "99999999-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_wrong_directory(self):
        """Test rejection of wrong directory code."""
        uuid = "01421131-0000-0000-0000-000000000001"  # Wrong directory (31 instead of 21)
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_nonzero_segment_4(self):
        """Test rejection of non-zero segment 4."""
        uuid = "01421121-4211-1000-1234-000000000001"  # Segment 4 should be 0000
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_nonnumeric_last_segment(self):
        """Test rejection of non-numeric last segment."""
        uuid = "01421121-0000-0000-0000-abcdefabcdef"  # Non-numeric last segment
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_invalid_function_segment_length(self):
        """Test rejection of invalid function segment length."""
        uuid = "01421121-421-1000-0000-000000000001"  # Function segment too short
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_invalid_function_hex(self):
        """Test rejection of invalid hex in function segment."""
        uuid = "01421121-421g-1000-0000-000000000001"  # Invalid hex character
        schema_entity = "014211"
        directory = "21"

        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_rejects_invalid_scenario_value(self):
        """Test rejection of invalid scenario values."""
        validator = SeedEnumeratedValidator()
        schema_entity = "014211"
        directory = "21"

        # Invalid scenario values
        assert not validator.is_valid_pattern(
            "01421121-0000-0500-0000-000000000001", schema_entity, directory
        )
        assert not validator.is_valid_pattern(
            "01421121-0000-4000-0000-000000000001", schema_entity, directory
        )

    def test_validates_all_three_scenarios(self):
        """Test validation of all three scenario values."""
        validator = SeedEnumeratedValidator()
        schema_entity = "014211"
        directory = "21"

        # Scenario 1
        assert validator.is_valid_pattern(
            "01421121-4211-1000-0000-000000000001", schema_entity, directory
        )
        # Scenario 2
        assert validator.is_valid_pattern(
            "01421121-4211-2000-0000-000000000001", schema_entity, directory
        )
        # Scenario 3
        assert validator.is_valid_pattern(
            "01421121-4211-3000-0000-000000000001", schema_entity, directory
        )

    def test_case_insensitive_entity_directory(self):
        """Test that entity and directory matching is case-insensitive."""
        validator = SeedEnumeratedValidator()

        # UUID with uppercase entity/directory
        uuid = "01421121-0000-0000-0000-000000000001"
        assert validator.is_valid_pattern(uuid, "014211", "21")
        assert validator.is_valid_pattern(uuid, "014211", "21")

    def test_rejects_empty_uuid(self):
        """Test rejection of empty UUID string."""
        validator = SeedEnumeratedValidator()
        assert not validator.is_valid_pattern("", "014211", "21")

    def test_rejects_invalid_uuid_length(self):
        """Test rejection of UUID with invalid length."""
        validator = SeedEnumeratedValidator()
        # Too short
        assert not validator.is_valid_pattern("01421121-0000-0000-0000", "014211", "21")
        # Too long
        assert not validator.is_valid_pattern(
            "01421121-0000-0000-0000-000000000001-extra", "014211", "21"
        )

    def test_rejects_invalid_segment_count(self):
        """Test rejection of UUID with wrong number of segments."""
        validator = SeedEnumeratedValidator()
        # 6 segments instead of 5
        assert not validator.is_valid_pattern(
            "01421121-0000-0000-0000-0000-00000001", "014211", "21"
        )
        # 4 segments instead of 5
        assert not validator.is_valid_pattern("01421121-0000-0000-0000", "014211", "21")


class TestTestPlaceholderValidator:
    """Test test placeholder UUID validation."""

    def test_validates_all_ones(self):
        """Test validation of all-ones UUID."""
        validator = TestPlaceholderValidator()
        assert validator.is_valid_pattern("11111111-1111-1111-1111-111111111111")

    def test_validates_all_twos(self):
        """Test validation of all-twos UUID."""
        validator = TestPlaceholderValidator()
        assert validator.is_valid_pattern("22222222-2222-2222-2222-222222222222")

    def test_validates_all_digits_0_to_9(self):
        """Test validation of all digit values 0-9."""
        validator = TestPlaceholderValidator()
        for digit in range(10):
            digit_char = str(digit)
            uuid = (
                f"{digit_char * 8}-{digit_char * 4}-{digit_char * 4}"
                f"-{digit_char * 4}-{digit_char * 12}"
            )
            assert validator.is_valid_pattern(uuid), f"Failed for digit {digit}"

    def test_rejects_mixed_digits(self):
        """Test rejection of mixed digit UUIDs."""
        validator = TestPlaceholderValidator()
        # Mixed first and second segments
        assert not validator.is_valid_pattern("11111111-2222-2222-2222-222222222222")
        # Mixed in different segment
        assert not validator.is_valid_pattern("11111111-1111-1111-2222-111111111111")

    def test_rejects_partial_match(self):
        """Test rejection of partial matching digits."""
        validator = TestPlaceholderValidator()
        # Most digits same but not all
        assert not validator.is_valid_pattern("11111112-1111-1111-1111-111111111111")
        assert not validator.is_valid_pattern("11111111-1112-1111-1111-111111111111")

    def test_rejects_hex_characters(self):
        """Test rejection of non-digit characters."""
        validator = TestPlaceholderValidator()
        assert not validator.is_valid_pattern("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        assert not validator.is_valid_pattern("abababab-abab-abab-abab-abababababab")

    def test_rejects_empty_uuid(self):
        """Test rejection of empty UUID."""
        validator = TestPlaceholderValidator()
        assert not validator.is_valid_pattern("")

    def test_rejects_invalid_length(self):
        """Test rejection of UUID with invalid length."""
        validator = TestPlaceholderValidator()
        # Too short
        assert not validator.is_valid_pattern("11111111-1111-1111-1111")
        # Too long
        assert not validator.is_valid_pattern("11111111-1111-1111-1111-111111111111-extra")

    def test_rejects_none_value(self):
        """Test rejection of None."""
        validator = TestPlaceholderValidator()
        assert not validator.is_valid_pattern(None)


class TestSeedPatternValidationIntegration:
    """Integration tests for seed pattern validators."""

    def test_different_patterns_for_different_scenarios(self):
        """Test that same table can have different UUID patterns."""
        seed_enum = SeedEnumeratedValidator()
        test_placeholder = TestPlaceholderValidator()

        schema_entity = "014211"
        directory = "21"

        # Same table, different UUID patterns
        uuid_enum = "01421121-0000-0000-0000-000000000001"
        uuid_placeholder = "11111111-1111-1111-1111-111111111111"

        assert seed_enum.is_valid_pattern(uuid_enum, schema_entity, directory)
        assert test_placeholder.is_valid_pattern(uuid_placeholder)

    def test_backend_seed_enumerated_examples(self):
        """Test seed enumerated validation with backend seed examples."""
        seed_enum = SeedEnumeratedValidator()

        # Backend reference data without function
        assert seed_enum.is_valid_pattern("01421121-0000-0000-0000-000000000001", "014211", "21")

        # Backend example with test function and scenario
        assert seed_enum.is_valid_pattern("01421121-4211-1000-0000-000000000001", "014211", "21")

    def test_frontend_seed_enumerated_examples(self):
        """Test seed enumerated validation with frontend seed examples."""
        seed_enum = SeedEnumeratedValidator()

        # Frontend reference data with directory 31
        assert seed_enum.is_valid_pattern("01312131-0000-0000-0000-000000000001", "013121", "31")

    def test_common_seed_enumerated_examples(self):
        """Test seed enumerated validation with common seed examples."""
        seed_enum = SeedEnumeratedValidator()

        # Common seed data with directory 11
        assert seed_enum.is_valid_pattern("01421111-0000-0000-0000-000000000001", "014211", "11")
