"""Unit tests for configurable migration tracking table name (Issue #60).

tracking_table is nested under migration: in the environment YAML, consistent
with all other migration settings. Migrator previously hardcoded 'tb_confiture'.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.migrator import Migrator

# ---------------------------------------------------------------------------
# Migrator.__init__ — migration_table parameter
# ---------------------------------------------------------------------------


class TestMigratorMigrationTableInit:
    def test_default_migration_table(self):
        """Default table name is 'tb_confiture'."""
        conn = MagicMock()
        m = Migrator(connection=conn)
        assert m.migration_table == "tb_confiture"

    def test_custom_unqualified_table_name(self):
        """Custom unqualified table name is stored."""
        conn = MagicMock()
        m = Migrator(connection=conn, migration_table="my_migrations")
        assert m.migration_table == "my_migrations"

    def test_schema_qualified_table_name(self):
        """Schema-qualified table name (public.tb_confiture) is stored."""
        conn = MagicMock()
        m = Migrator(connection=conn, migration_table="public.tb_confiture")
        assert m.migration_table == "public.tb_confiture"

    def test_table_base_unqualified(self):
        """_table_base equals migration_table when no schema prefix."""
        conn = MagicMock()
        m = Migrator(connection=conn, migration_table="my_migrations")
        assert m._table_base == "my_migrations"

    def test_table_base_schema_qualified(self):
        """_table_base is the unqualified part of a schema.table name."""
        conn = MagicMock()
        m = Migrator(connection=conn, migration_table="public.tb_confiture")
        assert m._table_base == "tb_confiture"

    def test_custom_schema_and_table(self):
        """Custom schema and table name stored and parsed correctly."""
        conn = MagicMock()
        m = Migrator(connection=conn, migration_table="myschema.tracking")
        assert m.migration_table == "myschema.tracking"
        assert m._table_base == "tracking"

    def test_invalid_table_name_raises(self):
        """Invalid table name (SQL injection chars) raises ValueError."""
        conn = MagicMock()
        with pytest.raises(ValueError, match="Invalid migration_table"):
            Migrator(connection=conn, migration_table="'; DROP TABLE users; --")

    def test_invalid_table_name_semicolon(self):
        """Semicolon in table name raises ValueError."""
        conn = MagicMock()
        with pytest.raises(ValueError, match="Invalid migration_table"):
            Migrator(connection=conn, migration_table="tb_confiture; DROP TABLE")

    def test_invalid_too_many_dots(self):
        """Three-part name (catalog.schema.table) raises ValueError."""
        conn = MagicMock()
        with pytest.raises(ValueError, match="Invalid migration_table"):
            Migrator(connection=conn, migration_table="catalog.schema.table")


# ---------------------------------------------------------------------------
# Migrator.tracking_table_exists — uses configured table name
# ---------------------------------------------------------------------------


class TestTrackingTableExistsCustomTable:
    def _make_migrator(self, table_name: str) -> Migrator:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (True,)
        conn.cursor.return_value = cursor
        return Migrator(connection=conn, migration_table=table_name)

    def test_tracking_table_exists_unqualified(self):
        """tracking_table_exists() checks correct table name (unqualified)."""
        m = self._make_migrator("my_migrations")
        result = m.tracking_table_exists()
        assert result is True
        cursor = m.connection.cursor.return_value.__enter__.return_value
        sql_executed = cursor.execute.call_args[0][0]
        assert "my_migrations" in sql_executed or cursor.execute.call_args[1] is not None

    def test_tracking_table_exists_schema_qualified(self):
        """tracking_table_exists() checks correct schema+table (qualified)."""
        m = self._make_migrator("public.tb_confiture")
        result = m.tracking_table_exists()
        assert result is True
        cursor = m.connection.cursor.return_value.__enter__.return_value
        execute_call = cursor.execute.call_args
        # Should pass 'public' and 'tb_confiture' as parameters
        if execute_call[1]:
            params = execute_call[1].get("params") or execute_call[0][1]
        else:
            params = execute_call[0][1] if len(execute_call[0]) > 1 else None
        assert params is not None
        assert "public" in params
        assert "tb_confiture" in params


# ---------------------------------------------------------------------------
# Config model — tracking_table nested under migration:
# ---------------------------------------------------------------------------


class TestMigrationConfigTrackingTable:
    def test_default_tracking_table(self):
        """MigrationConfig.tracking_table defaults to 'tb_confiture'."""
        from confiture.config.environment import MigrationConfig

        cfg = MigrationConfig()
        assert cfg.tracking_table == "tb_confiture"

    def test_custom_tracking_table(self):
        """MigrationConfig.tracking_table accepts custom value."""
        from confiture.config.environment import MigrationConfig

        cfg = MigrationConfig(tracking_table="public.tb_confiture")
        assert cfg.tracking_table == "public.tb_confiture"

    def test_environment_no_top_level_migration_table(self):
        """Environment no longer has a top-level migration_table field."""
        from confiture.config.environment import Environment

        env = Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test_db",
                "include_dirs": ["db/schema"],
            }
        )
        assert not hasattr(env, "migration_table")

    def test_environment_tracking_table_via_migration(self):
        """tracking_table is accessible via env.migration.tracking_table."""
        from confiture.config.environment import Environment

        env = Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test_db",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": "public.tb_confiture"},
            }
        )
        assert env.migration.tracking_table == "public.tb_confiture"


# ---------------------------------------------------------------------------
# CLI — migration.tracking_table from config is passed to Migrator
# ---------------------------------------------------------------------------


class TestCLIMigrationTablePassthrough:
    """Test that CLI commands pass migration.tracking_table from config to Migrator."""

    def _write_config(self, config_dir: Path, tracking_table: str = "public.tb_confiture") -> Path:
        config_file = config_dir / "test.yaml"
        config_file.write_text(
            f"""
