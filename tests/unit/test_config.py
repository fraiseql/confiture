"""Unit tests for configuration system (Milestone 1.2)

Tests for Environment class and YAML configuration loading.
"""

from pathlib import Path

import pytest
import yaml

from confiture.config.environment import Environment
from confiture.exceptions import ConfigurationError


class TestEnvironmentLoading:
    """Test Environment.load() from YAML files"""

    def test_load_environment_from_yaml(self, temp_project_dir: Path):
        """Environment should load from YAML file"""
        # Arrange: Create environment config
        env_file = temp_project_dir / "db" / "environments" / "test.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "test",
            "database_url": "postgresql://localhost/test_db",
            "include_dirs": ["db/schema"],
            "exclude_dirs": ["db/schema/deprecated"],
        }
        env_file.write_text(yaml.dump(config_data))

        # Act: Load environment
        env = Environment.load("test", project_dir=temp_project_dir)

        # Assert: Configuration loaded correctly
        assert env.name == "test"
        assert "postgresql://localhost/test_db" in env.database_url
        # Paths are resolved to absolute, check they end with expected paths
        assert any(path.endswith("db/schema") for path in env.include_dirs)
        assert any(path.endswith("db/schema/deprecated") for path in env.exclude_dirs)

    def test_load_missing_environment_file(self, temp_project_dir: Path):
        """Should raise ConfigurationError if YAML file missing"""
        with pytest.raises(ConfigurationError, match="not found"):
            Environment.load("nonexistent", project_dir=temp_project_dir)

    def test_load_malformed_yaml(self, temp_project_dir: Path):
        """Should raise ConfigurationError if YAML is malformed"""
        env_file = temp_project_dir / "db" / "environments" / "broken.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("invalid: yaml: syntax:")

        with pytest.raises(ConfigurationError, match="Invalid YAML"):
            Environment.load("broken", project_dir=temp_project_dir)

    def test_load_missing_required_fields(self, temp_project_dir: Path):
        """Should raise ConfigurationError if required fields missing"""
        env_file = temp_project_dir / "db" / "environments" / "incomplete.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"name": "incomplete"}  # Missing database_url
        env_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigurationError, match="database_url"):
            Environment.load("incomplete", project_dir=temp_project_dir)


class TestEnvironmentValidation:
    """Test Environment field validation"""

    def test_database_url_validation(self, temp_project_dir: Path):
        """Should validate PostgreSQL connection URL format"""
        env_file = temp_project_dir / "db" / "environments" / "invalid_url.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "invalid_url",
            "database_url": "not-a-valid-url",
            "include_dirs": ["db/schema"],
        }
        env_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigurationError, match="Invalid database_url"):
            Environment.load("invalid_url", project_dir=temp_project_dir)

    def test_include_dirs_must_exist(self, temp_project_dir: Path):
        """Should validate that include_dirs exist"""
        env_file = temp_project_dir / "db" / "environments" / "missing_dirs.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "missing_dirs",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/nonexistent"],
        }
        env_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigurationError, match="does not exist"):
            Environment.load("missing_dirs", project_dir=temp_project_dir)


class TestEnvironmentDefaults:
    """Test default configuration values"""

    def test_default_migration_table(self, temp_project_dir: Path):
        """Should use default migration tracking table name"""
        (temp_project_dir / "db" / "schema").mkdir(parents=True, exist_ok=True)
        env_file = temp_project_dir / "db" / "environments" / "defaults.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "defaults",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
        env_file.write_text(yaml.dump(config_data))

        env = Environment.load("defaults", project_dir=temp_project_dir)

        assert env.migration.tracking_table == "tb_confiture"

    def test_default_exclude_dirs_empty(self, temp_project_dir: Path):
        """Should have empty exclude_dirs by default"""
        (temp_project_dir / "db" / "schema").mkdir(parents=True, exist_ok=True)
        env_file = temp_project_dir / "db" / "environments" / "no_excludes.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "no_excludes",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
        env_file.write_text(yaml.dump(config_data))

        env = Environment.load("no_excludes", project_dir=temp_project_dir)

        assert env.exclude_dirs == []

    def test_default_auto_backup_true(self, temp_project_dir: Path):
        """Should enable auto-backup by default"""
        (temp_project_dir / "db" / "schema").mkdir(parents=True, exist_ok=True)
        env_file = temp_project_dir / "db" / "environments" / "backup.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "backup",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
        env_file.write_text(yaml.dump(config_data))

        env = Environment.load("backup", project_dir=temp_project_dir)

        assert env.auto_backup is True


class TestEnvironmentPaths:
    """Test path resolution in Environment"""

    def test_resolve_include_dirs_absolute(self, temp_project_dir: Path):
        """Should resolve include_dirs to absolute paths"""
        (temp_project_dir / "db" / "schema").mkdir(parents=True, exist_ok=True)
        env_file = temp_project_dir / "db" / "environments" / "paths.yaml"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "name": "paths",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
        env_file.write_text(yaml.dump(config_data))

        env = Environment.load("paths", project_dir=temp_project_dir)

        include_path = Path(env.include_dirs[0])
        assert include_path.is_absolute()
        assert include_path.exists()
