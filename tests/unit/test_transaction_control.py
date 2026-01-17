"""Unit tests for migration transaction control (Phase 1C).

Tests for:
- transactional attribute on Migration class
- Transactional vs non-transactional apply()
- Transactional vs non-transactional rollback()
- Mixed mode warning
"""

from unittest.mock import MagicMock

import pytest

from confiture.core.migrator import Migrator
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration


class TransactionalMigration(Migration):
    """Test migration that runs in transaction (default)."""

    version = "001"
    name = "transactional_test"
    transactional = True  # Default, explicit for clarity

    def up(self):
        self.execute("CREATE TABLE test_trans (id INT)")

    def down(self):
        self.execute("DROP TABLE test_trans")


class NonTransactionalMigration(Migration):
    """Test migration that runs outside transaction (for CREATE INDEX CONCURRENTLY)."""

    version = "002"
    name = "non_transactional_test"
    transactional = False

    def up(self):
        self.execute("CREATE INDEX CONCURRENTLY idx_test ON test_trans(id)")

    def down(self):
        self.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_test")


class TestMigrationTransactionalAttribute:
    """Test the transactional attribute on Migration class."""

    def test_migration_default_transactional(self):
        """Test that migrations default to transactional=True."""
        mock_conn = MagicMock()
        migration = TransactionalMigration(connection=mock_conn)
        assert migration.transactional is True

    def test_migration_explicit_non_transactional(self):
        """Test explicitly non-transactional migration."""
        mock_conn = MagicMock()
        migration = NonTransactionalMigration(connection=mock_conn)
        assert migration.transactional is False

    def test_migration_class_attribute(self):
        """Test transactional is a class attribute."""
        assert TransactionalMigration.transactional is True
        assert NonTransactionalMigration.transactional is False


class TestTransactionalApply:
    """Test apply() for transactional migrations."""

    def test_apply_transactional_uses_savepoint(self):
        """Test that transactional apply creates and releases savepoint."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Migration not applied yet
        mock_cursor.fetchone.return_value = (0,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = True

        migrator.apply(mock_migration)

        # Should create savepoint and release it
        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("SAVEPOINT" in str(c) for c in calls)
        assert any("RELEASE SAVEPOINT" in str(c) for c in calls)

    def test_apply_transactional_commits(self):
        """Test that transactional apply commits transaction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = True

        migrator.apply(mock_migration)

        mock_conn.commit.assert_called()

    def test_apply_transactional_rollback_on_failure(self):
        """Test that transactional apply rolls back on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = True
        mock_migration.up.side_effect = Exception("SQL error")

        with pytest.raises(MigrationError):
            migrator.apply(mock_migration)

        # Should rollback to savepoint
        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("ROLLBACK TO SAVEPOINT" in str(c) for c in calls)


class TestNonTransactionalApply:
    """Test apply() for non-transactional migrations."""

    def test_apply_non_transactional_sets_autocommit(self):
        """Test that non-transactional apply sets autocommit mode."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False

        migrator.apply(mock_migration)

        # Should have set autocommit = True at some point
        # and restored it to False
        assert mock_conn.autocommit is False  # Restored

    def test_apply_non_transactional_no_savepoint(self):
        """Test that non-transactional apply doesn't use savepoints."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False

        migrator.apply(mock_migration)

        # Should NOT create savepoint
        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert not any("SAVEPOINT" in str(c) for c in calls)

    def test_apply_non_transactional_commits_pending(self):
        """Test that non-transactional apply commits pending transaction first."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False

        migrator.apply(mock_migration)

        # First call should be to commit pending transaction
        assert mock_conn.commit.called

    def test_apply_non_transactional_failure_no_rollback(self):
        """Test that non-transactional apply doesn't auto-rollback on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False
        mock_migration.up.side_effect = Exception("CREATE INDEX failed")

        with pytest.raises(MigrationError, match="Manual cleanup"):
            migrator.apply(mock_migration)

        # Should NOT rollback (no transaction to rollback)
        mock_conn.rollback.assert_not_called()

    def test_apply_non_transactional_restores_autocommit(self):
        """Test that autocommit is restored even on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False
        mock_migration.up.side_effect = Exception("Boom")

        with pytest.raises(MigrationError):
            migrator.apply(mock_migration)

        # Autocommit should be restored to original value
        assert mock_conn.autocommit is False


class TestTransactionalRollback:
    """Test rollback() for transactional migrations."""

    def test_rollback_transactional_commits(self):
        """Test that transactional rollback commits transaction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)  # Migration is applied

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = True

        migrator.rollback(mock_migration)

        mock_conn.commit.assert_called()

    def test_rollback_transactional_on_failure_rolls_back(self):
        """Test that transactional rollback rolls back on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = True
        mock_migration.down.side_effect = Exception("Rollback failed")

        with pytest.raises(MigrationError):
            migrator.rollback(mock_migration)

        mock_conn.rollback.assert_called()


