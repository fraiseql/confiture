"""Tests for Pydantic ValidationError wrapping at config boundaries.

Verifies that invalid YAML configs raise ConfigurationError (not
pydantic.ValidationError) when loaded through Migrator.from_config().
"""

from pathlib import Path

import pytest

from confiture.exceptions import ConfigurationError


class TestConfigValidationWrapping:
    """Tests for Pydantic ValidationError → ConfigurationError wrapping."""

    def test_invalid_config_raises_configuration_error(self, tmp_path: Path):
        """Invalid YAML config should raise ConfigurationError, not ValidationError."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("name: 123\ndatabase_url: not-a-url\n")

        from confiture.core.migrator import Migrator

        with pytest.raises(ConfigurationError) as exc_info:
            Migrator.from_config(config_file)

        assert exc_info.value.error_code == "CONFIG_002"
        assert "bad.yaml" in str(exc_info.value)

    def test_missing_config_raises_configuration_error(self, tmp_path: Path):
        """Missing config file should raise ConfigurationError with CONFIG_004."""
        from confiture.core.migrator import Migrator

        with pytest.raises(ConfigurationError) as exc_info:
            Migrator.from_config(tmp_path / "nonexistent.yaml")

        assert exc_info.value.error_code == "CONFIG_004"

    def test_wrapped_validation_error_has_context(self, tmp_path: Path):
        """Wrapped error should preserve file_path in context."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("name: 123\ndatabase_url: not-a-url\n")

        from confiture.core.migrator import Migrator

        with pytest.raises(ConfigurationError) as exc_info:
            Migrator.from_config(config_file)

        assert "file_path" in exc_info.value.context
        assert exc_info.value.resolution_hint is not None
