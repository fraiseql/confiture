"""Unit tests for Issue #64: Handle BEGIN/COMMIT in migration SQL files.

Verifies that FileSQLMigration auto-strips explicit BEGIN;/COMMIT; lines
from .up.sql/.down.sql files before executing them, and emits a warning
when stripping occurs.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.sql_utils import strip_transaction_wrappers
from confiture.models.sql_file_migration import FileSQLMigration

# ---------------------------------------------------------------------------
# strip_transaction_wrappers (shared utility)
# ---------------------------------------------------------------------------


class TestStripTransactionWrappers:
    def test_strips_begin_commit(self):
        sql = "BEGIN;\nALTER TABLE foo ADD COLUMN bar TEXT;\nCOMMIT;\n"
        result = strip_transaction_wrappers(sql)
        assert result == "ALTER TABLE foo ADD COLUMN bar TEXT;\n"

    def test_strips_lowercase(self):
        sql = "begin;\nSELECT 1;\ncommit;\n"
        result = strip_transaction_wrappers(sql)
        assert result == "SELECT 1;\n"

    def test_strips_mixed_case(self):
        sql = "Begin;\nSELECT 1;\nCommit;\n"
        result = strip_transaction_wrappers(sql)
        assert result == "SELECT 1;\n"

    def test_strips_without_semicolon(self):
        sql = "BEGIN\nSELECT 1;\nCOMMIT\n"
        result = strip_transaction_wrappers(sql)
        assert result == "SELECT 1;\n"

    def test_preserves_sql_without_wrappers(self):
        sql = "ALTER TABLE foo ADD COLUMN bar TEXT;\n"
        result = strip_transaction_wrappers(sql)
        assert result == "ALTER TABLE foo ADD COLUMN bar TEXT;\n"

    def test_preserves_begin_in_identifier(self):
        """BEGIN inside a statement (e.g. comment or string) must not be stripped."""
        sql = "-- This starts a BEGIN block\nSELECT 1;\n"
        result = strip_transaction_wrappers(sql)
        assert result == "-- This starts a BEGIN block\nSELECT 1;\n"

    def test_empty_sql_returns_empty(self):
        assert strip_transaction_wrappers("") == ""

    def test_only_begin_commit_returns_empty(self):
        sql = "BEGIN;\nCOMMIT;\n"
        result = strip_transaction_wrappers(sql)
        assert result == ""

    def test_returns_changed_flag_true_when_stripped(self):
        sql = "BEGIN;\nSELECT 1;\nCOMMIT;\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert changed is True

    def test_returns_changed_flag_false_when_not_stripped(self):
        sql = "SELECT 1;\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert changed is False


# ---------------------------------------------------------------------------
# FileSQLMigration.up() strips BEGIN/COMMIT
# ---------------------------------------------------------------------------


def _make_migration(tmp_path: Path, up_sql: str, down_sql: str = "SELECT 1;") -> FileSQLMigration:
    """Helper: create a FileSQLMigration instance with given SQL content."""
    up_file = tmp_path / "001_example.up.sql"
    down_file = tmp_path / "001_example.down.sql"
    up_file.write_text(up_sql)
    down_file.write_text(down_sql)

    conn = MagicMock()
    return FileSQLMigration(connection=conn, up_file=up_file, down_file=down_file)


class TestFileSQLMigrationStripsTransactionWrappers:
    def test_up_strips_begin_commit_before_execute(self, tmp_path):
        """up() should strip BEGIN/COMMIT and execute only the inner SQL."""
        migration = _make_migration(
            tmp_path,
            up_sql="BEGIN;\nALTER TABLE foo ADD COLUMN bar TEXT;\nCOMMIT;\n",
        )
        with patch.object(migration, "execute") as mock_execute:
            migration.up()

        mock_execute.assert_called_once_with("ALTER TABLE foo ADD COLUMN bar TEXT;\n")

    def test_up_no_change_when_no_wrappers(self, tmp_path):
        """up() should pass SQL unchanged when no BEGIN/COMMIT present."""
        sql = "ALTER TABLE foo ADD COLUMN bar TEXT;\n"
        migration = _make_migration(tmp_path, up_sql=sql)
        with patch.object(migration, "execute") as mock_execute:
            migration.up()

        mock_execute.assert_called_once_with(sql)

    def test_down_strips_begin_commit_before_execute(self, tmp_path):
        """down() should strip BEGIN/COMMIT and execute only the inner SQL."""
        migration = _make_migration(
            tmp_path,
            up_sql="SELECT 1;",
            down_sql="BEGIN;\nALTER TABLE foo DROP COLUMN bar;\nCOMMIT;\n",
        )
        with patch.object(migration, "execute") as mock_execute:
            migration.down()

        mock_execute.assert_called_once_with("ALTER TABLE foo DROP COLUMN bar;\n")

    def test_up_emits_warning_when_stripped(self, tmp_path, caplog):
        """up() should log a warning when BEGIN/COMMIT lines are removed."""
        migration = _make_migration(
            tmp_path,
            up_sql="BEGIN;\nSELECT 1;\nCOMMIT;\n",
        )
        with patch.object(migration, "execute"):
            with caplog.at_level(logging.WARNING, logger="confiture"):
                migration.up()

        assert any(
            "BEGIN" in record.message or "transaction" in record.message.lower()
            for record in caplog.records
        )

    def test_down_emits_warning_when_stripped(self, tmp_path, caplog):
        """down() should log a warning when BEGIN/COMMIT lines are removed."""
        migration = _make_migration(
            tmp_path,
            up_sql="SELECT 1;",
            down_sql="BEGIN;\nSELECT 1;\nCOMMIT;\n",
        )
        with patch.object(migration, "execute"):
            with caplog.at_level(logging.WARNING, logger="confiture"):
                migration.down()

        assert any(
            "BEGIN" in record.message or "transaction" in record.message.lower()
            for record in caplog.records
        )

    def test_up_no_warning_when_not_stripped(self, tmp_path, caplog):
        """up() should not log any warning when no stripping occurs."""
        migration = _make_migration(tmp_path, up_sql="SELECT 1;\n")
        with patch.object(migration, "execute"):
            with caplog.at_level(logging.WARNING, logger="confiture"):
                migration.up()

        assert not caplog.records


# ---------------------------------------------------------------------------
# FileSQLMigration.from_files() strips BEGIN/COMMIT
# ---------------------------------------------------------------------------


class TestFileSQLMigrationFromFilesStrips:
    def test_from_files_up_strips_begin_commit(self, tmp_path):
        """from_files() class: up() should strip BEGIN/COMMIT."""
        up_file = tmp_path / "002_example.up.sql"
        down_file = tmp_path / "002_example.down.sql"
        up_file.write_text("BEGIN;\nCREATE TABLE bar (id INT);\nCOMMIT;\n")
        down_file.write_text("DROP TABLE bar;")

        MigrationClass = FileSQLMigration.from_files(up_file, down_file)
        conn = MagicMock()
        migration = MigrationClass(connection=conn)

        with patch.object(migration, "execute") as mock_execute:
            migration.up()

        mock_execute.assert_called_once_with("CREATE TABLE bar (id INT);\n")

    def test_from_files_down_strips_begin_commit(self, tmp_path):
        """from_files() class: down() should strip BEGIN/COMMIT."""
        up_file = tmp_path / "002_example.up.sql"
        down_file = tmp_path / "002_example.down.sql"
        up_file.write_text("CREATE TABLE bar (id INT);")
        down_file.write_text("BEGIN;\nDROP TABLE bar;\nCOMMIT;\n")

        MigrationClass = FileSQLMigration.from_files(up_file, down_file)
        conn = MagicMock()
        migration = MigrationClass(connection=conn)

        with patch.object(migration, "execute") as mock_execute:
            migration.down()

        mock_execute.assert_called_once_with("DROP TABLE bar;\n")

    def test_from_files_no_change_without_wrappers(self, tmp_path):
        """from_files() class: SQL without BEGIN/COMMIT is passed unchanged."""
        up_file = tmp_path / "002_example.up.sql"
        down_file = tmp_path / "002_example.down.sql"
        sql = "CREATE TABLE bar (id INT);\n"
        up_file.write_text(sql)
        down_file.write_text("DROP TABLE bar;\n")

        MigrationClass = FileSQLMigration.from_files(up_file, down_file)
        conn = MagicMock()
        migration = MigrationClass(connection=conn)

        with patch.object(migration, "execute") as mock_execute:
            migration.up()

        mock_execute.assert_called_once_with(sql)
