"""Integration tests for SchemaToSchemaMigrator.

These tests require a running PostgreSQL database and test the
Foreign Data Wrapper (FDW) based schema-to-schema migration strategy.

Phase 3, Milestone 3.1: FDW Strategy Setup
"""

import pytest
from confiture.core.schema_to_schema import SchemaToSchemaMigrator


class TestSchemaToSchemaFDW:
    """Integration tests for FDW-based schema-to-schema migration."""

    def test_setup_fdw_connection(self, test_db_connection):
        """Should setup FDW infrastructure (extension, server, user mapping).

        RED Phase Test - This test should FAIL initially.

        The test verifies that SchemaToSchemaMigrator can:
        1. Create postgres_fdw extension
        2. Create a foreign server pointing to source database
        3. Create user mapping for authentication
        4. Create the foreign schema (without importing tables for this test)

        Note: We don't test IMPORT FOREIGN SCHEMA here because it requires
        connecting back to the same database which causes timeouts. That will
        be tested in E2E tests with actual separate databases.
        """
        # Initialize migrator
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
            foreign_schema_name="old_schema"
        )

        # Setup FDW (without importing schema)
        migrator.setup_fdw(skip_import=True)

        # Verify postgres_fdw extension exists
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'postgres_fdw'
                )
            """)
            fdw_exists = cursor.fetchone()[0]
            assert fdw_exists is True, "postgres_fdw extension should be installed"

        # Verify foreign server exists
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM pg_foreign_server
                WHERE srvname = 'confiture_source_server'
            """)
            server_count = cursor.fetchone()[0]
            assert server_count == 1, "Foreign server should be created"

        # Verify user mapping exists
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM pg_user_mappings
                WHERE srvname = 'confiture_source_server'
            """)
            mapping_count = cursor.fetchone()[0]
            assert mapping_count == 1, "User mapping should be created"

        # Verify foreign schema was created
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'old_schema'
                )
            """)
            schema_exists = cursor.fetchone()[0]
            assert schema_exists is True, "Foreign schema should be created"

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS old_schema CASCADE")
            cursor.execute("DROP USER MAPPING IF EXISTS FOR CURRENT_USER SERVER confiture_source_server")
            cursor.execute("DROP SERVER IF EXISTS confiture_source_server CASCADE")
        test_db_connection.commit()

    def test_migrate_table_with_column_mapping(self, test_db_connection):
        """Should migrate data with column mapping (RED → GREEN test).

        Milestone 3.2: Data Migration with Column Mapping

        Tests that SchemaToSchemaMigrator can:
        1. Migrate data from old table to new table
        2. Apply column name mappings (e.g., full_name → display_name)
        3. Handle NULL values correctly
        4. Verify row counts match

        Note: This test uses a simplified setup without FDW to avoid connection
        issues when testing with same database. The migrate_table() method still
        queries from the foreign_schema which we create manually.
        """
        # Setup: Create old schema with data in foreign schema
        with test_db_connection.cursor() as cursor:
            # Create foreign schema and old table in it
            cursor.execute("CREATE SCHEMA IF NOT EXISTS old_schema")

            cursor.execute("""
                CREATE TABLE old_schema.old_users (
                    id SERIAL PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT UNIQUE
                )
            """)

            # Insert test data
            cursor.execute("""
                INSERT INTO old_schema.old_users (full_name, email) VALUES
                    ('John Doe', 'john@example.com'),
                    ('Jane Smith', 'jane@example.com'),
                    ('Bob Wilson', NULL)
            """)

            # Create new table with renamed columns in public schema
            cursor.execute("""
                CREATE TABLE new_users (
                    id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT UNIQUE
                )
            """)
        test_db_connection.commit()

        # Create migrator (no FDW needed for this simplified test)
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
            foreign_schema_name="old_schema"
        )

        # Execute migration with column mapping
        column_mapping = {
            "id": "id",
            "full_name": "display_name",  # Rename
            "email": "email",
        }

        rows_migrated = migrator.migrate_table(
            source_table="old_users",
            target_table="new_users",
            column_mapping=column_mapping
        )

        # Verify return value
        assert rows_migrated == 3, f"Should return 3 rows migrated, got {rows_migrated}"

        # Verify data migrated correctly
        with test_db_connection.cursor() as cursor:
            # Check row count matches
            cursor.execute("SELECT COUNT(*) FROM old_schema.old_users")
            old_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM new_users")
            new_count = cursor.fetchone()[0]

            assert new_count == old_count, f"Row counts should match: {new_count} != {old_count}"
            assert new_count == 3, "Should have migrated 3 rows"

            # Verify column mapping worked
            cursor.execute("SELECT display_name, email FROM new_users ORDER BY id")
            rows = cursor.fetchall()

            assert rows[0] == ("John Doe", "john@example.com")
            assert rows[1] == ("Jane Smith", "jane@example.com")
            assert rows[2] == ("Bob Wilson", None)

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS old_schema.old_users CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS old_schema CASCADE")
            cursor.execute("DROP TABLE IF EXISTS new_users CASCADE")
        test_db_connection.commit()

    @pytest.mark.skip(reason="Will implement in Milestone 3.3")
    def test_copy_strategy_for_large_table(self, test_db_connection):
        """COPY strategy should be faster for large tables.

        This test will be enabled in Milestone 3.3.
        """
        pass
