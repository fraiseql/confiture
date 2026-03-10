"""Test that MigratorSession methods raise ConfigurationError when called outside 'with' block."""

import pytest

from confiture.core.migrator import Migrator
from confiture.exceptions import ConfigurationError


def test_status_outside_with_block_raises_configuration_error() -> None:
    """Test that calling status() outside 'with' block raises ConfigurationError."""
    session = Migrator.from_config("db/environments/test.yaml")
    with pytest.raises(ConfigurationError, match="context manager"):
        session.status()


def test_up_outside_with_block_raises_configuration_error() -> None:
    """Test that calling up() outside 'with' block raises ConfigurationError."""
    session = Migrator.from_config("db/environments/test.yaml")
    with pytest.raises(ConfigurationError, match="context manager"):
        session.up()


def test_down_outside_with_block_raises_configuration_error() -> None:
    """Test that calling down() outside 'with' block raises ConfigurationError."""
    session = Migrator.from_config("db/environments/test.yaml")
    with pytest.raises(ConfigurationError, match="context manager"):
        session.down(steps=1)


def test_reinit_outside_with_block_raises_configuration_error() -> None:
    """Test that calling reinit() outside 'with' block raises ConfigurationError."""
    session = Migrator.from_config("db/environments/test.yaml")
    with pytest.raises(ConfigurationError, match="context manager"):
        session.reinit()


def test_rebuild_outside_with_block_raises_configuration_error() -> None:
    """Test that calling rebuild() outside 'with' block raises ConfigurationError."""
    session = Migrator.from_config("db/environments/test.yaml")
    with pytest.raises(ConfigurationError, match="context manager"):
        session.rebuild()
