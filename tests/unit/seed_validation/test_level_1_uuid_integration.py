"""Tests for Level 1 UUID validation integration."""

from pathlib import Path

from confiture.core.seed_validation.seed_pattern_validator import (
    DirectoryExtractor,
    SchemaEntityExtractor,
)
from confiture.core.seed_validation.uuid_patterns import UUIDPatternDetector
from confiture.core.seed_validation.uuid_validator import UUIDValidator


class TestLevel1UUIDIntegration:
    """Test integration of UUID validators into Level 1 validation."""

    def test_full_uuid_validation_pipeline_read_seed(self):
        """Test complete UUID validation pipeline for read seed."""
        # Simulate Level 1 validation flow
        uuid_validator = UUIDValidator()
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()
        pattern_detector = UUIDPatternDetector()

        # Seed file path
        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        # SQL content
        sql = (
            "INSERT INTO prep_seed.tb_organizational_unit_info (id, name) "
            "VALUES ('01421121-0000-0000-0000-000000000001', 'Unit1');"
        )

        # Step 1: Extract UUIDs from SQL
        uuids = uuid_validator.extract_uuid_literals(sql)
        assert len(uuids) == 1
        uuid = uuids[0]

        # Step 2: Validate UUID format
        assert uuid_validator.is_valid_uuid(uuid)

        # Step 3: Extract schema context
        schema_entity = schema_extractor.extract_schema_entity(seed_path)
        directory = dir_extractor.extract_directory(seed_path)
        assert schema_entity == "014211"
        assert directory == "21"

        # Step 4: Detect pattern type
        pattern = pattern_detector.detect_type(
            uuid, schema_entity=schema_entity, directory=directory, is_seed_file=True
        )
        from confiture.core.seed_validation.uuid_patterns import UUIDPatternType

        assert pattern == UUIDPatternType.SEED_ENUMERATED

    def test_full_uuid_validation_pipeline_with_function(self):
        """Test complete pipeline with test function and scenario."""
        uuid_validator = UUIDValidator()
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()
        pattern_detector = UUIDPatternDetector()

        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        sql = (
            "INSERT INTO prep_seed.tb_organizational_unit_info (id, name) "
            "VALUES ('01421121-4211-1000-0000-000000000001', 'TestUnit');"
        )

        uuids = uuid_validator.extract_uuid_literals(sql)
        assert len(uuids) == 1
        uuid = uuids[0]

        assert uuid_validator.is_valid_uuid(uuid)

        schema_entity = schema_extractor.extract_schema_entity(seed_path)
        directory = dir_extractor.extract_directory(seed_path)

        pattern = pattern_detector.detect_type(
            uuid, schema_entity=schema_entity, directory=directory, is_seed_file=True
        )
        from confiture.core.seed_validation.uuid_patterns import UUIDPatternType

        assert pattern == UUIDPatternType.SEED_ENUMERATED

    def test_detects_invalid_uuid_in_pipeline(self):
        """Test detection of invalid UUID in pipeline."""
        uuid_validator = UUIDValidator()

        # Invalid UUID (missing segment)
        sql = (
            "INSERT INTO prep_seed.tb_organizational_unit_info (id, name) "
            "VALUES ('01421121-0000-0000-0000', 'Unit1');"
        )

        uuids = uuid_validator.extract_uuid_literals(sql)
        # Extraction should find nothing (format is invalid)
        assert len(uuids) == 0

    def test_detects_wrong_entity_in_seed_file(self):
        """Test detection of wrong entity in seed enumerated UUID."""
        uuid_validator = UUIDValidator()
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()
        pattern_detector = UUIDPatternDetector()

        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        # UUID with wrong entity prefix
        sql = (
            "INSERT INTO prep_seed.tb_organizational_unit_info (id, name) "
            "VALUES ('99999999-0000-0000-0000-000000000001', 'Unit1');"
        )

        uuids = uuid_validator.extract_uuid_literals(sql)
        assert len(uuids) == 1
        uuid = uuids[0]

        assert uuid_validator.is_valid_uuid(uuid)

        schema_entity = schema_extractor.extract_schema_entity(seed_path)
        directory = dir_extractor.extract_directory(seed_path)

        # Pattern detection should not find seed enumerated match
        pattern = pattern_detector.detect_type(
            uuid, schema_entity=schema_entity, directory=directory, is_seed_file=True
        )
        from confiture.core.seed_validation.uuid_patterns import UUIDPatternType

        assert pattern == UUIDPatternType.RFC4122_RANDOM

    def test_handles_multiple_uuids_in_multi_row_insert(self):
        """Test handling multiple UUIDs in multi-row INSERT."""
        uuid_validator = UUIDValidator()
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()
        pattern_detector = UUIDPatternDetector()

        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        sql = """INSERT INTO prep_seed.tb_organizational_unit_info (id, name) VALUES
    ('01421121-0000-0000-0000-000000000001', 'Unit1'),
    ('01421121-0000-0000-0000-000000000002', 'Unit2'),
    ('11111111-1111-1111-1111-111111111111', 'Placeholder');"""

        uuids = uuid_validator.extract_uuid_literals(sql)
        assert len(uuids) == 3

        schema_entity = schema_extractor.extract_schema_entity(seed_path)
        directory = dir_extractor.extract_directory(seed_path)

        from confiture.core.seed_validation.uuid_patterns import UUIDPatternType

        # First two should be seed enumerated
        for i in range(2):
            pattern = pattern_detector.detect_type(
                uuids[i], schema_entity=schema_entity, directory=directory, is_seed_file=True
            )
            assert pattern == UUIDPatternType.SEED_ENUMERATED

        # Third should be test placeholder
        pattern = pattern_detector.detect_type(uuids[2])
        assert pattern == UUIDPatternType.TEST_PLACEHOLDER

    def test_validation_across_all_seed_levels(self):
        """Test UUID validation works across all seed levels."""
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()
        pattern_detector = UUIDPatternDetector()

        seed_paths_and_uuids = [
            (
                Path("db/1_seed_common/11_write_side/011_crm/.../011211_org.sql"),
                "01121111-0000-0000-0000-000000000001",
                "011211",
                "11",
            ),
            (
                Path("db/2_seed_backend/21_write_side/214_dim/.../014211_org.sql"),
                "01421121-0000-0000-0000-000000000001",
                "014211",
                "21",
            ),
            (
                Path("db/3_seed_frontend/31_write_side/314_dim/.../014211_org.sql"),
                "01421131-0000-0000-0000-000000000001",
                "014211",
                "31",
            ),
        ]

        from confiture.core.seed_validation.uuid_patterns import UUIDPatternType

        for path, uuid, expected_entity, expected_dir in seed_paths_and_uuids:
            schema_entity = schema_extractor.extract_schema_entity(path)
            directory = dir_extractor.extract_directory(path)

            assert schema_entity == expected_entity, f"Failed for path: {path}"
            assert directory == expected_dir, f"Failed for path: {path}"

            pattern = pattern_detector.detect_type(
                uuid, schema_entity=schema_entity, directory=directory, is_seed_file=True
            )
            assert pattern == UUIDPatternType.SEED_ENUMERATED, (
                f"Failed to detect seed enumerated for: {path}"
            )
