# tests/integration/test_migration_transaction_rollback.py

import pytest

from confiture.core.migrator import Migrator
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration


class TestMigrationTransactionRollback:
    """Test transaction rollback on migration failure"""

    def test_partial_migration_is_rolled_back(self, test_db_connection):
        """Failed migration should rollback ALL changes, not partial"""

        class PartialFailureMigration(Migration):
            version = "001"
            name = "test_rollback"

            def up(self):
                # First statement succeeds
                self.execute("CREATE TABLE test_table1 (id INT)")

                # Second statement succeeds
                self.execute("CREATE TABLE test_table2 (id INT)")

                # Third statement FAILS
                self.execute("CREATE TABLE invalid syntax")

            def down(self):
                self.execute("DROP TABLE IF EXISTS test_table1")
                self.execute("DROP TABLE IF EXISTS test_table2")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migration = PartialFailureMigration(connection=test_db_connection)

        # Apply migration through migrator (should fail)
        with pytest.raises(MigrationError):
            migrator.apply(migration)

        # Verify NO tables were created (transaction rolled back)
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name IN ('test_table1', 'test_table2')
            """)
            count = cursor.fetchone()[0]

        # Should be 0 (all rolled back)
        assert count == 0, "Partial migration should be rolled back completely"

    def test_migrator_apply_rolls_back_on_failure(self, test_db_connection):
        """Migrator.apply() should rollback both migration and tracking record"""

        class FailingMigration(Migration):
            version = "002"
            name = "test_migrator_rollback"

            def up(self):
                self.execute("CREATE TABLE will_fail (id INT)")
                self.execute("INVALID SQL HERE")

            def down(self):
                pass

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migration = FailingMigration(connection=test_db_connection)

        # Apply migration (should fail)
        with pytest.raises(MigrationError):
            migrator.apply(migration)

        # Verify table was NOT created
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'will_fail'
                )
            """)
            table_exists = cursor.fetchone()[0]

        assert not table_exists, "Failed migration table should not exist"

        # Verify migration was NOT recorded
        assert not migrator._is_applied("002"), "Failed migration should not be recorded"

    def test_connection_state_after_failed_migration(self, clean_test_db):
        """Connection should be usable after failed migration"""

        class FirstFailingMigration(Migration):
            version = "003"
            name = "first_fail"

            def up(self):
                self.execute("INVALID SQL")

            def down(self):
                pass

        class SuccessfulMigration(Migration):
            version = "004"
            name = "second_success"

            def up(self):
                self.execute("CREATE TABLE successful_table (id INT)")

            def down(self):
                self.execute("DROP TABLE successful_table")

        migrator = Migrator(connection=clean_test_db)
        migrator.initialize()

        # First migration fails
        migration1 = FirstFailingMigration(connection=clean_test_db)
        with pytest.raises(MigrationError):
            migrator.apply(migration1)

        # Connection should still be usable
        migration2 = SuccessfulMigration(connection=clean_test_db)
        migrator.apply(migration2)  # Should succeed

        # Verify only second migration was applied
        assert not migrator._is_applied("003")
        assert migrator._is_applied("004")