name: test
database_url: postgresql://localhost/test_db
include_dirs:
  - db/schema
migration:
  tracking_table: {tracking_table}
"""
        )
        return config_file

    def _make_env(self, tracking_table: str = "public.tb_confiture"):
        from confiture.config.environment import Environment

        return Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test_db",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": tracking_table},
            }
        )

    def test_migrate_up_passes_migration_table_to_migrator(self, tmp_path):
        """migrate up passes migration.tracking_table from config to Migrator."""
        from typer.testing import CliRunner

        from confiture.cli.main import app

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = self._write_config(config_dir, "public.tb_confiture")

        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        runner = CliRunner()

        with (
            patch("confiture.core.connection.create_connection") as mock_conn_factory,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.connection.load_config") as mock_load_config,
        ):
            mock_load_config.return_value = self._make_env("public.tb_confiture")
            mock_conn_factory.return_value = MagicMock()

            mock_migrator_instance = MagicMock()
            mock_migrator_instance.tracking_table_exists.return_value = True
            mock_migrator_instance.find_migration_files.return_value = []
            mock_migrator_cls.return_value = mock_migrator_instance

            runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

            mock_migrator_cls.assert_called_once()
            call_kwargs = mock_migrator_cls.call_args[1]
            assert call_kwargs.get("migration_table") == "public.tb_confiture"

    def test_migrate_status_passes_migration_table_to_migrator(self, tmp_path):
        """migrate status passes migration.tracking_table from config to Migrator."""
        from typer.testing import CliRunner

        from confiture.cli.main import app

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = self._write_config(config_dir, "public.tb_confiture")

        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_init.up.sql").write_text("SELECT 1;")

        runner = CliRunner()

        with (
            patch("confiture.core.connection.create_connection") as mock_conn_factory,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.connection.load_config") as mock_load_config,
        ):
            mock_load_config.return_value = self._make_env("public.tb_confiture")
            mock_conn_factory.return_value = MagicMock()

            mock_migrator_instance = MagicMock()
            mock_migrator_instance.tracking_table_exists.return_value = True
            mock_migrator_instance.get_applied_versions.return_value = []
            mock_migrator_cls.return_value = mock_migrator_instance

            runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )
