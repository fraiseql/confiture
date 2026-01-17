"""Tests for PostgreSQL version detection and feature flags."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.pg_version import (
    PGFeature,
    PGVersionInfo,
    VersionAwareSQL,
    check_version_compatibility,
    detect_version,
    get_recommended_settings,
    parse_version_string,
)


class TestPGFeature:
    """Tests for PGFeature enum."""

    def test_feature_versions(self):
        """Test feature version values."""
        assert PGFeature.GENERATED_COLUMNS.value == 12
        assert PGFeature.VACUUM_PARALLEL.value == 13
        assert PGFeature.MULTIRANGE_TYPES.value == 14
        assert PGFeature.MERGE_STATEMENT.value == 15
        assert PGFeature.JSON_IS_JSON.value == 16
        assert PGFeature.INCREMENTAL_BACKUP.value == 17

    def test_all_features_have_valid_versions(self):
        """Test all features have versions 12-17."""
        for feature in PGFeature:
            assert 12 <= feature.value <= 17, f"{feature.name} has invalid version"


class TestPGVersionInfo:
    """Tests for PGVersionInfo dataclass."""

    def test_version_creation(self):
        """Test creating version info."""
        info = PGVersionInfo(major=15, minor=4, patch=2)
        assert info.major == 15
        assert info.minor == 4
        assert info.patch == 2

    def test_version_with_full_string(self):
        """Test version with full version string."""
        info = PGVersionInfo(
            major=15,
            minor=4,
            full_version="PostgreSQL 15.4 (Ubuntu 15.4-1)",
        )
        assert "PostgreSQL 15.4" in info.full_version

    def test_supports_feature_true(self):
        """Test supports returns True for supported feature."""
        info = PGVersionInfo(major=15, minor=0)
        assert info.supports(PGFeature.MERGE_STATEMENT) is True
        assert info.supports(PGFeature.VACUUM_PARALLEL) is True
        assert info.supports(PGFeature.GENERATED_COLUMNS) is True

    def test_supports_feature_false(self):
        """Test supports returns False for unsupported feature."""
        info = PGVersionInfo(major=14, minor=0)
        assert info.supports(PGFeature.MERGE_STATEMENT) is False
        assert info.supports(PGFeature.JSON_IS_JSON) is False

    def test_is_at_least_major(self):
        """Test is_at_least for major version."""
        info = PGVersionInfo(major=15, minor=4)
        assert info.is_at_least(14) is True
        assert info.is_at_least(15) is True
        assert info.is_at_least(16) is False

    def test_is_at_least_minor(self):
        """Test is_at_least for minor version."""
        info = PGVersionInfo(major=15, minor=4)
        assert info.is_at_least(15, 3) is True
        assert info.is_at_least(15, 4) is True
        assert info.is_at_least(15, 5) is False

    def test_version_tuple(self):
        """Test version_tuple property."""
        info = PGVersionInfo(major=15, minor=4, patch=2)
        assert info.version_tuple == (15, 4, 2)

    def test_str_representation(self):
        """Test string representation."""
        info = PGVersionInfo(major=15, minor=4, patch=2)
        assert str(info) == "15.4.2"


class TestDetectVersion:
    """Tests for detect_version function."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_detect_pg15(self, mock_connection):
        """Test detecting PostgreSQL 15."""
        conn, cursor = mock_connection
        cursor.fetchone.side_effect = [
            ("PostgreSQL 15.4 (Ubuntu 15.4-1)",),
            (150004,),  # 15.0.4
        ]

        info = detect_version(conn)

        assert info.major == 15
        assert info.minor == 0
        assert info.patch == 4
        assert "PostgreSQL 15.4" in info.full_version

    def test_detect_pg12(self, mock_connection):
        """Test detecting PostgreSQL 12."""
        conn, cursor = mock_connection
        cursor.fetchone.side_effect = [
            ("PostgreSQL 12.17",),
            (120017,),
        ]

        info = detect_version(conn)

        assert info.major == 12
        assert info.minor == 0
        assert info.patch == 17

    def test_detect_pg16(self, mock_connection):
        """Test detecting PostgreSQL 16."""
        conn, cursor = mock_connection
        cursor.fetchone.side_effect = [
            ("PostgreSQL 16.1",),
            (160001,),
        ]

        info = detect_version(conn)

        assert info.major == 16
        assert info.minor == 0
        assert info.patch == 1


