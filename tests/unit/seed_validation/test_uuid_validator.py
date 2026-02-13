"""Tests for UUID format validation (RFC 4122)."""

from confiture.core.seed_validation.uuid_validator import UUIDValidator


class TestUUIDFormatValidation:
    """Test RFC 4122 format validation."""

    def test_valid_rfc4122_uuid(self):
        """Test that valid RFC 4122 UUIDs are accepted."""
        validator = UUIDValidator()
        assert validator.is_valid_uuid("01442fe1-00c7-0000-0000-000000000001")
        assert validator.is_valid_uuid("2422ffde-753e-4645-836d-4d0499a96465")

    def test_valid_uppercase_uuid(self):
        """Test that uppercase UUIDs are accepted."""
        validator = UUIDValidator()
        assert validator.is_valid_uuid("01442FE1-00C7-0000-0000-000000000001")

    def test_rejects_invalid_segment_length_short_second(self):
        """Test that UUIDs with short second segment are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe1-c7-0000-0000-000000000001")

    def test_rejects_invalid_segment_length_long_second(self):
        """Test that UUIDs with long second segment are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe1-00c77-0000-0000-000000000001")

    def test_rejects_invalid_hex_character_in_first(self):
        """Test that invalid hex characters are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("0144zfe1-00c7-0000-0000-000000000001")

    def test_rejects_invalid_hex_character_in_second(self):
        """Test that invalid hex characters in second segment are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe1-00cz-0000-0000-000000000001")

    def test_rejects_invalid_hex_character_in_last(self):
        """Test that invalid hex characters in last segment are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe1-00c7-0000-0000-00000000000g")

    def test_rejects_missing_dashes(self):
        """Test that UUIDs without dashes are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe100c70000000000000000000001")

    def test_rejects_extra_dashes(self):
        """Test that UUIDs with extra dashes are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442fe1-00c7-0000-0000-00000000-0001")

    def test_rejects_wrong_dash_positions(self):
        """Test that UUIDs with dashes in wrong positions are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("01442-fe100c7-0000-0000-000000000001")

    def test_rejects_empty_string(self):
        """Test that empty strings are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid("")

    def test_rejects_none_value(self):
        """Test that None values are rejected."""
        validator = UUIDValidator()
        assert not validator.is_valid_uuid(None)


class TestUUIDExtraction:
    """Test UUID extraction from SQL statements."""

    def test_finds_uuid_in_simple_insert(self):
        """Test finding UUID in simple INSERT statement."""
        validator = UUIDValidator()
        sql = (
            "INSERT INTO users (id, name) VALUES ('01442fe1-00c7-0000-0000-000000000001', 'Alice');"
        )
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 1
        assert uuids[0] == "01442fe1-00c7-0000-0000-000000000001"

    def test_finds_multiple_uuids_in_single_statement(self):
        """Test finding multiple UUIDs in one statement."""
        validator = UUIDValidator()
        sql = "INSERT INTO users (id, parent_id) VALUES ('01442fe1-00c7-0000-0000-000000000001', '01442fe2-00c7-0000-0000-000000000002');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 2
        assert uuids[0] == "01442fe1-00c7-0000-0000-000000000001"
        assert uuids[1] == "01442fe2-00c7-0000-0000-000000000002"

    def test_handles_multiline_inserts(self):
        """Test handling multiline INSERT statements."""
        validator = UUIDValidator()
        sql = """INSERT INTO users (id, name)
    VALUES ('01442fe1-00c7-0000-0000-000000000001', 'Alice');"""
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 1
        assert uuids[0] == "01442fe1-00c7-0000-0000-000000000001"

    def test_handles_multiple_value_rows(self):
        """Test handling INSERT with multiple value rows."""
        validator = UUIDValidator()
        sql = """INSERT INTO users (id, name) VALUES
    ('01442fe1-00c7-0000-0000-000000000001', 'Alice'),
    ('01442fe2-00c7-0000-0000-000000000002', 'Bob');"""
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 2
        assert uuids[0] == "01442fe1-00c7-0000-0000-000000000001"
        assert uuids[1] == "01442fe2-00c7-0000-0000-000000000002"

    def test_ignores_null_values(self):
        """Test that NULL values are ignored."""
        validator = UUIDValidator()
        sql = "INSERT INTO users (id, name) VALUES (NULL, 'Alice');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 0

    def test_ignores_non_uuid_strings(self):
        """Test that non-UUID strings are not extracted."""
        validator = UUIDValidator()
        sql = "INSERT INTO users (id, name) VALUES ('01442fe1-00c7-0000-0000-000000000001', 'not-a-uuid');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 1
        assert uuids[0] == "01442fe1-00c7-0000-0000-000000000001"

    def test_handles_uppercase_uuids(self):
        """Test extraction of uppercase UUIDs."""
        validator = UUIDValidator()
        sql = "INSERT INTO users (id) VALUES ('01442FE1-00C7-0000-0000-000000000001');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 1
        assert uuids[0] == "01442FE1-00C7-0000-0000-000000000001"

    def test_empty_sql(self):
        """Test handling empty SQL."""
        validator = UUIDValidator()
        uuids = validator.extract_uuid_literals("")

        assert len(uuids) == 0

    def test_sql_without_uuids(self):
        """Test handling SQL without UUIDs."""
        validator = UUIDValidator()
        sql = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
        uuids = validator.extract_uuid_literals(sql)

        assert len(uuids) == 0
