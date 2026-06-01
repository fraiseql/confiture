"""Tests for --database-url resolution precedence (issue #140).

Precedence: --database-url flag > CONFITURE_DATABASE_URL > DATABASE_URL > None
(None means: let MigratorSession/load_config resolve from --config).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.cli.helpers import resolve_database_url
from confiture.exceptions import ConfigurationError


def test_flag_wins_over_env_and_config(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://env/db")
    assert resolve_database_url("postgresql://flag/db", Path("env.yaml")) == "postgresql://flag/db"


def test_env_used_when_no_flag(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://env/db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_database_url(None, None) == "postgresql://env/db"


def test_canonical_env_wins_over_bare(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://bare/db")
    assert resolve_database_url(None, None) == "postgresql://canonical/db"


def test_bare_database_url_fallback(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://bare/db")
    assert resolve_database_url(None, None) == "postgresql://bare/db"


def test_returns_none_when_only_config(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # No flag, no env → caller falls back to config_path.
    assert resolve_database_url(None, Path("env.yaml")) is None


def test_malformed_flag_dsn_raises_config_003(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url("mysql://nope/db", None)
    assert exc_info.value.error_code == "CONFIG_003"
    assert exc_info.value.exit_code == 5  # #146: CONFIG family → config invalid
