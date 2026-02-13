"""Tests for extracting schema entities from seed file paths."""

from pathlib import Path

from confiture.core.seed_validation.seed_pattern_validator import (
    DirectoryExtractor,
    SchemaEntityExtractor,
)


class TestSchemaEntityExtractor:
    """Test extraction of canonical schema entity numbers from seed paths."""

    def test_extracts_schema_entity_from_seed_backend_path(self):
        """Test extracting schema entity from backend seed path."""
        extractor = SchemaEntityExtractor()
        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Schema equivalent: db/0_schema/01_write_side/...014211...
        assert schema_entity == "014211"

    def test_extracts_schema_entity_from_seed_frontend_path(self):
        """Test extracting schema entity from frontend seed path."""
        extractor = SchemaEntityExtractor()
        seed_path = Path(
            "db/3_seed_frontend/31_write_side/314_dim/3142_org/"
            "31421_organizational_unit/314211_tb_org_info.sql"
        )

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Schema equivalent: db/0_schema/01_write_side/...014211...
        assert schema_entity == "014211"

    def test_extracts_schema_entity_from_seed_common_path(self):
        """Test extracting schema entity from common seed path."""
        extractor = SchemaEntityExtractor()
        seed_path = Path(
            "db/1_seed_common/11_write_side/114_dim/1142_org/"
            "11421_organizational_unit/114211_tb_org_info.sql"
        )

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Schema equivalent: db/0_schema/01_write_side/...014211...
        assert schema_entity == "014211"

    def test_extracts_schema_entity_from_seed_etl_path(self):
        """Test extracting schema entity from ETL seed path."""
        extractor = SchemaEntityExtractor()
        seed_path = Path(
            "db/6_seed_etl/61_write_side/614_dim/6142_org/"
            "61421_organizational_unit/614211_tb_org_info.sql"
        )

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Schema equivalent: db/0_schema/01_write_side/...014211...
        assert schema_entity == "014211"

    def test_handles_shorter_table_numbers(self):
        """Test extraction with shorter table numbers."""
        extractor = SchemaEntityExtractor()
        seed_path = Path("db/2_seed_backend/21_write_side/214_dim/2142_product.sql")

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Should convert seed level 2 to 0: 2142 → 0142
        assert schema_entity == "0142"

    def test_handles_longer_table_numbers_with_variants(self):
        """Test extraction with table number variants (extra digits)."""
        extractor = SchemaEntityExtractor()
        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_org_unit/2142111_tb_org_info_variant.sql"
        )

        schema_entity = extractor.extract_schema_entity(seed_path)

        # Variant digit is preserved
        assert schema_entity == "0142111"


class TestDirectoryExtractor:
    """Test extraction of directory codes from seed paths."""

    def test_extracts_directory_first_two_digits_from_seed_backend(self):
        """Test extracting directory from backend seed path."""
        extractor = DirectoryExtractor()
        seed_path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_organizational_unit_info.sql"
        )

        directory = extractor.extract_directory(seed_path)

        # First 2 digits of materialized path: 21_write_side → "21"
        assert directory == "21"

    def test_extracts_directory_from_seed_frontend(self):
        """Test extracting directory from frontend seed path."""
        extractor = DirectoryExtractor()
        seed_path = Path(
            "db/3_seed_frontend/31_write_side/314_dim/3142_org/"
            "31421_organizational_unit/314211_tb_org_info.sql"
        )

        directory = extractor.extract_directory(seed_path)

        # First 2 digits: 31_write_side → "31"
        assert directory == "31"

    def test_extracts_directory_from_seed_common(self):
        """Test extracting directory from common seed path."""
        extractor = DirectoryExtractor()
        seed_path = Path(
            "db/1_seed_common/11_write_side/114_dim/1142_org/"
            "11421_organizational_unit/114211_tb_org_info.sql"
        )

        directory = extractor.extract_directory(seed_path)

        # First 2 digits: 11_write_side → "11"
        assert directory == "11"

    def test_extracts_directory_from_seed_etl(self):
        """Test extracting directory from ETL seed path."""
        extractor = DirectoryExtractor()
        seed_path = Path(
            "db/6_seed_etl/61_write_side/614_dim/6142_org/"
            "61421_organizational_unit/614211_tb_org_info.sql"
        )

        directory = extractor.extract_directory(seed_path)

        # First 2 digits: 61_write_side → "61"
        assert directory == "61"

    def test_extracts_from_relative_path(self):
        """Test extraction from relative path."""
        extractor = DirectoryExtractor()
        seed_path = Path("2_seed_backend/21_write_side/214_dim/2142_org.sql")

        directory = extractor.extract_directory(seed_path)

        # First 2 digits: 21_write_side → "21"
        assert directory == "21"


class TestExtractorsWithMultipleSeedLevels:
    """Test extractors with file paths across different seed environments."""

    def test_backend_seed_extraction(self):
        """Test extraction from backend seed path."""
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()

        path = Path(
            "db/2_seed_backend/21_write_side/214_dim/2142_org/"
            "21421_organizational_unit/214211_tb_reference_data.sql"
        )

        assert schema_extractor.extract_schema_entity(path) == "014211"
        assert dir_extractor.extract_directory(path) == "21"

    def test_frontend_seed_extraction(self):
        """Test extraction from frontend seed path."""
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()

        path = Path(
            "db/3_seed_frontend/31_catalog/313_products/"
            "3131_catalog_product/313121_product_types.sql"
        )

        # Frontend (3) converts to schema (0), rest preserved
        assert schema_extractor.extract_schema_entity(path) == "013121"
        assert dir_extractor.extract_directory(path) == "31"

    def test_extraction_consistency_across_seed_levels(self):
        """Test extraction consistency across different seed environments."""
        schema_extractor = SchemaEntityExtractor()
        dir_extractor = DirectoryExtractor()

        paths_and_expected = [
            (
                "db/1_seed_common/11_write_side/011_crm/.../011211_org.sql",
                "011211",
                "11",
            ),
            (
                "db/2_seed_backend/21_write_side/214_dim/.../014211_org.sql",
                "014211",
                "21",
            ),
            (
                "db/3_seed_frontend/31_write_side/314_dim/.../014211_org.sql",
                "014211",
                "31",
            ),
        ]

        for path_str, expected_entity, expected_dir in paths_and_expected:
            path = Path(path_str)
            assert schema_extractor.extract_schema_entity(path) == expected_entity, (
                f"Failed for path: {path_str}"
            )
            assert dir_extractor.extract_directory(path) == expected_dir, (
                f"Failed for path: {path_str}"
            )
