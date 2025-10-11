"""Integration tests for Migrator class.

These tests require a running PostgreSQL database.
"""

from confiture.core.migrator import Migrator
from confiture.models.migration import Migration


class TestMigratorIntegration:
    """Integration tests for migration execution."""

    def test_migrator_creates_tracking_table(self, test_db_connection):
        """Migrator should create confiture_migrations table if not exists."""
        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Verify table exists
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename = 'confiture_migrations'
                )
            """)
            exists = cursor.fetchone()[0]
            assert exists is True

    def test_apply_migration(self, test_db_connection):
        """Migrator should apply migration and track it."""

        class TestMigration(Migration):
            version = "001"
            name = "create_test_table"

            def up(self):
                self.execute("""
                    CREATE TABLE test_migration_table (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                """)

            def down(self):
                self.execute("DROP TABLE test_migration_table")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migration = TestMigration(connection=test_db_connection)
        migrator.apply(migration)

        # Verify migration was tracked
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT version, name
                FROM confiture_migrations
                WHERE version = '001'
            """)
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == "001"
            assert result[1] == "create_test_table"

        # Verify table was created
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename = 'test_migration_table'
                )
            """)
            exists = cursor.fetchone()[0]
            assert exists is True

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE test_migration_table")
            cursor.execute("DELETE FROM confiture_migrations WHERE version = '001'")
        test_db_connection.commit()

    def test_apply_migration_records_execution_time(self, test_db_connection):
        """Apply should record migration execution time."""

        class SlowMigration(Migration):
            version = "002"
            name = "slow_migration"

            def up(self):
                self.execute("SELECT pg_sleep(0.1)")  # Sleep 100ms

            def down(self):
                pass

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migration = SlowMigration(connection=test_db_connection)
        migrator.apply(migration)

        # Verify execution time was recorded
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT execution_time_ms
                FROM confiture_migrations
                WHERE version = '002'
            """)
            execution_time = cursor.fetchone()[0]
            assert execution_time is not None
            assert execution_time >= 100  # At least 100ms

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM confiture_migrations WHERE version = '002'")
        test_db_connection.commit()

    def test_rollback_migration(self, test_db_connection):
        """Migrator should rollback migration."""

        class ReversibleMigration(Migration):
            version = "003"
            name = "reversible_migration"

            def up(self):
                self.execute("""
                    CREATE TABLE reversible_test (
                        id SERIAL PRIMARY KEY
                    )
                """)

            def down(self):
                self.execute("DROP TABLE reversible_test")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migration = ReversibleMigration(connection=test_db_connection)

        # Apply migration
        migrator.apply(migration)

        # Verify table exists
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = 'reversible_test'
                )
            """)
            assert cursor.fetchone()[0] is True

        # Rollback migration
        migrator.rollback(migration)

        # Verify table dropped
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = 'reversible_test'
                )
            """)
            assert cursor.fetchone()[0] is False

        # Verify migration removed from tracking
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM confiture_migrations
                WHERE version = '003'
            """)
            count = cursor.fetchone()[0]
            assert count == 0