class TestParseVersionString:
    """Tests for parse_version_string function."""

    def test_parse_full_version(self):
        """Test parsing full version string."""
        info = parse_version_string("PostgreSQL 15.4.2")
        assert info.major == 15
        assert info.minor == 4
        assert info.patch == 2

    def test_parse_simple_version(self):
        """Test parsing simple version."""
        info = parse_version_string("15.4")
        assert info.major == 15
        assert info.minor == 4
        assert info.patch == 0

    def test_parse_version_with_suffix(self):
        """Test parsing version with suffix."""
        info = parse_version_string("PostgreSQL 15.4 (Ubuntu 15.4-1)")
        assert info.major == 15
        assert info.minor == 4

    def test_parse_invalid_version(self):
        """Test parsing invalid version raises error."""
        with pytest.raises(ValueError):
            parse_version_string("not a version")


class TestVersionAwareSQL:
    """Tests for VersionAwareSQL class."""

    def test_reindex_concurrently_pg12(self):
        """Test REINDEX CONCURRENTLY on PG 12+."""
        version = PGVersionInfo(major=12, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.reindex_concurrently("idx_users_email")

        assert "CONCURRENTLY" in result
        assert "idx_users_email" in result

    def test_reindex_concurrently_pg11(self):
        """Test REINDEX CONCURRENTLY fallback on PG 11."""
        version = PGVersionInfo(major=11, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.reindex_concurrently("idx_users_email")

        assert "CONCURRENTLY" not in result
        assert result == "REINDEX INDEX idx_users_email"

    def test_vacuum_parallel_pg13(self):
        """Test VACUUM PARALLEL on PG 13+."""
        version = PGVersionInfo(major=13, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.vacuum_parallel("users", parallel_workers=4)

        assert "PARALLEL 4" in result
        assert "users" in result

    def test_vacuum_parallel_pg12(self):
        """Test VACUUM PARALLEL fallback on PG 12."""
        version = PGVersionInfo(major=12, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.vacuum_parallel("users")

        assert "PARALLEL" not in result
        assert result == "VACUUM users"

    def test_create_index_concurrently(self):
        """Test CREATE INDEX CONCURRENTLY."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.create_index_concurrently(
            "idx_users_email", "users", ["email"]
        )

        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in result
        assert "idx_users_email" in result
        assert "users" in result
        assert "email" in result

    def test_create_index_concurrently_unique(self):
        """Test CREATE UNIQUE INDEX CONCURRENTLY."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.create_index_concurrently(
            "idx_users_email", "users", ["email"], unique=True
        )

        assert "CREATE UNIQUE INDEX CONCURRENTLY" in result

    def test_create_index_concurrently_partial(self):
        """Test CREATE INDEX CONCURRENTLY with WHERE."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.create_index_concurrently(
            "idx_active_users",
            "users",
            ["email"],
            where="active = true",
        )

        assert "WHERE active = true" in result

    def test_create_index_multiple_columns(self):
        """Test CREATE INDEX with multiple columns."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.create_index_concurrently(
            "idx_users_name", "users", ["first_name", "last_name"]
        )

        assert "first_name, last_name" in result

    def test_merge_statement_pg15(self):
        """Test MERGE statement on PG 15+."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.merge_statement(
            target="users",
            source="staging_users s",
            on_condition="users.id = s.id",
            when_matched="UPDATE SET name = s.name",
            when_not_matched="INSERT (id, name) VALUES (s.id, s.name)",
        )

        assert result is not None
        assert "MERGE INTO users" in result
        assert "USING staging_users s" in result
        assert "ON users.id = s.id" in result
        assert "WHEN MATCHED THEN UPDATE SET name = s.name" in result
        assert "WHEN NOT MATCHED THEN INSERT" in result

    def test_merge_statement_pg14(self):
        """Test MERGE statement returns None on PG 14."""
        version = PGVersionInfo(major=14, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.merge_statement(
            target="users",
            source="staging",
            on_condition="users.id = staging.id",
        )

        assert result is None

    def test_add_column_with_default_fast(self):
        """Test ADD COLUMN with DEFAULT."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.add_column_with_default_fast(
            "users", "status", "TEXT", "'active'"
        )

        assert "ALTER TABLE users" in result
        assert "ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'" in result

    def test_unique_nulls_not_distinct_pg15(self):
        """Test UNIQUE NULLS NOT DISTINCT on PG 15+."""
        version = PGVersionInfo(major=15, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.unique_nulls_not_distinct(
            "users", "email", "uq_users_email"
        )

        assert result is not None
        assert "UNIQUE NULLS NOT DISTINCT" in result
        assert "uq_users_email" in result

    def test_unique_nulls_not_distinct_pg14(self):
        """Test UNIQUE NULLS NOT DISTINCT returns None on PG 14."""
        version = PGVersionInfo(major=14, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.unique_nulls_not_distinct("users", "email", "uq")

        assert result is None

    def test_detach_partition_concurrently_pg14(self):
        """Test DETACH PARTITION CONCURRENTLY on PG 14+."""
        version = PGVersionInfo(major=14, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.detach_partition_concurrently("orders", "orders_2024")

        assert "DETACH PARTITION orders_2024 CONCURRENTLY" in result

    def test_detach_partition_concurrently_pg13(self):
        """Test DETACH PARTITION fallback on PG 13."""
        version = PGVersionInfo(major=13, minor=0)
        sql = VersionAwareSQL(version)

        result = sql.detach_partition_concurrently("orders", "orders_2024")

        assert "CONCURRENTLY" not in result
        assert "DETACH PARTITION orders_2024" in result


class TestGetRecommendedSettings:
    """Tests for get_recommended_settings function."""

    def test_base_settings(self):
        """Test base settings for all versions."""
        version = PGVersionInfo(major=12, minor=0)
        settings = get_recommended_settings(version)

        assert "statement_timeout" in settings
        assert "lock_timeout" in settings
        assert "idle_in_transaction_session_timeout" in settings

    def test_pg13_settings(self):
        """Test additional settings for PG 13+."""
        version = PGVersionInfo(major=13, minor=0)
        settings = get_recommended_settings(version)

        assert "hash_mem_multiplier" in settings

    def test_pg14_settings(self):
        """Test additional settings for PG 14+."""
        version = PGVersionInfo(major=14, minor=0)
        settings = get_recommended_settings(version)

        assert "client_connection_check_interval" in settings

    def test_pg15_settings(self):
        """Test additional settings for PG 15+."""
        version = PGVersionInfo(major=15, minor=0)
        settings = get_recommended_settings(version)

        assert "log_min_duration_statement" in settings


class TestCheckVersionCompatibility:
    """Tests for check_version_compatibility function."""

    def test_compatible_version(self):
        """Test compatible version."""
        version = PGVersionInfo(major=15, minor=4)
        is_compatible, error = check_version_compatibility(version)

        assert is_compatible is True
        assert error is None

    def test_compatible_minimum_version(self):
        """Test exactly minimum version is compatible."""
        version = PGVersionInfo(major=12, minor=0)
        is_compatible, error = check_version_compatibility(version)

        assert is_compatible is True
        assert error is None

    def test_incompatible_version(self):
        """Test incompatible version."""
        version = PGVersionInfo(major=11, minor=0)
        is_compatible, error = check_version_compatibility(version)

        assert is_compatible is False
        assert error is not None
        assert "11.0" in error
        assert "12.0" in error

    def test_custom_minimum_version(self):
        """Test custom minimum version."""
        version = PGVersionInfo(major=13, minor=0)
        is_compatible, error = check_version_compatibility(
            version, min_version=(14, 0)
        )

        assert is_compatible is False
        assert "13.0" in error
        assert "14.0" in error

    def test_compatible_with_custom_minimum(self):
        """Test compatible with custom minimum."""
        version = PGVersionInfo(major=15, minor=0)
        is_compatible, error = check_version_compatibility(
            version, min_version=(14, 5)
        )

        assert is_compatible is True
        assert error is None
