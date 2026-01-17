"""Tests for schema drift detection."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.drift import (
    DriftItem,
    DriftReport,
    DriftSeverity,
    DriftType,
    SchemaDriftDetector,
)
from confiture.core.schema_analyzer import SchemaInfo


class TestDriftItem:
    """Tests for DriftItem dataclass."""

    def test_drift_item_creation(self):
        """Test creating a drift item."""
        item = DriftItem(
            drift_type=DriftType.MISSING_TABLE,
            severity=DriftSeverity.CRITICAL,
            object_name="users",
            expected="users",
            actual=None,
            message="Table 'users' is missing",
        )
        assert item.drift_type == DriftType.MISSING_TABLE
        assert item.severity == DriftSeverity.CRITICAL
        assert item.object_name == "users"
        assert "users" in str(item)

    def test_drift_item_to_dict(self):
        """Test converting drift item to dictionary."""
        item = DriftItem(
            drift_type=DriftType.EXTRA_COLUMN,
            severity=DriftSeverity.WARNING,
            object_name="users.email",
            message="Extra column",
        )
        result = item.to_dict()
        assert result["type"] == "extra_column"
        assert result["severity"] == "warning"
        assert result["object"] == "users.email"


class TestDriftReport:
    """Tests for DriftReport dataclass."""

    def test_empty_report_no_drift(self):
        """Test empty report has no drift."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
        )
        assert not report.has_drift
        assert not report.has_critical_drift
        assert report.critical_count == 0
        assert report.warning_count == 0

    def test_report_with_critical_drift(self):
        """Test report with critical drift."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
            drift_items=[
                DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    severity=DriftSeverity.CRITICAL,
                    object_name="users",
                    message="Missing table",
                )
            ],
        )
        assert report.has_drift
        assert report.has_critical_drift
        assert report.critical_count == 1
        assert report.warning_count == 0

    def test_report_with_warning_only(self):
        """Test report with warning but no critical."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
            drift_items=[
                DriftItem(
                    drift_type=DriftType.EXTRA_TABLE,
                    severity=DriftSeverity.WARNING,
                    object_name="temp",
                    message="Extra table",
                )
            ],
        )
        assert report.has_drift
        assert not report.has_critical_drift
        assert report.warning_count == 1

    def test_report_to_dict(self):
        """Test report to dictionary conversion."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="file:schema.sql",
            tables_checked=5,
            columns_checked=20,
            detection_time_ms=100,
        )
        result = report.to_dict()
        assert result["database_name"] == "test_db"
        assert result["expected_schema_source"] == "file:schema.sql"
        assert result["has_drift"] is False
        assert result["tables_checked"] == 5


class TestSchemaDriftDetector:
    """Tests for SchemaDriftDetector."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        # Mock database name query
        cursor.fetchone.return_value = ("test_db",)
        cursor.fetchall.return_value = []
        return conn, cursor

    def test_no_drift_identical_schemas(self, mock_connection):
        """Test no drift for identical schemas."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={"users": {"id": {"type": "integer", "nullable": False}}}
        )
        actual = SchemaInfo(
            tables={"users": {"id": {"type": "integer", "nullable": False}}}
        )

        report = detector.compare_schemas(expected, actual)

        assert not report.has_drift
        assert report.tables_checked == 1

    def test_missing_table_detected(self, mock_connection):
        """Test missing table is detected as critical."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={
                "users": {"id": {"type": "integer"}},
                "orders": {"id": {"type": "integer"}},
            }
        )
        actual = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})

        report = detector.compare_schemas(expected, actual)

        assert report.has_drift
        assert report.has_critical_drift
        assert report.critical_count == 1

        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_TABLE]
        assert len(missing) == 1
        assert missing[0].object_name == "orders"

    def test_extra_table_detected(self, mock_connection):
        """Test extra table is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})
        actual = SchemaInfo(
            tables={
                "users": {"id": {"type": "integer"}},
                "temp_data": {"id": {"type": "integer"}},
            }
        )

        report = detector.compare_schemas(expected, actual)

        assert report.has_drift
        assert not report.has_critical_drift
        assert report.warning_count == 1

        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_TABLE]
        assert len(extra) == 1
        assert extra[0].object_name == "temp_data"

    def test_missing_column_detected(self, mock_connection):
        """Test missing column is detected as critical."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}, "email": {"type": "text"}}}
        )
        actual = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})

        report = detector.compare_schemas(expected, actual)

        assert report.has_critical_drift
        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_COLUMN]
        assert len(missing) == 1
        assert missing[0].object_name == "users.email"

    def test_extra_column_detected(self, mock_connection):
        """Test extra column is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})
        actual = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}, "legacy_field": {"type": "text"}}}
        )

        report = detector.compare_schemas(expected, actual)

        assert not report.has_critical_drift
        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_COLUMN]
        assert len(extra) == 1
        assert extra[0].object_name == "users.legacy_field"

    def test_type_mismatch_detected(self, mock_connection):
        """Test column type mismatch is detected."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})
        actual = SchemaInfo(tables={"users": {"id": {"type": "bigint"}}})

        report = detector.compare_schemas(expected, actual)

        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.TYPE_MISMATCH]
        assert len(mismatch) == 1
        assert mismatch[0].severity == DriftSeverity.WARNING

    def test_type_aliases_compatible(self, mock_connection):
        """Test compatible type aliases don't trigger mismatch."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})
        actual = SchemaInfo(tables={"users": {"id": {"type": "int4"}}})

        report = detector.compare_schemas(expected, actual)

        # integer and int4 are compatible
        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.TYPE_MISMATCH]
        assert len(mismatch) == 0

    def test_nullable_mismatch_detected(self, mock_connection):
        """Test nullable mismatch is detected."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={"users": {"id": {"type": "integer", "nullable": False}}}
        )
        actual = SchemaInfo(
            tables={"users": {"id": {"type": "integer", "nullable": True}}}
        )

        report = detector.compare_schemas(expected, actual)

        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.NULLABLE_MISMATCH]
        assert len(mismatch) == 1

    def test_missing_index_detected(self, mock_connection):
        """Test missing index is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}}},
            indexes={"users": ["idx_users_email"]},
        )
        actual = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}}},
            indexes={"users": []},
        )

        report = detector.compare_schemas(expected, actual)

        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_INDEX]
        assert len(missing) == 1
        assert "idx_users_email" in missing[0].object_name

    def test_extra_index_detected(self, mock_connection):
        """Test extra index is detected as info."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}}},
            indexes={"users": []},
        )
        actual = SchemaInfo(
            tables={"users": {"id": {"type": "integer"}}},
            indexes={"users": ["idx_users_temp"]},
        )

        report = detector.compare_schemas(expected, actual)

        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_INDEX]
        assert len(extra) == 1
        assert extra[0].severity == DriftSeverity.INFO

    def test_ignore_tables(self, mock_connection):
        """Test ignored tables are not reported."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn, ignore_tables=["temp_data", "cache"])

        expected = SchemaInfo(tables={"users": {"id": {"type": "integer"}}})
        actual = SchemaInfo(
            tables={
                "users": {"id": {"type": "integer"}},
                "temp_data": {"data": {"type": "jsonb"}},
                "cache": {"key": {"type": "text"}},
            }
        )

        report = detector.compare_schemas(expected, actual)

        # temp_data and cache should be ignored
        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_TABLE]
        assert len(extra) == 0

    def test_system_tables_ignored(self, mock_connection):
        """Test Confiture system tables are always ignored."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaInfo(tables={})
        actual = SchemaInfo(
            tables={
                "confiture_migrations": {"id": {"type": "integer"}},
                "confiture_version": {"version": {"type": "text"}},
            }
        )

        report = detector.compare_schemas(expected, actual)

        # System tables should be ignored
        assert not report.has_drift

    def test_parse_schema_from_sql(self, mock_connection):
        """Test parsing schema from SQL DDL."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            name TEXT
        );

        CREATE INDEX idx_users_email ON users (email);

        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id)
        );
        """

        info = detector._parse_schema_from_sql(sql)

        assert "users" in info.tables
        assert "orders" in info.tables
        assert "id" in info.tables["users"]
        assert "email" in info.tables["users"]
        assert "users" in info.indexes
        assert "idx_users_email" in info.indexes["users"]

    def test_extract_columns_from_create(self, mock_connection):
        """Test extracting columns from CREATE TABLE."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        create_stmt = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """

        columns = detector._extract_columns_from_create(create_stmt)

        assert "id" in columns
        assert "email" in columns
        assert columns["email"]["nullable"] is False
        assert "name" in columns
        assert columns["name"]["nullable"] is True

    def test_types_compatible(self, mock_connection):
        """Test type compatibility checking."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        # Compatible pairs
        assert detector._types_compatible("integer", "int4")
        assert detector._types_compatible("bigint", "int8")
        assert detector._types_compatible("boolean", "bool")
        assert detector._types_compatible("character varying", "varchar")
        assert detector._types_compatible("timestamp with time zone", "timestamptz")

        # Incompatible pairs
        assert not detector._types_compatible("integer", "text")
        assert not detector._types_compatible("boolean", "integer")


class TestDriftDetectorIntegration:
    """Integration tests for drift detection with real database."""

    @pytest.fixture
    def db_connection(self):
        """Create test database connection if available."""
        try:
            import psycopg
            conn = psycopg.connect("postgresql://localhost/confiture_test")
            yield conn
            conn.close()
        except Exception:
            pytest.skip("Test database not available")

    def test_get_live_schema(self, db_connection):
        """Test getting live schema from database."""
        detector = SchemaDriftDetector(db_connection)
        schema = detector.get_live_schema()

        assert isinstance(schema, SchemaInfo)
        assert isinstance(schema.tables, dict)

    def test_compare_with_expected(self, db_connection):
        """Test comparing live schema with expected."""
        detector = SchemaDriftDetector(db_connection)

        # Empty expected schema should detect all tables as extra
        expected = SchemaInfo(tables={})
        report = detector.compare_with_expected(expected)

        assert isinstance(report, DriftReport)
        assert report.database_name == "confiture_test"