class TestNonTransactionalRollback:
    """Test rollback() for non-transactional migrations."""

    def test_rollback_non_transactional_sets_autocommit(self):
        """Test that non-transactional rollback sets autocommit mode."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False

        migrator.rollback(mock_migration)

        # Should restore autocommit
        assert mock_conn.autocommit is False

    def test_rollback_non_transactional_failure_no_auto_rollback(self):
        """Test non-transactional rollback doesn't auto-rollback on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False
        mock_migration.down.side_effect = Exception("DROP INDEX failed")

        with pytest.raises(MigrationError, match="Manual cleanup"):
            migrator.rollback(mock_migration)

        # No rollback for non-transactional
        mock_conn.rollback.assert_not_called()

    def test_rollback_non_transactional_restores_autocommit_on_failure(self):
        """Test autocommit is restored even on rollback failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.autocommit = False

        migrator = Migrator(connection=mock_conn)

        mock_migration = MagicMock(spec=Migration)
        mock_migration.version = "001"
        mock_migration.name = "test"
        mock_migration.transactional = False
        mock_migration.down.side_effect = Exception("Boom")

        with pytest.raises(MigrationError):
            migrator.rollback(mock_migration)

        assert mock_conn.autocommit is False


class TestMixedModeWarning:
    """Test warning for mixed transactional modes in batch."""

    def test_warn_mixed_transactional_modes(self, tmp_path, caplog):
        """Test warning when batch has mixed transactional modes."""
        import logging

        # Create migration files
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Transactional migration
        (migrations_dir / "001_trans.py").write_text('''
from confiture.models.migration import Migration

class CreateTable(Migration):
    version = "001"
    name = "trans"
    transactional = True

    def up(self): pass
    def down(self): pass
''')

        # Non-transactional migration
        (migrations_dir / "002_non_trans.py").write_text('''
from confiture.models.migration import Migration

class CreateIndex(Migration):
    version = "002"
    name = "non_trans"
    transactional = False

    def up(self): pass
    def down(self): pass
''')

        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        files = migrator.find_migration_files(migrations_dir)

        with caplog.at_level(logging.WARNING, logger="confiture.core.migrator"):
            migrator._warn_mixed_transactional_modes(files)

        assert "both transactional and non-transactional" in caplog.text
        assert "002_non_trans.py" in caplog.text

    def test_no_warning_for_single_migration(self, tmp_path, caplog):
        """Test no warning for single migration."""
        import logging

        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        (migrations_dir / "001_single.py").write_text('''
from confiture.models.migration import Migration

class Single(Migration):
    version = "001"
    name = "single"
    transactional = True

    def up(self): pass
    def down(self): pass
''')

        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        files = migrator.find_migration_files(migrations_dir)

        with caplog.at_level(logging.WARNING):
            migrator._warn_mixed_transactional_modes(files)

        assert "both transactional and non-transactional" not in caplog.text

    def test_no_warning_for_all_transactional(self, tmp_path, caplog):
        """Test no warning when all migrations are transactional."""
        import logging

        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        for i in range(3):
            (migrations_dir / f"00{i}_trans_{i}.py").write_text(f'''
from confiture.models.migration import Migration

class Trans{i}(Migration):
    version = "00{i}"
    name = "trans_{i}"
    transactional = True

    def up(self): pass
    def down(self): pass
''')

        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        files = migrator.find_migration_files(migrations_dir)

        with caplog.at_level(logging.WARNING):
            migrator._warn_mixed_transactional_modes(files)

        assert "both transactional and non-transactional" not in caplog.text

    def test_no_warning_for_all_non_transactional(self, tmp_path, caplog):
        """Test no warning when all migrations are non-transactional."""
        import logging

        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        for i in range(2):
            (migrations_dir / f"00{i}_non_trans_{i}.py").write_text(f'''
from confiture.models.migration import Migration

class NonTrans{i}(Migration):
    version = "00{i}"
    name = "non_trans_{i}"
    transactional = False

    def up(self): pass
    def down(self): pass
''')

        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        files = migrator.find_migration_files(migrations_dir)

        with caplog.at_level(logging.WARNING):
            migrator._warn_mixed_transactional_modes(files)

        assert "both transactional and non-transactional" not in caplog.text

    def test_no_warning_for_empty_list(self, caplog):
        """Test no warning for empty migration list."""
        import logging

        mock_conn = MagicMock()
        migrator = Migrator(connection=mock_conn)

        with caplog.at_level(logging.WARNING):
            migrator._warn_mixed_transactional_modes([])

        assert "both transactional and non-transactional" not in caplog.text


class TestConcurrentIndexMigrationPattern:
    """Test the CREATE INDEX CONCURRENTLY pattern."""

    def test_concurrent_index_migration_pattern(self):
        """Test that CREATE INDEX CONCURRENTLY migration is non-transactional."""

        class AddSearchIndex(Migration):
            version = "015"
            name = "add_search_index"
            transactional = False  # Required for CONCURRENTLY

            def up(self):
                self.execute(
                    "CREATE INDEX CONCURRENTLY idx_search ON products(name)"
                )

            def down(self):
                self.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_search")

        mock_conn = MagicMock()
        migration = AddSearchIndex(connection=mock_conn)

        assert migration.transactional is False
        assert migration.version == "015"
        assert migration.name == "add_search_index"
