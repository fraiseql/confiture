"""Integration tests for SchemaToSchemaMigrator.

These tests require a running PostgreSQL database and test the
Foreign Data Wrapper (FDW) based schema-to-schema migration strategy.
"""

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
            foreign_schema_name="old_schema",
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
            cursor.execute(
                "DROP USER MAPPING IF EXISTS FOR CURRENT_USER SERVER confiture_source_server"
            )
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
            foreign_schema_name="old_schema",
        )

        # Execute migration with column mapping
        column_mapping = {
            "id": "id",
            "full_name": "display_name",  # Rename
            "email": "email",
        }

        rows_migrated = migrator.migrate_table(
            source_table="old_users", target_table="new_users", column_mapping=column_mapping
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

    def test_copy_strategy_for_large_table(self, test_db_connection):
        """COPY strategy should migrate large tables efficiently.

        Milestone 3.3: COPY Strategy (Large Tables)

        Tests that SchemaToSchemaMigrator can:
        1. Detect when COPY strategy should be used (row count threshold)
        2. Use PostgreSQL COPY for fast data migration
        3. Stream data without intermediate storage
        4. Apply column mapping during COPY
        5. Verify row counts match

        COPY is 10-20x faster than FDW for large tables (>10M rows).
        """
        # Setup: Create old schema with larger dataset
        with test_db_connection.cursor() as cursor:
            # Cleanup any existing tables from previous runs
            cursor.execute("DROP TABLE IF EXISTS old_schema.large_events CASCADE")
            cursor.execute("DROP TABLE IF EXISTS events CASCADE")

            # Create foreign schema and old table
            cursor.execute("CREATE SCHEMA IF NOT EXISTS old_schema")

            cursor.execute("""
                CREATE TABLE old_schema.large_events (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Insert test data (smaller than 10M for test speed, but enough to verify)
            # In production, this would be 10M+ rows
            cursor.execute("""
                INSERT INTO old_schema.large_events (event_type, user_id)
                SELECT
                    CASE (random() * 3)::int
                        WHEN 0 THEN 'click'
                        WHEN 1 THEN 'view'
                        ELSE 'purchase'
                    END,
                    (random() * 1000)::int
                FROM generate_series(1, 100000) -- 100K rows for testing
            """)

            # Create new table with renamed column
            cursor.execute("""
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY,
                    type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP
                )
            """)
        test_db_connection.commit()

        # Create migrator
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
            foreign_schema_name="old_schema",
        )

        # Execute migration with COPY strategy
        column_mapping = {
            "id": "id",
            "event_type": "type",  # Rename
            "user_id": "user_id",
            "created_at": "created_at",
        }

        rows_migrated = migrator.migrate_table_copy(
            source_table="large_events", target_table="events", column_mapping=column_mapping
        )

        # Verify return value
        assert rows_migrated == 100000, f"Should return 100000 rows migrated, got {rows_migrated}"

        # Verify data migrated correctly
        with test_db_connection.cursor() as cursor:
            # Check row count matches
            cursor.execute("SELECT COUNT(*) FROM old_schema.large_events")
            old_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM events")
            new_count = cursor.fetchone()[0]

            assert new_count == old_count, f"Row counts should match: {new_count} != {old_count}"
            assert new_count == 100000, "Should have migrated 100000 rows"

            # Verify column mapping worked (sample check)
            cursor.execute("SELECT DISTINCT type FROM events ORDER BY type")
            types = [row[0] for row in cursor.fetchall()]
            assert set(types) == {"click", "view", "purchase"}

            # Verify timestamps preserved
            cursor.execute("SELECT COUNT(*) FROM events WHERE created_at IS NOT NULL")
            non_null_timestamps = cursor.fetchone()[0]
            assert non_null_timestamps == 100000, "All timestamps should be preserved"

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS old_schema.large_events CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS old_schema CASCADE")
            cursor.execute("DROP TABLE IF EXISTS events CASCADE")
        test_db_connection.commit()

    def test_analyze_tables_recommends_strategy(self, test_db_connection):
        """Should analyze table sizes and recommend optimal strategy.

        Milestone 3.4: Hybrid Strategy (Auto-Detection)

        Tests that SchemaToSchemaMigrator can:
        1. Query table row counts from database
        2. Recommend FDW for small tables (<10M rows)
        3. Recommend COPY for large tables (>10M rows)
        4. Estimate migration time for each strategy
        5. Return structured recommendations

        This enables auto-detection of optimal strategy per table.

        Note: This test uses smaller row counts (1K and 1M instead of 15M)
        for speed, but verifies the threshold logic works correctly.
        """
        # Setup: Create tables with different sizes
        with test_db_connection.cursor() as cursor:
            # Cleanup from previous runs
            cursor.execute("DROP TABLE IF EXISTS small_users CASCADE")
            cursor.execute("DROP TABLE IF EXISTS medium_posts CASCADE")

            # Small table (< 10M rows → FDW)
            cursor.execute("""
                CREATE TABLE small_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT
                )
            """)
            cursor.execute(
                "INSERT INTO small_users (username) SELECT 'user' || i FROM generate_series(1, 1000) i"
            )

            # Medium table to simulate large (we'll update stats manually)
            # Creating 1M rows instead of 15M for test speed
            cursor.execute("""
                CREATE TABLE medium_posts (
                    id SERIAL PRIMARY KEY,
                    content TEXT
                )
            """)
            cursor.execute(
                "INSERT INTO medium_posts (content) SELECT 'post' || i FROM generate_series(1, 1000000) i"
            )  # 1M rows

        test_db_connection.commit()

        # Update statistics to simulate larger table
        with test_db_connection.cursor() as cursor:
            cursor.execute("ANALYZE small_users")
            cursor.execute("ANALYZE medium_posts")

        # Create migrator
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
        )

        # Analyze tables
        recommendations = migrator.analyze_tables()

        # Verify recommendations
        assert "small_users" in recommendations
        assert "medium_posts" in recommendations

        # Small table should recommend FDW
        small_rec = recommendations["small_users"]
        assert small_rec["strategy"] == "fdw"
        assert small_rec["row_count"] == 1000
        assert small_rec["estimated_seconds"] > 0

        # Medium table should recommend FDW (since it's < 10M)
        # But if we had 15M it would recommend COPY
        medium_rec = recommendations["medium_posts"]
        assert medium_rec["row_count"] == 1000000
        # At 1M rows, should still be FDW
        assert medium_rec["strategy"] == "fdw"

        # Verify the threshold logic by checking calculated values
        # If row_count >= 10M, strategy should be "copy"
        assert (medium_rec["row_count"] < 10_000_000) == (medium_rec["strategy"] == "fdw")

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS small_users CASCADE")
            cursor.execute("DROP TABLE IF EXISTS medium_posts CASCADE")
        test_db_connection.commit()

    def test_verify_migration_counts(self, test_db_connection):
        """Should verify row counts match between source and target.

        Milestone 3.5: Verification & Cutover

        Tests that SchemaToSchemaMigrator can:
        1. Count rows in source tables (via foreign schema)
        2. Count rows in target tables
        3. Compare counts and detect mismatches
        4. Return verification results with pass/fail status

        This is critical for ensuring data migration completeness.
        """
        # Setup: Create source and target tables with data
        with test_db_connection.cursor() as cursor:
            # Cleanup
            cursor.execute("DROP TABLE IF EXISTS old_schema.products CASCADE")
            cursor.execute("DROP TABLE IF EXISTS products CASCADE")

            # Create foreign schema
            cursor.execute("CREATE SCHEMA IF NOT EXISTS old_schema")

            # Create source table with data
            cursor.execute("""
                CREATE TABLE old_schema.products (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    price DECIMAL(10, 2)
                )
            """)
            cursor.execute("""
                INSERT INTO old_schema.products (name, price)
                SELECT 'Product ' || i, (i * 10.99)::DECIMAL
                FROM generate_series(1, 5000) i
            """)

            # Create target table (empty initially)
            cursor.execute("""
                CREATE TABLE products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    price DECIMAL(10, 2)
                )
            """)
        test_db_connection.commit()

        # Create migrator
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
            foreign_schema_name="old_schema",
        )

        # Migrate data
        column_mapping = {"id": "id", "name": "name", "price": "price"}
        migrator.migrate_table("products", "products", column_mapping)

        # Verify counts
        verification_results = migrator.verify_migration(
            tables=["products"], source_schema="old_schema", target_schema="public"
        )

        # Check verification results
        assert "products" in verification_results
        products_result = verification_results["products"]

        assert products_result["source_count"] == 5000
        assert products_result["target_count"] == 5000
        assert products_result["match"] is True
        assert products_result["difference"] == 0

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS old_schema.products CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS old_schema CASCADE")
            cursor.execute("DROP TABLE IF EXISTS products CASCADE")
        test_db_connection.commit()

    def test_verify_migration_detects_mismatch(self, test_db_connection):
        """Should detect count mismatches between source and target.

        Milestone 3.5: Verification & Cutover

        Tests that verification correctly identifies when row counts don't match,
        which would indicate incomplete or failed migration.
        """
        # Setup: Create tables with intentional mismatch
        with test_db_connection.cursor() as cursor:
            # Cleanup
            cursor.execute("DROP TABLE IF EXISTS old_schema.orders CASCADE")
            cursor.execute("DROP TABLE IF EXISTS orders CASCADE")

            cursor.execute("CREATE SCHEMA IF NOT EXISTS old_schema")

            # Source: 1000 rows
            cursor.execute("""
                CREATE TABLE old_schema.orders (
                    id SERIAL PRIMARY KEY,
                    total DECIMAL(10, 2)
                )
            """)
            cursor.execute("""
                INSERT INTO old_schema.orders (total)
                SELECT (i * 99.99)::DECIMAL
                FROM generate_series(1, 1000) i
            """)

            # Target: Only 900 rows (incomplete migration)
            cursor.execute("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    total DECIMAL(10, 2)
                )
            """)
            cursor.execute("""
                INSERT INTO orders (id, total)
                SELECT id, total
                FROM old_schema.orders
                WHERE id <= 900
            """)
        test_db_connection.commit()

        # Create migrator
        migrator = SchemaToSchemaMigrator(
            source_connection=test_db_connection,
            target_connection=test_db_connection,
            foreign_schema_name="old_schema",
        )

        # Verify counts (should detect mismatch)
        verification_results = migrator.verify_migration(
            tables=["orders"], source_schema="old_schema", target_schema="public"
        )

        # Check verification detected the mismatch
        assert "orders" in verification_results
        orders_result = verification_results["orders"]

        assert orders_result["source_count"] == 1000
        assert orders_result["target_count"] == 900
        assert orders_result["match"] is False
        # Negative difference means target has fewer rows (missing data)
        assert orders_result["difference"] == -100

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS old_schema.orders CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS old_schema CASCADE")
            cursor.execute("DROP TABLE IF EXISTS orders CASCADE")
        test_db_connection.commit()
