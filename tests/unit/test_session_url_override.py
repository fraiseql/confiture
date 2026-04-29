"""Unit tests for MigratorSession constructor URL/table overrides."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core._migrator.session import MigratorSession
from confiture.exceptions import ConfigurationError


@pytest.fixture()
def mock_env():
    env = MagicMock()
    env.database_url = "postgresql://localhost/main"
    env.migration.tracking_table = "tb_confiture"
    return env


def test_override_url_used(mock_env):
    with patch("confiture.core.migrator.create_connection") as mock_cc:
        mock_cc.return_value = MagicMock()
        session = MigratorSession(
            mock_env,
            Path("db/migrations"),
            database_url_override="postgresql://localhost/preflight",
        )
        with session:
            pass
    mock_cc.assert_called_once_with("postgresql://localhost/preflight")


def test_config_url_used_when_no_override(mock_env):
    mock_env.database_url = "postgresql://localhost/main"
    with patch("confiture.core.migrator.create_connection") as mock_cc:
        mock_cc.return_value = MagicMock()
        with MigratorSession(mock_env, Path("db/migrations")):
            pass
    mock_cc.assert_called_once_with("postgresql://localhost/main")


def test_no_config_no_override_raises():
    session = MigratorSession(None, Path("db/migrations"))
    with pytest.raises(ConfigurationError):
        session.__enter__()


def test_migration_table_override_used(mock_env):
    with (
        patch("confiture.core.migrator.create_connection") as mock_cc,
        patch("confiture.core._migrator.session.Migrator") as MockMigrator,
    ):
        mock_cc.return_value = MagicMock()
        session = MigratorSession(
            mock_env,
            Path("db/migrations"),
            database_url_override="postgresql://localhost/preflight",
            migration_table_override="my_tracking",
        )
        with session:
            pass
    MockMigrator.assert_called_once_with(
        connection=mock_cc.return_value,
        migration_table="my_tracking",
    )


def test_override_url_no_table_override_defaults_to_tb_confiture():
    with (
        patch("confiture.core.migrator.create_connection") as mock_cc,
        patch("confiture.core._migrator.session.Migrator") as MockMigrator,
    ):
        mock_cc.return_value = MagicMock()
        session = MigratorSession(
            None,
            Path("db/migrations"),
            database_url_override="postgresql://localhost/preflight",
        )
        with session:
            pass
    MockMigrator.assert_called_once_with(
        connection=mock_cc.return_value,
        migration_table="tb_confiture",
    )
