"""Tests that public-API raise sites populate error_code correctly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.exceptions import (
    ConfigurationError,
    MigrationError,
    SchemaError,
)

# ── C-1: MIGR_010 (lock timeout) and MIGR_011 (checksum mismatch) in registry ──


def test_migr_010_registered():
    from confiture.core.error_codes import ERROR_CODE_REGISTRY

    definition = ERROR_CODE_REGISTRY.get("MIGR_010")
    assert definition.code == "MIGR_010"
    assert definition.exit_code == 3


def test_migr_011_registered():
    from confiture.core.error_codes import ERROR_CODE_REGISTRY

    definition = ERROR_CODE_REGISTRY.get("MIGR_011")
    assert definition.code == "MIGR_011"
    assert definition.exit_code == 3


def test_config_010_registered():
    from confiture.core.error_codes import ERROR_CODE_REGISTRY

    definition = ERROR_CODE_REGISTRY.get("CONFIG_010")
    assert definition.code == "CONFIG_010"
    assert definition.exit_code == 2


# ── C-2: ConfigurationError guard raises with CONFIG_001 ──────────────────────


def _make_env():
    from confiture.config.environment import Environment

    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
    )


def test_migrator_session_guard_has_config_error_code():
    """MigratorSession used outside context manager raises ConfigurationError with CONFIG_001."""
    from confiture.core.migrator import MigratorSession

    session = MigratorSession(_make_env(), Path("db/migrations"))

    with pytest.raises(ConfigurationError) as exc_info:
        session.status()

    assert exc_info.value.error_code == "CONFIG_001"
    assert exc_info.value.exit_code == 2


def test_migrator_session_up_guard_has_config_error_code():
    from confiture.core.migrator import MigratorSession

    session = MigratorSession(_make_env(), Path("db/migrations"))

    with pytest.raises(ConfigurationError) as exc_info:
        session.up()

    assert exc_info.value.error_code == "CONFIG_001"


# ── C-3: SchemaError default code ────────────────────────────────────────────


def test_schema_error_default_has_error_code():
    """SchemaError without explicit code gets SCHEMA_001."""
    e = SchemaError("test schema error")
    assert e.error_code == "SCHEMA_001"
    assert e.exit_code == 4


# ── C-4: Specific codes at key engine raise sites ────────────────────────────


def test_apply_already_applied_uses_migr_101():
    """engine.apply() raises MigrationError with MIGR_101 when migration already applied."""
    from confiture.core._migrator.engine import Migrator

    mock_conn = MagicMock()
    migrator = Migrator(connection=mock_conn)

    mock_migration = MagicMock()
    mock_migration.version = "20260101000001"
    mock_migration.name = "test_migration"

    with patch.object(migrator, "_is_applied", return_value=True):
        with pytest.raises(MigrationError) as exc_info:
            migrator.apply(mock_migration, force=False)

    assert exc_info.value.error_code == "MIGR_101"


def test_reinit_version_not_found_uses_migr_100():
    """engine.reinit() raises MigrationError with MIGR_100 when through version not found."""
    from confiture.core._migrator.engine import Migrator

    mock_conn = MagicMock()
    migrator = Migrator(connection=mock_conn)

    with patch.object(migrator, "find_migration_files", return_value=[]):
        with pytest.raises(MigrationError) as exc_info:
            migrator.reinit(through="nonexistent_version", migrations_dir=Path("db/migrations"))

    assert exc_info.value.error_code == "MIGR_100"


def test_rollback_not_applied_uses_migr_100():
    """engine.rollback() raises MigrationError with MIGR_100 when migration not applied."""
    from confiture.core._migrator.engine import Migrator

    mock_conn = MagicMock()
    migrator = Migrator(connection=mock_conn)

    mock_migration = MagicMock()
    mock_migration.version = "20260101000001"
    mock_migration.name = "test_migration"

    with patch.object(migrator, "_is_applied", return_value=False):
        with pytest.raises(MigrationError) as exc_info:
            migrator.rollback(mock_migration)

    assert exc_info.value.error_code == "MIGR_100"


def test_from_config_missing_file_uses_config_004():
    """Migrator.from_config() raises ConfigurationError with CONFIG_004 for missing file."""
    from confiture.core.migrator import Migrator

    with pytest.raises(ConfigurationError) as exc_info:
        Migrator.from_config("/nonexistent/path/config.yaml")

    assert exc_info.value.error_code == "CONFIG_004"
    assert exc_info.value.exit_code == 2


# ── C-5: error_code is always present as non-None string ─────────────────────


def test_migration_error_to_dict_has_error_code():
    """MigrationError.to_dict()['error_code'] is always a non-None string."""
    e = MigrationError("something failed")
    d = e.to_dict()
    assert d["error_code"] is not None
    assert isinstance(d["error_code"], str)


def test_configuration_error_to_dict_has_error_code():
    """ConfigurationError.to_dict()['error_code'] is always a non-None string."""
    e = ConfigurationError("bad config")
    d = e.to_dict()
    assert d["error_code"] is not None
    assert isinstance(d["error_code"], str)


def test_schema_error_to_dict_has_error_code():
    """SchemaError.to_dict()['error_code'] is always a non-None string."""
    e = SchemaError("bad schema")
    d = e.to_dict()
    assert d["error_code"] is not None
    assert isinstance(d["error_code"], str)
