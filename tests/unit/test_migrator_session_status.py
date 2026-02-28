"""Tests for MigratorSession.status()."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.config.environment import Environment
from confiture.core.migrator import MigratorSession
from confiture.models.results import StatusResult


def _make_env(tracking_table: str = "tb_confiture") -> Environment:
    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": tracking_table},
        }
    )


def _make_session(env: Environment, migrations_dir: Path, mock_conn: MagicMock) -> MigratorSession:
    """Create a MigratorSession with a mocked connection that has entered the context."""
    with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
        session = MigratorSession(env, migrations_dir)
        session.__enter__()
    return session


class TestMigratorSessionStatusNoMigrationsDir:
    def test_missing_migrations_dir_returns_empty_result(self, tmp_path):
        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, tmp_path / "nonexistent", mock_conn)

        result = session.status()

        assert isinstance(result, StatusResult)
        assert result.migrations == []
        assert result.summary["total"] == 0

    def test_empty_migrations_dir_returns_empty_result(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)

        # mock out the DB calls so we can test the file-based path
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()

        assert result.migrations == []
        assert result.has_pending is False


class TestMigratorSessionStatusTrackingTableAbsent:
    def test_all_shown_as_pending_when_table_absent(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_posts.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=False)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()

        assert result.tracking_table_exists is False
        assert all(m.status == "pending" for m in result.migrations)
        assert result.summary["pending"] == 2
        assert result.summary["applied"] == 0

    def test_tracking_table_name_from_env(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        env = _make_env(tracking_table="custom.tb_track")
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=False)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()

        assert result.tracking_table == "custom.tb_track"


class TestMigratorSessionStatusAllApplied:
    def test_all_applied(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_posts.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)

        ts = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=["001", "002"])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(
            return_value=[
                {"version": "001", "applied_at": ts.isoformat()},
                {"version": "002", "applied_at": ts.isoformat()},
            ]
        )

        result = session.status()

        assert result.tracking_table_exists is True
        assert result.has_pending is False
        assert result.summary["applied"] == 2
        assert result.summary["pending"] == 0

    def test_applied_at_set_for_applied_migrations(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)

        ts_str = "2026-02-01T12:00:00+00:00"
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=["001"])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(
            return_value=[{"version": "001", "applied_at": ts_str}]
        )

        result = session.status()

        assert result.migrations[0].applied_at is not None


class TestMigratorSessionStatusMixed:
    def test_mixed_applied_and_pending(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_posts.py").write_text("# migration")
        (migrations_dir / "003_add_comments.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)

        ts = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=["001", "002"])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(
            return_value=[
                {"version": "001", "applied_at": ts.isoformat()},
                {"version": "002", "applied_at": ts.isoformat()},
            ]
        )

        result = session.status()

        assert result.has_pending is True
        assert result.summary["applied"] == 2
        assert result.summary["pending"] == 1
        assert result.summary["total"] == 3
        assert result.pending == ["003"]
        assert "001" in result.applied
        assert "002" in result.applied

    def test_sql_migrations_included(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.up.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "001_add_users.down.sql").write_text("DROP TABLE users;")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=["001"])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(
            return_value=[{"version": "001", "applied_at": "2026-02-01T12:00:00+00:00"}]
        )

        result = session.status()

        assert result.summary["total"] == 1
        assert result.migrations[0].version == "001"

    def test_result_has_correct_tracking_table_exists_true(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()
        assert result.tracking_table_exists is True

    def test_version_extracted_from_py_filename(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "20260228131907_add_users.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()

        assert result.migrations[0].version == "20260228131907"
        assert result.migrations[0].name == "add_users"

    def test_version_extracted_from_sql_filename(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_posts.up.sql").write_text("-- sql")
        (migrations_dir / "001_add_posts.down.sql").write_text("-- sql")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=[])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(return_value=[])

        result = session.status()

        assert result.migrations[0].version == "001"
        assert result.migrations[0].name == "add_posts"


class TestMigratorSessionStatusToDict:
    def test_to_dict_has_expected_keys(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")

        env = _make_env()
        mock_conn = MagicMock()
        session = _make_session(env, migrations_dir, mock_conn)
        session._migrator.tracking_table_exists = MagicMock(return_value=True)
        session._migrator.get_applied_versions = MagicMock(return_value=["001"])
        session._migrator.get_applied_migrations_with_timestamps = MagicMock(
            return_value=[{"version": "001", "applied_at": "2026-02-01T12:00:00+00:00"}]
        )

        result = session.status()
        d = result.to_dict()

        assert "tracking_table" in d
        assert "tracking_table_exists" in d
        assert "migrations" in d
        assert "summary" in d
