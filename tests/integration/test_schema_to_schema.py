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

    @pytest.mark.skip(reason="Will implement in GREEN phase")
    def test_migrate_table_with_column_mapping(self, test_db_connection):
        """Should migrate data with column rename.

        This test will be enabled in Milestone 3.2.
        """
        pass

    @pytest.mark.skip(reason="Will implement in Milestone 3.3")
    def test_copy_strategy_for_large_table(self, test_db_connection):
        """COPY strategy should be faster for large tables.

        This test will be enabled in Milestone 3.3.
        """
        pass
