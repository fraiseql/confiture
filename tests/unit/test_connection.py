"""Tests for connection management utilities."""

from unittest.mock import MagicMock, patch

import psycopg
import pytest
import yaml

from confiture.core.connection import (
    create_connection,
    get_migration_class,
    load_config,
    load_migration_module,
)
from confiture.exceptions import MigrationError


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_success(self, tmp_path):
        """Test loading valid YAML config."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "database": {
                "host": "localhost",
                "port": 5432,
                "database": "test_db",
                "user": "test_user",
            }
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config["database"]["host"] == "localhost"
        assert config["database"]["port"] == 5432
        assert config["database"]["database"] == "test_db"

    def test_load_config_file_not_found(self, tmp_path):
        """Test loading non-existent config file."""
        nonexistent_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(MigrationError, match="Configuration file not found"):
            load_config(nonexistent_file)

    def test_load_config_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML content."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("{ invalid: yaml: content: : : }")

        with pytest.raises(MigrationError, match="Invalid YAML configuration"):
            load_config(config_file)

    def test_load_config_empty_file(self, tmp_path):
        """Test loading empty YAML file."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        config = load_config(config_file)
        assert config is None  # Empty YAML returns None


class TestCreateConnection:
    """Tests for create_connection function."""

    @patch("confiture.core.connection.psycopg.connect")
    def test_create_connection_success(self, mock_connect):
        """Test successful database connection."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        config = {
            "database": {
                "host": "localhost",
                "port": 5432,
                "database": "test_db",
                "user": "test_user",
                "password": "test_pass",
            }
        }

        conn = create_connection(config)

        assert conn == mock_conn
        mock_connect.assert_called_once_with(
            host="localhost",
            port=5432,
            dbname="test_db",
            user="test_user",
            password="test_pass",
        )

    @patch("confiture.core.connection.psycopg.connect")
    def test_create_connection_defaults(self, mock_connect):
        """Test connection with default values."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        config = {"database": {}}  # Empty database config

        conn = create_connection(config)

        assert conn == mock_conn
        mock_connect.assert_called_once_with(
            host="localhost",  # Default
            port=5432,  # Default
            dbname="postgres",  # Default
            user="postgres",  # Default
            password="",  # Default
        )

    @patch("confiture.core.connection.psycopg.connect")
    def test_create_connection_no_database_section(self, mock_connect):
        """Test connection with missing database section."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        config = {}  # No database section

        conn = create_connection(config)

        assert conn == mock_conn
        # Should use all defaults
        mock_connect.assert_called_once()

    @patch("confiture.core.connection.psycopg.connect")
    def test_create_connection_error(self, mock_connect):
        """Test connection failure."""
        mock_connect.side_effect = psycopg.OperationalError("Connection refused")

        config = {"database": {"host": "invalid-host"}}

        with pytest.raises(MigrationError, match="Failed to connect to database"):
            create_connection(config)


class TestLoadMigrationModule:
    """Tests for load_migration_module function."""

    def test_load_migration_module_success(self, tmp_path):
        """Test loading valid migration module."""
        migration_file = tmp_path / "001_test_migration.py"
        migration_content = '''
"""Test migration."""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test_migration"

    def up(self):
        self.execute("CREATE TABLE test (id INT);")

    def down(self):
        self.execute("DROP TABLE test;")
'''
        migration_file.write_text(migration_content)

        module = load_migration_module(migration_file)

        assert hasattr(module, "TestMigration")
        assert module.TestMigration.version == "001"

    def test_load_migration_module_invalid_file(self, tmp_path):
        """Test loading migration with syntax error."""
        migration_file = tmp_path / "002_invalid.py"
        migration_file.write_text("this is invalid python syntax {{{")

        with pytest.raises(MigrationError, match="Failed to load migration"):
            load_migration_module(migration_file)

    def test_load_migration_module_import_error(self, tmp_path):
        """Test loading migration with import error."""
        migration_file = tmp_path / "003_import_error.py"
        migration_file.write_text("import nonexistent_module")

        with pytest.raises(MigrationError, match="Failed to load migration"):
            load_migration_module(migration_file)


class TestGetMigrationClass:
    """Tests for get_migration_class function."""

    def test_get_migration_class_success(self, tmp_path):
        """Test extracting Migration class from module."""
        migration_file = tmp_path / "001_test.py"
        migration_content = """
from confiture.models.migration import Migration

class TestMigration(Migration):
    def up(self):
        pass
    def down(self):
        pass
"""
        migration_file.write_text(migration_content)

        module = load_migration_module(migration_file)
        migration_class = get_migration_class(module)

        assert migration_class.__name__ == "TestMigration"
        assert hasattr(migration_class, "up")
        assert hasattr(migration_class, "down")

    def test_get_migration_class_no_migration(self, tmp_path):
        """Test module without Migration subclass."""
        migration_file = tmp_path / "002_no_migration.py"
        migration_content = """
# Just a regular class, not a Migration
class SomeOtherClass:
    pass
"""
        migration_file.write_text(migration_content)

        module = load_migration_module(migration_file)

        with pytest.raises(MigrationError, match="No Migration subclass found"):
            get_migration_class(module)

    def test_get_migration_class_multiple_migrations(self, tmp_path):
        """Test module with multiple Migration subclasses (returns first)."""
        migration_file = tmp_path / "003_multiple.py"
        migration_content = """
from confiture.models.migration import Migration

class FirstMigration(Migration):
    def up(self):
        pass
    def down(self):
        pass

class SecondMigration(Migration):
    def up(self):
        pass
    def down(self):
        pass
"""
        migration_file.write_text(migration_content)

        module = load_migration_module(migration_file)
        migration_class = get_migration_class(module)

        # Should return one of the migration classes
        assert migration_class.__name__ in ["FirstMigration", "SecondMigration"]
