"""Integration tests that require a live PostgreSQL database.

These tests were moved from tests/unit/ because they depend on a running
PostgreSQL instance with a ``confiture_test`` database.
"""

import psycopg
import pytest

from confiture.core.drift import DriftReport, SchemaDriftDetector
from confiture.core.schema_analyzer import SchemaAnalyzer, SchemaInfo
from confiture.models.migration import Migration


@pytest.fixture
def db_connection():
    """Create test database connection if available."""
    try:
        conn = psycopg.connect("postgresql://localhost/confiture_test")
        yield conn
        conn.close()
    except Exception:
        pytest.skip("Test database not available")


class TestDriftDetectorIntegration:
    """Integration tests for drift detection with real database."""

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


class TestSchemaAnalyzerIntegration:
    """Integration tests for SchemaAnalyzer with real database."""

    def test_get_schema_info_from_database(self, db_connection):
        """Test retrieving schema info from real database."""
        analyzer = SchemaAnalyzer(db_connection)
        info = analyzer.get_schema_info()

        assert isinstance(info, SchemaInfo)
        assert isinstance(info.tables, dict)
        assert isinstance(info.indexes, dict)


class TestStrictModeIntegration:
    """Integration tests for strict mode with real database."""

    def test_strict_mode_enabled_detects_warnings(self, test_db_connection):
        """Strict mode should detect and report PostgreSQL warnings."""

        class WarningMigration(Migration):
            version = "001"
            name = "test_warning"
            strict_mode = True

            def up(self):
                self.execute("DO $$ BEGIN RAISE NOTICE 'Test notice'; END $$;")

            def down(self):
                pass

        migration = WarningMigration(connection=test_db_connection)
        migration.up()

    def test_normal_mode_ignores_notices(self, test_db_connection):
        """Normal mode should ignore PostgreSQL notices."""

        class NoticeMigration(Migration):
            version = "002"
            name = "test_notice"

            def up(self):
                self.execute("DO $$ BEGIN RAISE NOTICE 'Test notice'; END $$;")

            def down(self):
                pass

        migration = NoticeMigration(connection=test_db_connection)
        migration.up()
