"""Edge case tests for Migrator to improve coverage."""

import pytest
import psycopg
from unittest.mock import MagicMock, patch

from confiture.core.migrator import Migrator
from confiture.models.migration import Migration
from confiture.exceptions import MigrationError


class TestMigratorInitializeEdgeCases:
    """Test initialize method edge cases."""

    def test_initialize_with_commit_error(self):
        """Test initialize when commit fails."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate table doesn't exist
        mock_cursor.fetchone.side_effect = [(False,)]

        # Simulate commit failing
        mock_conn.commit.side_effect = psycopg.Error("Commit failed")

        migrator = Migrator(connection=mock_conn)

        with pytest.raises(MigrationError, match="Failed to initialize"):
            migrator.initialize()

        # Should call rollback
        mock_conn.rollback.assert_called_once()

    def test_initialize_is_idempotent(self):
        """Test that initialize can be called multiple times safely."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate table already exists with new structure
        mock_cursor.fetchone.side_effect = [
            (True,),  # Table exists
            (True,),  # Has new structure (pk_migration)
        ]

        migrator = Migrator(connection=mock_conn)
        migrator.initialize()

        # Should not raise error
        mock_conn.commit.assert_called()


class TestMigratorApplyEdgeCases:
    """Test apply method edge cases."""

    def test_apply_already_applied_migration(self):
        """Test applying migration that was already applied."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate migration already applied
        mock_cursor.fetchone.return_value = (1,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test_migration"

        with pytest.raises(MigrationError, match="has already been applied"):
            migrator.apply(mock_migration)

    def test_apply_with_up_failure(self):
        """Test apply when up() method fails."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate migration not applied yet
        mock_cursor.fetchone.return_value = (0,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test_migration"
        mock_migration.up.side_effect = Exception("SQL error")

        with pytest.raises(MigrationError, match="Failed to apply migration"):
            migrator.apply(mock_migration)

        # Should rollback
        mock_conn.rollback.assert_called()


class TestMigratorRollbackEdgeCases:
    """Test rollback method edge cases."""

    def test_rollback_not_applied_migration(self):
        """Test rolling back migration that was never applied."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate migration not applied
        mock_cursor.fetchone.return_value = (0,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test_migration"

        with pytest.raises(MigrationError, match="has not been applied"):
            migrator.rollback(mock_migration)

    def test_rollback_with_down_failure(self):
        """Test rollback when down() method fails."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate migration was applied
        mock_cursor.fetchone.return_value = (1,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test_migration"
        mock_migration.down.side_effect = Exception("SQL error during down")

        with pytest.raises(MigrationError, match="Failed to rollback migration"):
            migrator.rollback(mock_migration)

        # Should rollback transaction
        mock_conn.rollback.assert_called()


class TestMigratorIsApplied:
    """Test _is_applied helper method."""

    def test_is_applied_with_none_result(self):
        """Test _is_applied when query returns None."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate fetchone returning None
        mock_cursor.fetchone.return_value = None

        migrator = Migrator(connection=mock_conn)
        result = migrator._is_applied("001")

        assert result is False


class TestMigratorFindMigrationFiles:
    """Test find_migration_files method."""

    def test_find_migration_files_nonexistent_dir(self, tmp_path):
        """Test finding migrations when directory doesn't exist."""
        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        nonexistent_dir = tmp_path / "nonexistent" / "migrations"

        files = migrator.find_migration_files(migrations_dir=nonexistent_dir)

        assert files == []


class TestMigratorVersionExtraction:
    """Test _version_from_filename helper."""

    def test_version_from_filename_various_formats(self):
        """Test extracting version from different filename formats."""
        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        # Standard format
        assert migrator._version_from_filename("001_create_users.py") == "001"

        # Multiple underscores
        assert (
            migrator._version_from_filename("042_add_user_email_column.py") == "042"
        )

        # Different length version
        assert migrator._version_from_filename("00123_long_version.py") == "00123"
