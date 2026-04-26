"""Tests for Migration.execute_file() method."""

from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from confiture.models.migration import Migration


class ConcreteMigration(Migration):
    """Concrete migration subclass for testing."""

    version = "20260426120000"
    name = "test_migration"

    def up(self) -> None:
        pass

    def down(self) -> None:
        pass


def _make_migration(tmp_path: Path) -> ConcreteMigration:
    """Create a ConcreteMigration with a mock connection."""
    mock_conn = MagicMock(spec=psycopg.Connection)
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return ConcreteMigration(connection=mock_conn)


class TestExecuteFileHappyPath:
    """Cycle 1: execute_file reads file and delegates to self.execute()."""

    def test_executes_sql_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        sql_file = tmp_path / "schema.sql"
        sql_file.write_text("CREATE TABLE users (id INT);", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file("schema.sql")

        migration.execute.assert_called_once_with("CREATE TABLE users (id INT);")

    def test_executes_sql_from_absolute_path(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "func.sql"
        sql_file.write_text("SELECT 1;", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file(sql_file)

        migration.execute.assert_called_once_with("SELECT 1;")

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "init.sql"
        sql_file.write_text("CREATE SCHEMA app;", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file(Path(str(sql_file)))

        migration.execute.assert_called_once_with("CREATE SCHEMA app;")

    def test_reads_utf8_content(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "unicode.sql"
        sql_file.write_text("-- Commentaire en français\nSELECT 1;", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file(sql_file)

        migration.execute.assert_called_once_with("-- Commentaire en français\nSELECT 1;")

    def test_multiline_sql(self, tmp_path: Path) -> None:
        sql_content = """\
CREATE OR REPLACE FUNCTION my_func()
RETURNS void AS $$
BEGIN
    RAISE NOTICE 'hello';
END;
$$ LANGUAGE plpgsql;"""
        sql_file = tmp_path / "func.sql"
        sql_file.write_text(sql_content, encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file(sql_file)

        migration.execute.assert_called_once_with(sql_content)


class TestExecuteFileErrors:
    """Cycle 2: error cases."""

    def test_file_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        migration = _make_migration(tmp_path)

        with pytest.raises(FileNotFoundError, match="SQL file not found"):
            migration.execute_file("nonexistent.sql")

    def test_empty_file(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "empty.sql"
        sql_file.write_text("", encoding="utf-8")

        migration = _make_migration(tmp_path)

        with pytest.raises(ValueError, match="SQL file is empty"):
            migration.execute_file(sql_file)

    def test_whitespace_only_file(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "blank.sql"
        sql_file.write_text("   \n\n  \t  \n", encoding="utf-8")

        migration = _make_migration(tmp_path)

        with pytest.raises(ValueError, match="SQL file is empty"):
            migration.execute_file(sql_file)

    def test_sql_error_propagates(self, tmp_path: Path) -> None:
        from confiture.exceptions import SQLError

        sql_file = tmp_path / "bad.sql"
        sql_file.write_text("INVALID SQL;", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock(
            side_effect=SQLError("INVALID SQL;", None, Exception("syntax error"))
        )  # type: ignore[method-assign]

        with pytest.raises(SQLError):
            migration.execute_file(sql_file)


class TestExecuteFilePathResolution:
    """Cycle 3: path types and relative resolution."""

    def test_relative_path_resolves_against_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "db" / "schema"
        subdir.mkdir(parents=True)
        sql_file = subdir / "tables.sql"
        sql_file.write_text("CREATE TABLE t (id INT);", encoding="utf-8")

        migration = _make_migration(tmp_path)
        migration.execute = MagicMock()  # type: ignore[method-assign]

        migration.execute_file("db/schema/tables.sql")

        migration.execute.assert_called_once_with("CREATE TABLE t (id INT);")

    def test_str_and_path_produce_same_result(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "same.sql"
        sql_file.write_text("SELECT 42;", encoding="utf-8")

        m1 = _make_migration(tmp_path)
        m1.execute = MagicMock()  # type: ignore[method-assign]
        m1.execute_file(str(sql_file))

        m2 = _make_migration(tmp_path)
        m2.execute = MagicMock()  # type: ignore[method-assign]
        m2.execute_file(Path(str(sql_file)))

        assert m1.execute.call_args == m2.execute.call_args
