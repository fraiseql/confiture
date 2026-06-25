"""Issue #169 — SQL-file migrations auto-detect non-transactional statements.

A pure ``.up.sql`` migration cannot declare ``transactional = False`` (there is
no Python class to set the attribute on).  Before this fix such a migration —
e.g. ``CREATE INDEX CONCURRENTLY`` — inherited ``transactional = True`` and so:

- ``migrate up`` ran it inside a SAVEPOINT and PostgreSQL rejected it
  ("cannot run inside a transaction block");
- ``preflight --against`` replayed it inside a SAVEPOINT, failed, and reported
  an error-severity ``PFLIGHT_REPLAY_FAILED`` (exit 7) — a false positive next
  to the ``PFLIGHT_NON_TRANSACTIONAL`` warning the static analyzer already
  emits for the same migration.

``FileSQLMigration`` now reflects its ``.up.sql`` content via the same
``MigrationAnalyzer`` the static preflight check uses, so a non-transactional
SQL file runs in autocommit (``migrate up``) and is skipped (``preflight``),
exactly like a Python migration with ``transactional = False``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from confiture.models.sql_file_migration import FileSQLMigration


def _make(tmp_path, up_sql: str, down_sql: str = "SELECT 1;"):
    up_file = tmp_path / "20260101000000_example.up.sql"
    down_file = tmp_path / "20260101000000_example.down.sql"
    up_file.write_text(up_sql)
    down_file.write_text(down_sql)
    return FileSQLMigration.from_files(up_file, down_file)


class TestFromFilesTransactionalDetection:
    def test_create_index_concurrently_is_non_transactional(self, tmp_path):
        cls = _make(tmp_path, "CREATE INDEX CONCURRENTLY idx_x ON some_table (col);")
        assert cls.transactional is False

    def test_plain_ddl_stays_transactional(self, tmp_path):
        cls = _make(tmp_path, "CREATE TABLE foo (id INT);")
        assert cls.transactional is True

    def test_vacuum_is_non_transactional(self, tmp_path):
        cls = _make(tmp_path, "VACUUM some_table;")
        assert cls.transactional is False

    def test_alter_type_add_value_is_non_transactional(self, tmp_path):
        cls = _make(tmp_path, "ALTER TYPE my_enum ADD VALUE 'extra';")
        assert cls.transactional is False

    @pytest.mark.parametrize("attr", ["transactional"])
    def test_attribute_is_class_level(self, tmp_path, attr):
        """The flag is set on the class, so apply/run_against can read it
        without instantiating against a live connection first."""
        cls = _make(tmp_path, "CREATE INDEX CONCURRENTLY idx_x ON t (c);")
        assert getattr(cls, attr) is False
        migration = cls(connection=MagicMock())
        assert getattr(migration, attr) is False


class TestDirectConstructorDetection:
    """The direct ``FileSQLMigration(conn, up, down)`` path (not used by the
    loader, but public) must agree with ``from_files``."""

    def test_direct_init_detects_non_transactional(self, tmp_path):
        up_file = tmp_path / "20260101000000_example.up.sql"
        down_file = tmp_path / "20260101000000_example.down.sql"
        up_file.write_text("CREATE INDEX CONCURRENTLY idx_x ON t (c);")
        down_file.write_text("DROP INDEX CONCURRENTLY IF EXISTS idx_x;")

        migration = FileSQLMigration(MagicMock(), up_file, down_file)
        assert migration.transactional is False
