"""Tests for MigratorSession and Migrator.from_config()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import Migrator, MigratorSession


def _make_env(database_url: str = "postgresql://localhost/test") -> Environment:
    return Environment.model_validate(
        {
            "name": "test",
            "database_url": database_url,
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": "tb_confiture"},
        }
    )


class TestMigratorSessionContextManager:
    def test_enter_returns_self(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = MigratorSession(env, Path("db/migrations"))
            result = session.__enter__()
            assert result is session

    def test_exit_closes_connection(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = MigratorSession(env, Path("db/migrations"))
            session.__enter__()
            session.__exit__(None, None, None)
            mock_conn.close.assert_called_once()

    def test_exit_closes_connection_on_exception(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = MigratorSession(env, Path("db/migrations"))
            session.__enter__()
            session.__exit__(RuntimeError, RuntimeError("boom"), None)
            mock_conn.close.assert_called_once()

    def test_context_manager_with_statement(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with MigratorSession(env, Path("db/migrations")) as session:
                assert isinstance(session, MigratorSession)
            mock_conn.close.assert_called_once()

    def test_connection_closed_even_if_body_raises(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with pytest.raises(ValueError):
                with MigratorSession(env, Path("db/migrations")):
                    raise ValueError("body error")
            mock_conn.close.assert_called_once()

    def test_inner_migrator_uses_tracking_table_from_env(self):
        env = Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": "custom.tb_track"},
            }
        )
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with MigratorSession(env, Path("db/migrations")) as session:
                assert session._migrator.migration_table == "custom.tb_track"


class TestMigratorFromConfig:
    def test_from_config_with_environment_object(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = Migrator.from_config(env)
            assert isinstance(session, MigratorSession)

    def test_from_config_with_path(self, tmp_path):
        config_file = tmp_path / "local.yaml"
        config_file.write_text(
            "name: test\ndatabase_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
        )
        mock_conn = MagicMock()
        with (
            patch("confiture.core.migrator.create_connection", return_value=mock_conn),
        ):
            session = Migrator.from_config(config_file)
            assert isinstance(session, MigratorSession)

    def test_from_config_with_string_path(self, tmp_path):
        config_file = tmp_path / "local.yaml"
        config_file.write_text(
            "name: test\ndatabase_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
        )
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = Migrator.from_config(str(config_file))
            assert isinstance(session, MigratorSession)

    def test_from_config_custom_migrations_dir(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = Migrator.from_config(env, migrations_dir=Path("custom/migrations"))
            assert session._migrations_dir == Path("custom/migrations")

    def test_from_config_returns_usable_context_manager(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with Migrator.from_config(env) as m:
                assert isinstance(m, MigratorSession)
            mock_conn.close.assert_called_once()

    def test_from_config_nonexistent_file_raises(self):
        with pytest.raises(Exception):
            Migrator.from_config(Path("/nonexistent/config.yaml"))

    def test_from_config_default_migrations_dir(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = Migrator.from_config(env)
            assert session._migrations_dir == Path("db/migrations")


class TestMigratorSessionHasMethods:
    """Verify MigratorSession exposes the expected public API."""

    def test_has_status_method(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with Migrator.from_config(env) as m:
                assert callable(m.status)

    def test_has_up_method(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with Migrator.from_config(env) as m:
                assert callable(m.up)

    def test_has_down_method(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with Migrator.from_config(env) as m:
                assert callable(m.down)

    def test_has_reinit_method(self):
        env = _make_env()
        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            with Migrator.from_config(env) as m:
                assert callable(m.reinit)
