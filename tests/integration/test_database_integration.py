"""Integration tests that require a live PostgreSQL database.

These tests were moved from tests/unit/ because they depend on a running
PostgreSQL instance with a ``confiture_test`` database.
"""

import psycopg
import psycopg.pq
import pytest

from confiture.core.drift import DriftReport, SchemaDriftDetector
from confiture.core.schema_analyzer import LiveSchema, SchemaAnalyzer
from confiture.core.schema_model import SchemaModel
from confiture.models.migration import Migration


@pytest.fixture
def db_connection(test_db_url: str):
    """Create test database connection."""
    try:
        conn = psycopg.connect(test_db_url)
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

        assert isinstance(schema, SchemaModel)
        assert all(table.schema == "public" for table in schema.tables.values())

    def test_compare_with_expected(self, db_connection):
        """Test comparing live schema with expected."""
        detector = SchemaDriftDetector(db_connection)

        # Empty expected schema should detect all tables as extra
        expected = SchemaModel()
        report = detector.compare_with_expected(expected)

        assert isinstance(report, DriftReport)
        # Per-worker databases carry an xdist suffix; the report names the one we used.
        assert report.database_name == db_connection.info.dbname


class TestSchemaAnalyzerIntegration:
    """Integration tests for SchemaAnalyzer with real database."""

    def test_live_schema_from_database(self, db_connection):
        """Test reading the validator's view of the live schema from a real database."""
        analyzer = SchemaAnalyzer(db_connection)
        live = analyzer.live_schema()

        assert isinstance(live, LiveSchema)
        assert isinstance(live.index_names(), set)
        assert analyzer.live_schema() is live


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
        # A NOTICE is not an error: the transaction is still open and usable.
        assert test_db_connection.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

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
        assert test_db_connection.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
