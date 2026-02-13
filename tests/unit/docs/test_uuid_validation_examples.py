"""Tests that documentation examples are valid and executable."""

from confiture.core.seed_validation.seed_pattern_validator import (
    SeedEnumeratedValidator,
    TestPlaceholderValidator,
)
from confiture.core.seed_validation.uuid_validator import UUIDValidator


class TestUUIDValidationDocExamples:
    """Test that examples in UUID validation documentation are valid."""

    def test_rfc4122_example_is_valid(self) -> None:
        """Test RFC 4122 example from documentation."""
        validator = UUIDValidator()

        # Example from docs: RFC 4122 Random UUID
        uuid = "2422ffde-753e-4645-836d-4d0499a96465"
        assert validator.is_valid_uuid(uuid)

    def test_seed_enumerated_read_seed_example_is_valid(self) -> None:
        """Test seed enumerated read seed example."""
        validator = SeedEnumeratedValidator()

        # Example: Backend organizational units
        uuid = "01421121-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "21"

        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_seed_enumerated_with_function_example_is_valid(self) -> None:
        """Test seed enumerated with test function example."""
        validator = SeedEnumeratedValidator()

        # Example: Test function 4211, scenario 1
        uuid = "01421121-4211-1000-0000-000000000001"
        schema_entity = "014211"
        directory = "21"

        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_seed_enumerated_frontend_example_is_valid(self) -> None:
        """Test seed enumerated frontend example (directory 31)."""
        validator = SeedEnumeratedValidator()

        # Example: Frontend directory (31)
        uuid = "01421131-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "31"

        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_seed_enumerated_common_example_is_valid(self) -> None:
        """Test seed enumerated common seed example (directory 11)."""
        validator = SeedEnumeratedValidator()

        # Example: Common seed directory (11)
        uuid = "01421111-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "11"

        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_test_placeholder_all_ones_example_is_valid(self) -> None:
        """Test placeholder all-ones example."""
        validator = TestPlaceholderValidator()

        uuid = "11111111-1111-1111-1111-111111111111"
        assert validator.is_valid_pattern(uuid)

    def test_test_placeholder_all_twos_example_is_valid(self) -> None:
        """Test placeholder all-twos example."""
        validator = TestPlaceholderValidator()

        uuid = "22222222-2222-2222-2222-222222222222"
        assert validator.is_valid_pattern(uuid)

    def test_printoptim_product_uuid_examples_are_valid(self) -> None:
        """Test PrintOptim product examples from documentation."""
        validator = SeedEnumeratedValidator()

        # Product entity: 014311, Backend directory: 21
        assert validator.is_valid_pattern("01431121-0000-0000-0000-000000000001", "014311", "21")

        # Product variant with test function 4321, scenario 2
        assert validator.is_valid_pattern("01431121-4321-2000-0000-000000000001", "014311", "21")

    def test_printoptim_currency_codes_example_is_valid(self) -> None:
        """Test PrintOptim currency codes example (common seed)."""
        validator = SeedEnumeratedValidator()

        # Currency codes entity (example), common directory: 11
        uuid = "01421111-0000-0000-0000-000000000001"
        schema_entity = "014211"
        directory = "11"

        assert validator.is_valid_pattern(uuid, schema_entity, directory)

    def test_uuid_extraction_from_sql_example(self) -> None:
        """Test UUID extraction example from documentation."""
        validator = UUIDValidator()

        sql = "INSERT INTO users (id) VALUES ('2422ffde-753e-4645-836d-4d0499a96465');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 1
        assert uuids[0] == "2422ffde-753e-4645-836d-4d0499a96465"

    def test_multi_row_insert_extraction(self) -> None:
        """Test multi-row INSERT UUID extraction."""
        validator = UUIDValidator()

        sql = """INSERT INTO tb_organizational_unit_info (id, name, parent_id) VALUES
          ('01421121-0000-0000-0000-000000000001', 'Headquarters', NULL),
          ('01421121-0000-0000-0000-000000000002', 'Engineering', '01421121-0000-0000-0000-000000000001');"""

        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 3
        assert uuids[0] == "01421121-0000-0000-0000-000000000001"
        assert uuids[1] == "01421121-0000-0000-0000-000000000002"
        assert uuids[2] == "01421121-0000-0000-0000-000000000001"

    def test_all_documented_seed_levels_have_correct_directories(
        self,
    ) -> None:
        """Test that all documented seed levels use correct directory codes."""
        # From documentation mapping table
        examples = [
            ("014211", "21", "Backend"),  # 2_seed_backend
            ("014211", "31", "Frontend"),  # 3_seed_frontend
            ("014211", "11", "Common"),  # 1_seed_common
            ("014211", "61", "ETL"),  # 6_seed_etl (if exists)
        ]

        validator = SeedEnumeratedValidator()

        for entity, directory, label in examples:
            uuid = f"{entity[0:6]}{directory}-0000-0000-0000-000000000001"
            assert validator.is_valid_pattern(uuid, entity, directory), f"Failed for {label}"
